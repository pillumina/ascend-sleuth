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


_MERGE_POINTER_RE = re.compile(r"(?:PR|#)\s?#?\d{2,6}")


def has_merge_pointer(text: str) -> bool:
    """卡文本里有没有任何 PR/issue 号——判据「待合入积压」分子的**唯一实现**。

    为什么口径定义在这里，而不是各读侧各写一份：它原先有两份——`ev_proposal --waterline` 扫全卡
    文本，`ev_board_data.collect_stats` 只扫决策链结论。于是同一时刻两个读数不等（实测 0 张 vs
    8 张），而技能让 agent 读前一个、面板与体检显示后一个：同一件事两个数，且都自称是判据
    `backlog_over` 的分子。口径只在这里定义一次，两边 import 它。

    为什么松匹配（任意 PR/issue 号即算有指针）：指针的历史写法不止一种——正式的一条
    （`合入指针回写：本卡随 PR #278 进入 main`）、结论里的散文（`改动随 PR #97 供人审`）、
    以及正文提到的 issue 号。收紧到"只认正式形态"会把 32 张早已合入的老卡重新计进积压
    （实测），把闸门引向"停产新候选"这个错动作；松匹配的代价是"提过 issue 号的卡被当成
    已回写"，那个方向只让读数偏乐观，不触发错误动作。
    """
    return bool(_MERGE_POINTER_RE.search(str(text or "")))


# 旧名保留：面板与既有脚本沿用它，行为与 has_merge_pointer 完全一致。
_has_any_ref = has_merge_pointer


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
    if all_pending:
        # 不加门禁、也不静默：这条命令在"这一批就是全部待回写卡"时是对的，混入旧批的卡就是假数据。
        # 把风险在读的那一刻说出来（原先只有 --from-prs 的 docstring 里写了，用户看不到）。
        print(f"注意：--all-pending 把 PR #{pr} 写给 {len(targets)} 张卡"
              f"（{'、'.join(p.stem for p in targets)}）——"
              "若其中有属于别的批的卡，那个指针就是假的（一张卡的真实出处只有一个批 PR）；"
              "拿不准时用 --mark-merged --from-prs（按已合入 PR 逐卡匹配）", file=sys.stderr)

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
        # 插入点：decisions 块的**末尾**（不是文件末尾）——有的卡在 decisions 之后还有
        # 别的顶层键（actual_cost / template_index…），追加到 EOF 会挂到那段里、把 YAML 写坏。
        lines = text.splitlines(keepends=True)
        di = next((i for i, ln in enumerate(lines) if ln.startswith("decisions:")), None)
        if di is None:
            skipped.append((p.stem, "找不到 decisions 块——交人处理"))
            continue
        end = di + 1
        def _in_block(ln):
            # 块内行 = 缩进行 / 空行 / **0 缩进的列表项**（有的卡把 decisions 条目写在列 0，
            # 只判缩进会把块在第一个条目处截断，插入点就落到块中间 → 写坏 YAML）
            return ln.startswith((" ", "\t", "- ")) or not ln.strip()
        while end < len(lines) and _in_block(lines[end]):
            end += 1
        block_end = end
        if dry_run:
            marked.append((p.stem, "dry-run"))
            continue
        # 追加块的缩进必须**跟卡自己的列表风格**：有的卡把 decisions 的条目写在 0 缩进
        # （`- who: agent`），有的写 2 缩进（`  - who: agent`）。写死一种就会让另一种卡
        # 解析失败——实测一次回写把 4 张卡写坏（YAML 解析失败）。
        m_indent = re.search(r"(?m)^(\s*)- ", "".join(lines[di:block_end]))
        indent = m_indent.group(1) if m_indent else "  "
        block = block_tpl.format(when=when, pr=pr)
        if indent != "  ":
            block = "".join((indent + ln[2:] if ln.startswith("  ") else ln) + "\n"
                            for ln in block.rstrip("\n").split("\n"))
        new = "".join(lines[:block_end]) + block + "".join(lines[block_end:])
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

# --from-prs 的 PR 列表深度：批量回写要够回溯到旧批。与水位上限（候选张数上限）不是一回事，
# 共用一个 --limit 时两者的默认值必然有一个是错的——实测默认 20 会漏掉更早的批 PR，
# 于是"已合入但指针没回写"的卡被读成未合入。两个默认值分开。
PRS_LIMIT_DEFAULT = 200


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


def impact(root: Path, component: str = "", min_attempts: int = 2):
    """同组件先例视图：按组件聚合历史尝试 × 验证方式 × 结局（同组件先例咨询的聚合形态）。

    为什么要有它：产卡前那句"别重复被拒方案"此前只是一句纪律——卡 schema 里没有
    `target_component` 字段（实测 0 张有），于是没有任何地方能按组件查历史。本视图用
    **确定性派生的改动落点**（卡文本里指到的仓库路径，来自面板同源归因）当组件键，
    `target_component` 存在时优先用它。有了它，"这个组件改过几次、结局如何"是一条命令。
    """
    import ev_board_data as EBD          # 同目录，复用归因口径（避免双源漂移）
    ideas = EBD.collect_ideas(root)
    rows = {}
    for c in ideas:
        key = str(c.get("target_component") or (c.get("surface_basis") or {}).get("path") or "（未归因）")
        r = rows.setdefault(key, {"attempts": 0, "by_status": {}, "cards": []})
        r["attempts"] += 1
        st = str(c.get("status"))
        r["by_status"][st] = r["by_status"].get(st, 0) + 1
        r["cards"].append((c.get("id"), st, str(c.get("created_at"))[:10], str(c.get("title"))[:52]))

    if component:
        picked = {k: v for k, v in rows.items() if component in k}
        if not picked:
            print(f"ev_proposal: 没有组件匹配「{component}」——用不带参数的 --impact 看全表", file=sys.stderr)
            return 2
    else:
        picked = {k: v for k, v in rows.items() if v["attempts"] >= min_attempts}

    print(f"同组件先例视图（共 {len(rows)} 个组件 / {len(ideas)} 张卡；下表列尝试 ≥{min_attempts} 次的）\n")
    for key, r in sorted(picked.items(), key=lambda kv: -kv[1]["attempts"]):
        outs = "、".join(f"{k}×{v}" for k, v in sorted(r["by_status"].items()))
        flag = "  ← 有结局分歧（先例可查）" if (r["by_status"].get("rejected") or r["by_status"].get("superseded")) else ""
        print(f"  {key}：{r['attempts']} 次（{outs}）{flag}")
        if component:
            for cid, st, day, title in sorted(r["cards"]):
                print(f"      {cid} {day} {st:<12} {title}")
    multi = [k for k, v in rows.items() if v["attempts"] >= 2]
    divergent = [k for k in multi if rows[k]["by_status"].get("rejected") or rows[k]["by_status"].get("superseded")]
    print(f"\n  汇总：{len(multi)} 个组件被 ≥2 张卡改过，其中 {len(divergent)} 个有结局分歧"
          "（只有这些组件的先例能告诉你「别重试」，其余是「改完又改」的累积）")
    return 0


def mark_merged_from_prs(root: Path, limit: int, dry_run: bool, prs_file: str = ""):
    """按已合入的 PR 列表**逐卡匹配**回写指针。

    为什么不能一条命令刷全部：`--all-pending <PR号>` 会把同一个号写给所有待回写卡——那是假数据
    （一张卡的真实出处只有一个批 PR）。本模式只为**在 PR 标题/正文里被点名**的卡回写，
    没被点名的如实报出来（不猜、不编），剩下的由人按 commit 信息补。
    """
    import json as _json
    import subprocess
    if prs_file:
        prs = _json.loads(Path(prs_file).read_text(encoding="utf-8"))
    else:
        r = subprocess.run(["gh", "pr", "list", "--state", "merged", "--limit", str(limit),
                            "--json", "number,title,body"], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"ev_proposal: 取 PR 列表失败（gh 未登录？）：{r.stderr.strip()[:160]}", file=sys.stderr)
            return 2
        prs = _json.loads(r.stdout or "[]")
    # 每张卡取**最早**点名它的 PR（批次按时间推进，后来的 PR 不会回溯引用旧卡）
    by_card = {}
    for pr in sorted(prs, key=lambda x: x.get("number") or 0):
        blob = f"{pr.get('title') or ''}\n{pr.get('body') or ''}"
        for m in re.finditer(r"EV-\d{4}-\d{3,}", blob):
            cid = m.group(0)
            by_card.setdefault(cid, pr.get("number"))
    pending, matched, unmatched = [], {}, []
    for f in sorted((root / IDEAS_DIR).glob("EV-*.yaml")):
        doc = load_yaml(f) or {}
        if doc.get("status") != "validated":
            continue
        txt = f.read_text(encoding="utf-8")
        if _has_any_ref(txt):
            continue
        cid = str(doc.get("id") or f.stem)
        pending.append(cid)
        if cid in by_card:
            matched.setdefault(by_card[cid], []).append(cid)
        else:
            unmatched.append(cid)
    # 第二遍：按 commit 追溯——历史卡早于"卡内写 PR 号"的约定，但它们的改动commit 在 main 上。
    # 取最早点名该卡的非 merge commit，再取**最早包含它的 merge**（= 带它进 main 的那个 PR）。
    import subprocess as _sp
    traced, still = {}, []
    for cid in unmatched:
        r = _sp.run(["git", "log", "--all", "--no-merges", "--grep", cid, "--format=%H"],
                    capture_output=True, text=True)
        shas = [x for x in (r.stdout or "").split() if x]
        if not shas:
            still.append(cid)
            continue
        sha = shas[-1]                      # 最早的一次提交
        m = _sp.run(["git", "log", "--merges", "--ancestry-path", f"{sha}..origin/main",
                     "--format=%s", "--reverse"], capture_output=True, text=True)
        first_merge = next((ln for ln in (m.stdout or "").splitlines() if ln.strip()), "")
        pm = re.search(r"pull request #(\d+)", first_merge)
        if pm:
            traced.setdefault(int(pm.group(1)), []).append(cid)
        else:
            still.append(cid)
    for pr_no, cards in traced.items():
        matched.setdefault(pr_no, []).extend(cards)
    unmatched = still
    print(f"待回写 {len(pending)} 张：按 PR 点名 {sum(len(v) for k, v in matched.items() if k in by_card.values())} 张"
          f" + 按 commit 追溯 {sum(len(v) for v in traced.values())} 张"
          f"（合计落在 {len(matched)} 个 PR）、仍未匹配 {len(unmatched)} 张")
    if unmatched:
        print("  未匹配（不猜、不编，交人按 commit 信息补）：" + "、".join(unmatched[:12])
              + ("…" if len(unmatched) > 12 else ""))
    rc = 0
    for pr_no, cards in sorted(matched.items()):
        if pr_no is None:
            continue
        rc |= mark_merged(root, pr_no, cards, all_pending=False, dry_run=dry_run)
    return rc


def main():
    ap = argparse.ArgumentParser(description="self-evolve 产卡辅助")
    ap.add_argument("--next", action="store_true", help="打印下一个卡号")
    ap.add_argument("--new", action="store_true", help="生成新卡骨架")
    ap.add_argument("--list", action="store_true", help="列现有卡")
    ap.add_argument("--mark-merged", metavar="PR", nargs="?", const="",
                    help="把合入指针回写进卡的 decisions（追加，保留注释）；"
                         "配 --from-prs 时可省略 PR 号（按已合入 PR 逐卡匹配）")
    ap.add_argument("--card", action="append", default=[], help="配合 --mark-merged：指定卡号（可多次）")
    ap.add_argument("--all-pending", action="store_true",
                    help="配合 --mark-merged：选全部「已验证且无该 PR 指针」的卡"
                         "（会把同一个号写给全部；混入旧批的卡即假数据，优先 --from-prs）")
    ap.add_argument("--dry-run", action="store_true", help="配合 --mark-merged：只打印不落盘")
    ap.add_argument("--from-prs", action="store_true",
                    help="配合 --mark-merged：按已合入 PR 逐卡匹配回写（不用一个号刷全部）")
    ap.add_argument("--prs-file", default="", help="配合 --from-prs：从 JSON 文件读 PR 列表（默认用 gh 拉）")
    ap.add_argument("--impact", metavar="组件", nargs="?", const="", default=None,
                    help="同组件先例视图（给组件名则只看它，不给则列尝试≥2 次的全部）")
    ap.add_argument("--waterline", action="store_true", help="打印候选水位（超限退 1）")
    ap.add_argument("--limit", type=int, default=None,
                    help=f"配合 --waterline：候选上限（默认 {WATERLINE_DEFAULT}）；"
                         f"配合 --from-prs：拉取多少个已合入 PR（默认 {PRS_LIMIT_DEFAULT}）")
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
    elif args.mark_merged is not None and args.from_prs:
        # PR 号可省略（--mark-merged --from-prs）：逐卡匹配的出处由 PR 列表决定，不是一个号
        sys.exit(mark_merged_from_prs(root, args.limit or PRS_LIMIT_DEFAULT,
                                      args.dry_run, args.prs_file))
    elif args.mark_merged is not None:
        sys.exit(mark_merged(root, args.mark_merged, args.card, args.all_pending, args.dry_run))
    elif args.impact is not None:
        sys.exit(impact(root, args.impact))
    elif args.waterline:
        sys.exit(waterline(root, args.limit or WATERLINE_DEFAULT, args.json))
    else:
        ap.print_help()


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
