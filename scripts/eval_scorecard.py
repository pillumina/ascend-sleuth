#!/usr/bin/env python3
# eval_scorecard.py —— 回放观测的结构化账本（eval/scorecard.yaml）
#
# 为什么需要它：回放结果此前只写在 fixture 的头注散文里（形如
# 「本条回放结果：candidates=Y rank=2 path=primary」），完整报告落 gitignore 的
# eval-reports/。于是有两件事在数据上不可见：
#   ① 仓库里没有「当前命中构成」这个数——要读 24 个文件的散文才能拼出来；
#   ② 夹具改了而没人重跑，与「跑过了、结果就是这样」完全不可区分。
# 本脚本把观测搬进结构化账本，并让"夹具已变"变成机械可判的红色。
#
# 判据强度（如实标注，原则六/十）：
#   - **硬门**：夹具字节哈希与账本不符 → 红。夹具就是量尺，量尺被改过就该重跑一次
#     （与 holdout 的封存哈希同一条思路，但覆盖面不同：holdout 只管维护者封存的那部分，
#     本账本管**全部** fixture，且不阻止改夹具——只要求改完重跑并重新记账）。
#   - **软信号**：目标 case 的内容哈希（取自 knowledge/_index.yaml）变了 → 进「待复核」清单，
#     **不判红**。case 的合法内容变更（groom 修订 fix/symptoms）不该让无关 PR 变红；
#     硬判红会变成对每次 case 变更的阻塞，与错误代价不匹配。
#   - **硬门（契约冲突）**：fixture 的 assertion 是 `top-3`（不含 or-miss-documented）、
#     账本却记着 miss → 红。这是夹具自述期望与观测的矛盾，改哪一侧都是人的决定，机器只负责喊。
#   - **不判准确率**：账本记的是"上次观测到什么"，不是"现在能不能命中"。
#     准确率门禁仍要 agent 跑回放（docs/guide/eval.md 门禁分级），本脚本不假装它是硬门。
#
# 已知局限（不掩盖）：账本读的是 fixture 头注与 expected 块。若有人重跑了回放却没更新
# fixture 头注，本脚本无法发现（观测与现实的差在头注这一层就丢了）——这正是记账流程
# 要求"先更新头注、再 --build"的原因，也是本账本强度的上界。
#
# 用法：
#   python3 scripts/eval_scorecard.py --build    # 从 fixture 头注 + expected + 索引重建账本（写文件）
#   python3 scripts/eval_scorecard.py --check    # CI：覆盖 + 夹具哈希 + 契约冲突（红）；case 漂移（不红）
#   python3 scripts/eval_scorecard.py --list     # 只打印聚合（人读，不改文件、不判红）
#
# 退出码：0 = 一致；1 = 有不一致；2 = 用法错。
#
# 记账流程（改完夹具/跑完回放后）：更新 fixture 头注的「回放结果」行 → `--build` → 连同夹具一起提交。

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

import yaml

from _stdio import pin_utf8_stdio, write_text_lf

SCORECARD = "eval/scorecard.yaml"
GOLDEN = "eval/golden"
INDEX = "knowledge/_index.yaml"

# 头注里的观测行：「candidates=Y rank=2 path=primary」。path 可缺（历史记录形态不一），
# 缺时不猜——只记 rank 与 candidates，原文留在 raw 字段供人核。
_OBS_RE = re.compile(r"candidates=([YN])\s+rank=(\S+)\s*(?:path=([A-Za-z][\w-]*))?")
_RANK_UNKNOWN = {"none", "None", "-", "null"}

STATUS_HIT = "hit"
STATUS_MISS = "miss"
STATUS_NOT_RECORDED = "not_recorded"


def sha256_of(path: Path) -> str:
    # 归一 CRLF：哈希按字节算，Windows 检出 CRLF 会让同一份内容被判"已变"（同 holdout 的理由）。
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def header_text(path: Path) -> str:
    """取文件开头的注释块（首个非注释行之前）。观测行只可能写在这里。"""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            lines.append(line.lstrip("#").strip())
        elif line.strip() == "" and lines:
            continue
        else:
            break
    return "\n".join(lines)


def parse_observed(header: str) -> dict:
    m = _OBS_RE.search(header)
    if not m:
        return {"status": STATUS_NOT_RECORDED, "rank": None, "path": None,
                "candidates": None, "raw": ""}
    cand, rank_tok, path = m.group(1), m.group(2), m.group(3)
    rank = None if rank_tok in _RANK_UNKNOWN else (int(rank_tok) if rank_tok.isdigit() else None)
    hit = cand == "Y"
    raw_line = next((ln.strip() for ln in header.splitlines() if "回放结果" in ln), "")
    return {
        "status": STATUS_HIT if hit else STATUS_MISS,
        "rank": rank,
        "path": path,
        "candidates": hit,
        "raw": raw_line,
    }


def load_fixture(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    exp = doc.get("expected") or {}
    # case 标识在 fixture 里有三种写法（case_id / case），全都认；认不出记空串，由 --check 报出。
    case_id = str(exp.get("case_id") or exp.get("case") or doc.get("case_id") or "")
    ns = str(exp.get("namespace") or "").rstrip("/")
    assertion = str(exp.get("assertion") or "").strip()
    return {
        "fixture": path.name,
        "case_id": case_id,
        "covers": ns,
        "assertion": assertion,
        "observed": parse_observed(header_text(path)),
    }


def index_case_hashes(root: Path) -> dict:
    """{case_id: hash} —— 取自生成的 knowledge/_index.yaml（build_index --check 保证它新鲜）。"""
    p = root / INDEX
    if not p.exists():
        return {}
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out = {}
    for ns_cats in (doc.get("namespaces") or {}).values():
        for entries in (ns_cats or {}).values():
            for e in entries or []:
                if isinstance(e, dict) and e.get("id"):
                    out[str(e["id"])] = str(e.get("hash") or "")
    return out


def recorded_before(root: Path, fixture: str) -> str | None:
    """该 fixture 最后一次内容变动的提交日期——观测不可能晚于它（上界，不是观测日期）。

    拿不到（无 git / 未提交 / 该文件无历史）时返回 None，不猜。
    """
    rel = f"{GOLDEN}/{fixture}"
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%cs", "--", rel],
                           cwd=str(root), capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (r.stdout or "").strip()
    return out or None


# ---------------------------------------------------------------- 子命令
def build_entries(root: Path) -> list:
    hashes = index_case_hashes(root)
    entries = []
    for f in sorted((root / GOLDEN).glob("*.fixture.yaml")):
        e = load_fixture(f)
        e["fixture_sha256"] = sha256_of(f)
        e["case_sha256"] = hashes.get(e["case_id"])
        e["observed"]["recorded_before"] = recorded_before(root, f.name)
        entries.append(e)
    return entries


def dump_yaml(entries: list) -> str:
    doc = {
        "version": 1,
        "note": ("回放观测账本（生成物，由 scripts/eval_scorecard.py --build 重建）。"
                 "observed 记的是「上次回放观测到什么」，不是「现在能不能命中」；"
                 "fixture_sha256 用于判定夹具是否在观测之后被改过，case_sha256 用于"
                 "标出目标 case 是否已变（待复核，不阻塞）。"),
        "entries": entries,
    }
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=4096)


def aggregate(entries: list) -> dict:
    """聚合口径：hit 但排在第三名之外单列（`beyond`）——它不是 miss，也不该混进命中数里。

    为什么单列：低分 case 在自身症状族里排到第 6/17 是实测出现过的事（跨队语料两条 fixture），
    读成「命中」会让聚合数看起来比实际好。
    """
    def rank(e):
        return e["observed"].get("rank")

    top1 = sum(1 for e in entries if rank(e) == 1)
    top3 = sum(1 for e in entries if rank(e) is not None and rank(e) <= 3)
    hit = sum(1 for e in entries if e["observed"].get("status") == STATUS_HIT)
    miss = sum(1 for e in entries if e["observed"].get("status") == STATUS_MISS)
    unrec = sum(1 for e in entries if e["observed"].get("status") == STATUS_NOT_RECORDED)
    return {"total": len(entries), "top1": top1, "top3": top3, "hit": hit,
            "beyond": hit - top3, "miss": miss,
            "not_recorded": unrec, "recorded": len(entries) - unrec}


def fmt_agg(a: dict) -> str:
    return (f"{a['total']} 条条目；有观测 {a['recorded']}"
            f"（命中第一 {a['top1']}／前三 {a['top3']}／前三外 {a['beyond']}，未命中 {a['miss']}）"
            f"，未记录 {a['not_recorded']}")


def cmd_build(root: Path) -> int:
    entries = build_entries(root)
    write_text_lf(root / SCORECARD, dump_yaml(entries))
    print(f"scorecard：已重建 {SCORECARD}（{fmt_agg(aggregate(entries))}）")
    return 0


def cmd_list(root: Path) -> int:
    entries = build_entries(root)  # 只读：现算现看，不写文件
    print(f"scorecard：{fmt_agg(aggregate(entries))}")
    stale_case = [e for e in entries if e["case_id"] and e["case_sha256"]
                  and e["case_sha256"] != current_case_hash(root, e["case_id"])]
    if stale_case:
        print(f"  待复核（目标 case 内容已变，建议重跑）：{len(stale_case)} 条"
              f"——{'; '.join(e['fixture'] for e in stale_case)}")
    return 0


def current_case_hash(root: Path, case_id: str) -> str | None:
    return index_case_hashes(root).get(case_id)


def cmd_check(root: Path) -> int:
    p = root / SCORECARD
    if not p.exists():
        print(f"未找到 {SCORECARD}——账本未建立；跑 `python3 scripts/eval_scorecard.py --build` 生成")
        return 1
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    entries = [e for e in (doc.get("entries") or []) if isinstance(e, dict) and e.get("fixture")]

    fixtures = {f.name: f for f in sorted((root / GOLDEN).glob("*.fixture.yaml"))}
    by_name = {str(e["fixture"]): e for e in entries}
    hashes = index_case_hashes(root)

    bad, warn = [], []
    for name, f in fixtures.items():
        e = by_name.get(name)
        if e is None:
            bad.append(f"{name}: 夹具未入账本——跑 `--build` 记账（没跑过回放就记 not_recorded，别空着）")
            continue
        want = str(e.get("fixture_sha256") or "")
        got = sha256_of(f)
        if got != want:
            bad.append(f"{name}: 夹具内容已变（账本 {want[:12]}…／实测 {got[:12]}…）——"
                       "重跑回放 → 更新头注「回放结果」→ 再 --build")
            continue
        cur = load_fixture(f)
        if cur["case_id"] != str(e.get("case_id") or ""):
            bad.append(f"{name}: 账本 case_id={e.get('case_id')!r} 与夹具 expected={cur['case_id']!r} 不一致")
        obs = e.get("observed") or {}
        if obs.get("status") == STATUS_MISS and _asserts_hit(cur["assertion"]):
            bad.append(f"{name}: 断言冲突——assertion={cur['assertion']!r} 要求命中，账本记的是 miss"
                       "（放宽断言或修命中，二者都要人决定）")
        cid = str(e.get("case_id") or "")
        if cid and cid not in hashes:
            # 构造示例（example.*）按 docs/guide/eval.md 的分类天然指向不存在的 case，不报——
            # 常驻噪声会被读成"总是红的"，反而盖掉真信号。真实 case 投影指向未收录 case 才是信号。
            if not name.startswith("example."):
                warn.append(f"{name}: 目标 case {cid} 不在 knowledge/ 索引中（夹具指向已退休/未收录的 case）")
        elif cid and e.get("case_sha256") and hashes.get(cid) != e.get("case_sha256"):
            warn.append(f"{name}: 目标 case {cid} 内容已变（账本 {str(e['case_sha256'])[:12]}…／"
                        f"当前 {str(hashes.get(cid))[:12]}…）——待复核，不阻塞")

    for name in by_name:
        if name not in fixtures:
            bad.append(f"{name}: 账本条目指向不存在的夹具（夹具被删或改名）")

    agg = aggregate(entries)
    for w in warn:
        print(f"  ! {w}")
    if bad:
        print(f"scorecard --check: {len(bad)} 项不一致")
        for b in bad:
            print(f"  - {b}")
        print(f"  现状：{fmt_agg(agg)}")
        return 1
    print(f"scorecard：OK（{fmt_agg(agg)}；待复核 {len(warn)} 条）")
    return 0


def _asserts_hit(assertion: str) -> bool:
    """assertion 是否要求"必须命中"——`top-3-or-miss-documented` 允许记录在案的 miss。"""
    a = (assertion or "").lower()
    return bool(a) and "miss" not in a


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="回放观测账本（观测在 eval/scorecard.yaml）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--build", action="store_true", help="重建账本（写 eval/scorecard.yaml）")
    g.add_argument("--check", action="store_true", help="CI：覆盖 + 夹具哈希 + 契约冲突")
    g.add_argument("--list", action="store_true", help="打印聚合（不改文件）")
    ap.add_argument("--root", default=None, help="仓库根（默认脚本所在目录的上一级）")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    if args.build:
        return cmd_build(root)
    if args.list:
        return cmd_list(root)
    return cmd_check(root)


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
