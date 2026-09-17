#!/usr/bin/env python3
# settle_s2_feedback.py —— 把 S2 issue-replay 结果结算到 case 的内容验证记录
#
# 目的（selfevolve-loop 重构）：S2 replay 对照的是**外部 ground truth**（issue 的实际
# resolution / 维护者 fix PR / committer 确认），所以它的结果本身就是 feedback——
# 只是反馈对象是"case 内容是否正确（检索+根因指向）"，不是"fix 在现场是否有效"
# （后者仍只认 S1）。此前 S2 结果躺在 .s2-replay/*.result.yaml 里从不回流，等于把
# 唯一不依赖人的高质量反馈源丢掉了。
#
# 结算规则：
#   - tier2_hit=true + hit_case 非空 + root_cause_ok=true
#       → case 的 validation_record.consistent += 1（内容与外部 resolution 一致）
#         若该 case 的来源正是被 replay 的 issue（self-referential，run §3 自我参照
#         污染）→ 记 self_consistent（如实标注，不虚增"外部验证"权重）
#   - tier2_hit=true + hit_case 非空 + root_cause_ok=false
#       → validation_record.inconsistent += 1（命中但结论与 resolution 不符 =
#         case 内容错/过时/判别力不足的复审信号——这是此前完全没有的通道）
#   - tier2_hit=false → 覆盖缺口信号（无 case 命中），不结算 case（补 case 候选走
#     EV 卡机制，非本脚本职权）
#
# 口径纪律：validation_record 与 confidence 分开——confidence.hits/mis 只承载 S1
# 现场 resolve（"fix 在你环境解决了没有"）；validation_record 承载"内容被外部验证"
# （S2/上游确认）。两种信号不混算（execution §4.1 的 resolve 只认 S1 在此保留为
# confidence 语义，S2 另立验证记录，不再被降格为无落点的旁证）。
#
# 幂等：结算游标记在 ingest-state.json 的 sources.<key>.s2_feedback 下
#   （key = issue + result 内容 hash——同 settle_trace_feedback 哲学，重复跑不重复累积）。
#
# 用法（groom 周批 / replay 批量后，串行）：
#   python3 scripts/settle_s2_feedback.py --state ingest-state.json [--dry-run|--apply]
#   --dry-run（默认）：输出将要发生的 diff，不写任何文件
#   --apply：写回 case YAML（diff 走 knowledge_modification PR——脚本本身不改 git）
#
# 输出：每个 case 的 validation_record 变更 diff + inconsistent 复审候选清单。

import argparse
import hashlib
import json
import re
from pathlib import Path

import yaml

from _stdio import write_text_lf
from settle_trace_feedback import SETTLE_STATE_REL, load_cursors, resolve_default_state  # noqa: E402
from exec_log_path import resolve_rel  # noqa: E402

REPLAY_DIR = Path(".s2-replay")


def iso_week_now():
    from datetime import date
    d = date.today()
    return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"


def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def find_case(kb_root: Path, case_id: str):
    """按 id 定位 case 文件，返回 (path, doc, case)。"""
    if not case_id:
        return None
    for case_f in kb_root.rglob("*.yaml"):
        if "_archive" in str(case_f) or case_f.name == "_index.yaml":
            continue
        doc = load_yaml(case_f)
        if not isinstance(doc, dict):
            continue
        for c in doc.get("cases", []):
            if c.get("id") == case_id:
                return (case_f, doc, c)
    return None


def case_issue_sources(case) -> set:
    """case 的来源 issue 号集合（判定 self-referential——replay 的 issue 是否正是
    case 的沉淀来源。实际落点在 case 的 references 字段（URL 列表）或 source_ref）。"""
    nums = set()
    for key in ("references", "sources", "urls"):
        for u in case.get(key, []) or []:
            m = re.search(r"issues?/(\d+)", str(u))
            if m:
                nums.add(int(m.group(1)))
    return nums


def _strings(node):
    """递归取一条 case 里所有字符串叶子（用于"正文有没有引用某个 issue 号"的扫描）。"""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _strings(v)


def case_cites_issue(case, issue_no) -> bool:
    """case 正文里是否**引用**了这个 issue 号（作为来源或作为旁证）。

    独立性判据（2026-09 加，起因是一次实测）：cross 样本要当"独立"外部验证，前提是这个
    issue 没有参与该 case 的撰写。实测教训——#2723（同签名、有维护者结论）一度被当成
    VLLM-ASC-1767 的合格 cross 样本，但那条 case 的 verification.detail 里就写着
    「#2723（同签名，2025-12-15 关闭 COMPLETED）上同一维护者记为…」：命中的结论正是写 case
    时从它那儿读来的，记成 consistent 等于把同一份证据数两次（与自证同一条纪律）。
    识别形态：`issues/<n>`、`pull/<n>`、`#<n>`（含 `issue #<n>` / `PR #<n>`）。

    **强度如实标注（半硬）**：它只挡得住"正文点名了这个号"这一种。case 与样本出自同一族
    判词、同一 fix PR 的关联无法机械识别——所以 `consistent` 的语义只能是"该 issue 不是它的
    来源、也未在正文被引用"，**不是**"信息独立"。别把它读成后者。
    """
    pats = (rf"issues?/{issue_no}\b", rf"pulls?/{issue_no}\b", rf"#{issue_no}\b")
    return any(re.search(p, s) for s in _strings(case) for p in pats)


def settle(root: Path, state_path: Path, apply: bool, migrate_from=None):
    state_path = Path(state_path)
    # 游标：登记的共享运行时件（gitignored，锚主检出）。与 S1 结算同一条落点纪律——
    # 进 git 会让每次结算都变成一次 PR（EV-2026-096）。
    state, migrated = load_cursors(state_path, migrate_from)
    settled = state.setdefault("_s2_feedback", {})
    if migrated:
        print(f"[migrate] 从 {migrated} 迁入 {len(settled)} 条既有游标\n")
    replay_dir = root / REPLAY_DIR
    kb_root = root / "knowledge"

    diffs = []
    recheck = []  # inconsistent → 复审候选
    skip_none = []  # 不可证伪样本（issue 无外部结论）→ 不结算
    for f in sorted(replay_dir.glob("*.result.yaml")):
        res = load_yaml(f)
        if not isinstance(res, dict):
            continue
        issue = f.stem.replace(".result", "")
        # 幂等键：issue + result 内容 hash
        content_hash = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
        if settled.get(issue) == content_hash:
            continue

        hit_case = res.get("hit_case") or ""
        tier2_hit = res.get("tier2_hit")
        rc_ok = res.get("root_cause_ok")
        # 可证伪性闸门：样本的 issue 若**没有外部结论**（维护者判词 / 已合入 fix PR 都没有），
        # 那么"结论是否一致"这个判断本身就没有真值——既不能记 consistent（无从判对），
        # 也不能记 inconsistent（会把一个假复审信号压到 case 上）。
        # 声明方式：result 里的 `ground_truth`（none | maintainer-conclusion | fix-merged | both）。
        # 缺席按现状（向后兼容：23 条存量 result 没这个字段）。
        # 实测起因：#10913 命中 VLLM-ASC-8646 但该 issue 以 NOT_PLANNED 关闭、无维护者结论，
        # 一旦结算就会给 VLLM-ASC-8646 打进"结论不符、请复审"——一条它无从反驳的指控。
        gt = str(res.get("ground_truth") or "").strip().lower()
        if gt == "none":
            settled[issue] = content_hash
            skip_none.append((issue, hit_case))
            continue
        if not tier2_hit or not hit_case:
            # 覆盖缺口信号（无 case 命中）——不结算 case；但记游标避免重扫
            settled[issue] = content_hash
            continue
        if rc_ok is None:
            continue  # 旧 result 缺字段，跳过不结算

        found = find_case(kb_root, hit_case)
        if not found:
            print(f"[warn] {f.name}: hit_case {hit_case} 未在 knowledge/ 找到——跳过")
            settled[issue] = content_hash
            continue
        case_f, doc, case = found

        # 独立性判定（两条）：① replay issue 正是该 case 的沉淀来源（自证）；
        # ② replay issue 在 case 正文里被引用（撰写依据）——都不能算独立的"外部验证"。
        src_ref = int(issue) in case_issue_sources(case)
        cited = (not src_ref) and case_cites_issue(case, int(issue))
        self_ref = src_ref or cited
        rec = case.setdefault("validation_record", {
            "consistent": 0, "inconsistent": 0, "self_consistent": 0, "last_verified": "",
        })
        if rc_ok is True:
            field = "self_consistent" if self_ref else "consistent"
            rec[field] = rec.get(field, 0) + 1
            if src_ref:
                tag = f"{field}（自证：replay issue = case 来源）"
            elif cited:
                tag = f"{field}（非独立：replay issue 在 case 正文里被引用，属该 case 的撰写依据）"
            else:
                tag = f"{field}（外部验证）"
        else:
            rec["inconsistent"] = rec.get("inconsistent", 0) + 1
            tag = "inconsistent（复审信号：命中但结论与 resolution 不符）"
            recheck.append({"case": hit_case, "issue": issue, "path": str(case_f)})
        rec["last_verified"] = iso_week_now()
        old = dict(rec)
        # diff 的"改前"值：加的是哪个计数就减哪个。**别写成 `old[field] = A if rc_ok else B`**——
        # 赋值目标 `old[field]` 在 RHS 之后求值，inconsistent 分支里 `field` 从未被赋值，
        # 于是只要真出现一次"命中但结论不符"就 UnboundLocalError（实测：本轮第一次遇到
        # inconsistent 结算时脚本直接崩）。inconsistent 这条正是**复审信号**的唯一入口，
        # 它崩掉等于这条通道从未可用。
        if rc_ok is True:
            old[field] = old.get(field, 0) - 1
        else:
            old["inconsistent"] = old.get("inconsistent", 0) - 1
        diffs.append((case_f, doc, f"{case_f.name}: {tag} → validation_record {old} → {rec}"))

        if apply:
            text = case_f.read_text(encoding="utf-8")
            # 有 validation_record 块 → 替换值行；无 → 在 confidence 块前插入（顶层字段）
            lines = text.split("\n")
            rec_idx = None
            for i, ln in enumerate(lines):
                if ln.strip().startswith("validation_record:"):
                    rec_idx = i
                    break
            vals = {k: str(v) for k, v in rec.items()}
            if rec_idx is not None:
                j = rec_idx + 1
                while j < len(lines):
                    s = lines[j].strip()
                    if not s or s.startswith("#"):
                        j += 1
                        continue
                    for k in vals:
                        if s.startswith(k + ":"):
                            indent = lines[j][: len(lines[j]) - len(lines[j].lstrip())]
                            lines[j] = indent + k + ": " + vals[k]
                    j += 1
                    if s and not s.startswith("#") and not lines[j].startswith("      "):
                        break
            else:
                # 顶层插入：找 "    confidence:" 所在的 case 起始行之前？简化：插到
                # "    category:" 之后不可靠——改为插到文件 cases: 块内第一个字段前。
                # 稳妥做法：找 confidence: 块结束（其后的非缩进行）前插入同等缩进字段。
                insert_at = None
                for i, ln in enumerate(lines):
                    if ln.strip() == "confidence:":
                        j = i + 1
                        while j < len(lines):
                            s = lines[j].strip()
                            if s and not s.startswith("#") and not lines[j].startswith("      "):
                                break
                            j += 1
                        insert_at = j  # confidence 块后
                        break
                if insert_at is None:
                    print(f"  [warn] {case_f.name}: 未定位插入点——跳过写回（仅记录 diff）")
                    continue
                block = ["", "    validation_record:  # S2/外部验证累积（settle_s2_feedback 结算；与 confidence 分开：confidence=现场 resolve S1，validation=内容被外部验证）"]
                for k in ("consistent", "inconsistent", "self_consistent", "last_verified"):
                    block.append(f"      {k}: {vals[k]}")
                lines[insert_at:insert_at] = block
            write_text_lf(case_f, "\n".join(lines) + "\n", encoding="utf-8")
            settled[issue] = content_hash

    if skip_none:
        print(f"[skip] {len(skip_none)} 条样本不可证伪（issue 无维护者结论 / 已合入 fix PR）——不结算，"
              "既不记 consistent 也不记 inconsistent（后者会制造假复审信号）：")
        for iss, hc in skip_none:
            print(f"  - issue #{iss} → {hc}")
        print()
    print(f"发现 {len(diffs)} 条 S2 结算变更（{len(recheck)} 条复审候选）。\n")
    for _, _, delta in diffs:
        print(f"  [diff] {delta}")
    if recheck:
        print("\n【复审候选】命中 case 但结论与 resolution 不符——case 内容可能错/过时/判别力不足：")
        for r in recheck:
            print(f"  - {r['case']}（replay issue #{r['issue']}，{r['path']}）")
    if apply:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        write_text_lf(state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("\n--apply：case YAML 已写回 + 游标已更新。请走 knowledge_modification PR 提交。")
    else:
        print("\n--dry-run（默认）：未写任何文件。确认后加 --apply，再走 knowledge_modification PR。")


def main():
    ap = argparse.ArgumentParser(description="S2 replay 结果结算到 case 内容验证记录")
    default_state, where = resolve_default_state(Path.cwd())
    ap.add_argument("--state", default=str(default_state),
                    help=f"结算游标文件（默认落登记的共享运行时件：{default_state}；{where}）")
    ap.add_argument("--migrate-from", default="ingest-state.json",
                    help="游标文件不存在时，从这里迁移既有游标（默认 ingest-state.json）")
    ap.add_argument("--apply", action="store_true", help="写回 case YAML（默认 dry-run 只输出 diff）")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()
    settle(args.root.resolve(), args.state, args.apply, migrate_from=Path(args.migrate_from))


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
