#!/usr/bin/env python3
# ev_proposal.py —— self-evolve 产卡辅助：卡号分配 + 卡骨架生成 + 卡概览
#
# self-evolve skill 执行"产候选卡"时的机械辅助（原则二/九：机械环节脚本化，
# agent 不手动数卡号/不手写易错骨架）：
#   1. 分配下一个 EV 卡号（读 proposals/ideas/ 现有卡，自动递增）
#   2. 生成卡骨架（从 examples/sample-idea.yaml 复制，填好 id/created_at，
#      其余字段留空待 agent 填）——避免格式错误
#   3. 卡概览（--list）：列现有卡 id/title/status/authorization，供起草时
#      查重与冲突检测（orchestration §5.2）
#
# 用法：
#   python3 scripts/ev_proposal.py --next          # 打印下一个卡号（如 EV-2026-002）
#   python3 scripts/ev_proposal.py --new           # 生成新卡骨架文件并打印路径
#   python3 scripts/ev_proposal.py --list          # 现有卡概览
#   python3 scripts/ev_proposal.py --status <id> <new_status>   # 推进卡状态（+ 追加 decisions 提示）
#
# 注意：卡状态推进涉及授权与验证语义（见 pipeline §7 状态机），本脚本只提供
# 机械辅助 + 校验提示，不自动改 status 语义——状态变更的合理性由 agent 依设计
# 判断，decisions 追加由 agent/人写入。

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

from _stdio import write_text_lf

IDEAS_DIR = "proposals/ideas"
TEMPLATE = "examples/sample-idea.yaml"


def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def next_id(root: Path) -> str:
    """下一个卡号 = max(文件名里的号, 卡内 `id:` 字段的号) + 1。

    为什么两处都看（2026-09-10 修）：只看 `id:` 字段时，一旦文件名与它内部的 `id:`
    不一致（复制粘贴卡时的常见手误，如文件叫 EV-2026-099.yaml 而内容是 `id: EV-2026-001`），
    算出的"下一个号"会撞上一个**已存在的文件名**；而 make_new 是直接覆盖写——于是静默
    吃掉一张既有卡。取两边最大值，让分配结果同时避开"已用号"与"已占文件名"。
    """
    year = datetime.now().year
    max_n = 0
    for f in (root / IDEAS_DIR).glob("EV-*.yaml"):
        candidates = []
        doc = load_yaml(f)
        if isinstance(doc, dict):
            candidates.append(str(doc.get("id", "")))
        candidates.append(f.stem)          # 文件名也算一路（防文件名/字段不一致）
        for cid in candidates:
            # 格式 EV-YYYY-NNN
            parts = cid.split("-")
            if len(parts) == 3 and parts[1] == str(year):
                try:
                    max_n = max(max_n, int(parts[2]))
                except ValueError:
                    pass
    return f"EV-{year}-{max_n + 1:03d}"


def make_new(root: Path) -> Path:
    cid = next_id(root)
    tpl = root / TEMPLATE
    out = root / IDEAS_DIR / f"{cid}.yaml"
    # 覆盖保护（2026-09-10）：本函数的写入是"直接覆盖"。一旦算出的号已被占用
    # （文件名/字段不一致、手工放了同名文件、并发产卡），覆盖写会**静默吃掉既有卡**——
    # 卡是审计资产，静默丢失不可接受。这里宁可失败也不覆盖，让人/agent 显式处理。
    if out.exists():
        raise FileExistsError(
            f"{out} 已存在——拒绝覆盖（EV 卡是审计资产，静默覆盖=丢决策链）。"
            "请先处理该文件：填完它、改名，或确认不该存在后删除，再重跑 --new。")
    if tpl.exists():
        # 复制模板，替换 id 与 created_at
        txt = tpl.read_text(encoding="utf-8")
        txt = txt.replace("id: EV-2026-001", f"id: {cid}")
        txt = txt.replace("created_at: 2026-09-01", f"created_at: {datetime.now().date().isoformat()}")
        write_text_lf(out, txt, encoding="utf-8")
    else:
        write_text_lf(out, f"# {cid} idea 卡骨架（模板缺失，手填）\nid: {cid}\n", encoding="utf-8")
    return out


def list_cards(root: Path):
    rows = []
    for f in sorted((root / IDEAS_DIR).glob("*.yaml")):
        doc = load_yaml(f)
        if not isinstance(doc, dict):
            rows.append((f.stem, "?", "?", "解析失败"))
            continue
        rows.append((
            str(doc.get("id", f.stem)),
            str(doc.get("title", ""))[:60],
            str(doc.get("status", "?")),
            str(doc.get("authorization", "?")),
        ))
    print(f"{'id':<14} {'status':<14} {'auth':<8} title")
    for cid, title, status, auth in rows:
        print(f"{cid:<14} {status:<14} {auth:<8} {title}")


# ---------------------------------------------------------------- 合入指针回写
# 为什么需要它：判据「待合入积压」数的是"已验证但没有合入指针的卡"，而**指针只能靠人/agent
# 在卡文本里写一句 PR 号**。实测代价：一批 7 张卡随同一个 PR 合入 main，7 张全部无指针——
# 判据读出来的是"未合入"，实际是"已合入但没人回写"，读数与事实方向都反了（判据的 action
# 会把人引向"暂停产卡"，而真正缺的动作是回写）。回写因此不能停在纪律上：写进脚本，一条命令。
def _top_level_keys(text: str):
    """按出现顺序取顶层 key（只认行首无缩进的 `key:`）。"""
    keys = []
    for line in text.splitlines():
        if line and not line[0].isspace() and not line.startswith("#") and ":" in line:
            k = line.split(":", 1)[0].strip()
            if k and " " not in k:
                keys.append(k)
    return keys


def _has_ref(text: str, pr):
    return bool(re.search(r"(?:PR|#)\s?#?" + re.escape(str(pr)) + r"\b", text))


def _has_any_ref(text: str):
    """卡文本里有没有任何合入指针（与 ev_board_data.extract_pr_refs 同一形态）。"""
    return bool(re.search(r"(?:PR|#)\s?#?\d{2,6}", text))


def mark_merged(root: Path, pr, card_ids, all_pending: bool, dry_run: bool):
    """把合入指针追加进卡的 decisions（只追加、不动既有内容、保留注释）。

    拒绝条件（宁可失败不猜）：卡不存在 / 顶层最后一个 key 不是 decisions（追加会破坏结构）。
    """
    if not pr:
        print("ev_proposal: --mark-merged 需要 PR 号（如 --mark-merged 242）", file=sys.stderr)
        return 2
    targets = []
    if all_pending:
        targets = [f for f in sorted((root / IDEAS_DIR).glob("EV-*.yaml"))
                   if (load_yaml(f) or {}).get("status") == "validated"
                   and not _has_ref(f.read_text(encoding="utf-8"), pr)]
    for cid in card_ids or []:
        p = root / IDEAS_DIR / f"{cid}.yaml"
        if not p.exists():
            print(f"ev_proposal: 卡不存在 {cid}（{p}）", file=sys.stderr)
            return 2
        if p not in targets:
            targets.append(p)
    if not targets:
        print("ev_proposal: 没有可回写的卡（--all-pending 只选「已验证且无该 PR 指针」的卡）")
        return 0

    block_tpl = ("  - who: agent\n"
                 "    when: {when}\n"
                 "    type: action\n"
                 "    conclusion: \"合入指针回写：本卡（及其结论）随 PR #{pr} 进入 main"
                 "（回写由 evolve 批次收尾执行，供判据「待合入积压」读取）\"\n")
    when = datetime.now().date().isoformat()
    marked, skipped = [], []
    for p in targets:
        text = p.read_text(encoding="utf-8")
        if _has_ref(text, pr):
            skipped.append((p.stem, "已有该 PR 指针"))
            continue
        keys = _top_level_keys(text)
        if keys and keys[-1] != "decisions":
            skipped.append((p.stem, f"顶层最后一段是 {keys[-1]} 而不是 decisions——追加会破坏结构，需人处理"))
            continue
        if dry_run:
            marked.append((p.stem, "dry-run"))
            continue
        new = text if text.endswith("\n") else text + "\n"
        new += block_tpl.format(when=when, pr=pr)
        write_text_lf(p, new, encoding="utf-8")
        marked.append((p.stem, "已回写"))

    for cid, why in marked:
        print(f"  ✓ {cid}: {why}")
    for cid, why in skipped:
        print(f"  — {cid}: 跳过（{why}）")
    print(f"ev_proposal --mark-merged {pr}: 回写 {len(marked)} 张、跳过 {len(skipped)} 张"
          + ("（dry-run，未落盘）" if dry_run else ""))
    return 2 if any("破坏结构" in w for _c, w in skipped) else 0


# ---------------------------------------------------------------- 候选水位（积压治理）
# 设计处（orchestration §2.4）把「候选水位上限」标为蓝图态，启用条件是"候选积压真实发生
# （>20 在池）"。实测该条件早已满足（积压单调上升到数十张、日均产卡近十张），而 skill 正文
# 那句"水位超限时只记信号不产卡"没有数值也没有读数——规则只在 prose 里，等于没有。
# 本命令把它变成一条可机械读取的读数 + 退出码：≥上限退 1（下游按"只记信号不产卡"处理）。
WATERLINE_DEFAULT = 20


def waterline(root: Path, limit: int, as_json: bool = False):
    pending, in_pool, other = [], [], 0
    for f in sorted((root / IDEAS_DIR).glob("EV-*.yaml")):
        doc = load_yaml(f)
        if not isinstance(doc, dict):
            other += 1
            continue
        cid = str(doc.get("id") or f.stem)
        status = doc.get("status")
        if status == "in_experiment":
            in_pool.append(cid)
        elif status == "validated" and not _has_any_ref(f.read_text(encoding="utf-8")):
            pending.append(cid)
    over = len(pending) >= limit
    if as_json:
        print(json.dumps({"limit": limit, "pending_review": len(pending), "in_pool": len(in_pool),
                          "over": over, "pending_ids": pending, "in_pool_ids": in_pool},
                         ensure_ascii=False, indent=2))
    else:
        print(f"候选水位：待回写/待合入 {len(pending)}（上限 {limit}）· 未闭合在池 {len(in_pool)}")
        print(f"  读数 = 「已验证且无合入指针」的卡数（回写指针后该数即真实待合入量；见 --mark-merged）")
        if over:
            print(f"  ✗ 超限：本轮**只记信号不产卡**，先消化积压（设计处 orchestration §2.4）")
        else:
            print("  ✓ 未超限")
    return 1 if over else 0


def main():
    ap = argparse.ArgumentParser(description="self-evolve 产卡辅助")
    ap.add_argument("--next", action="store_true", help="打印下一个卡号")
    ap.add_argument("--new", action="store_true", help="生成新卡骨架")
    ap.add_argument("--list", action="store_true", help="列现有卡")
    ap.add_argument("--mark-merged", metavar="PR", help="把合入指针回写进卡的 decisions（追加，保留注释）")
    ap.add_argument("--card", action="append", default=[], help="配合 --mark-merged：指定卡号（可多次）")
    ap.add_argument("--all-pending", action="store_true",
                    help="配合 --mark-merged：选全部「已验证且无该 PR 指针」的卡")
    ap.add_argument("--dry-run", action="store_true", help="配合 --mark-merged：只打印不落盘")
    ap.add_argument("--waterline", action="store_true", help="打印候选水位（超限退 1）")
    ap.add_argument("--limit", type=int, default=WATERLINE_DEFAULT, help="配合 --waterline：上限")
    ap.add_argument("--json", action="store_true", help="配合 --waterline：机器可读")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()
    root = args.root.resolve()
    if args.next:
        print(next_id(root))
    elif args.new:
        try:
            p = make_new(root)
        except FileExistsError as e:
            # 覆盖保护触发：非零退出 + 一行可读原因（不抛 traceback，agent 能直接照做）
            print(f"ev_proposal: 拒绝产卡——{e}", file=sys.stderr)
            sys.exit(2)
        print(f"已生成骨架: {p}")
        print(f"ID: {p.stem} —— 按 examples/sample-idea.yaml 填字段后跑 verify_proposals.py")
    elif args.list:
        list_cards(root)
    elif args.mark_merged:
        sys.exit(mark_merged(root, args.mark_merged, args.card, args.all_pending, args.dry_run))
    elif args.waterline:
        sys.exit(waterline(root, args.limit, args.json))
    else:
        ap.print_help()


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
