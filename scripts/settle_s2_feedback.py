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


def settle(root: Path, state_path: Path, apply: bool):
    state_path = Path(state_path)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"sources": {}}
    settled = state.setdefault("sources", {}).setdefault("_s2_feedback", {})
    replay_dir = root / REPLAY_DIR
    kb_root = root / "knowledge"

    diffs = []
    recheck = []  # inconsistent → 复审候选
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

        # self-referential 判定：replay issue 正是该 case 的沉淀来源
        self_ref = int(issue) in case_issue_sources(case)
        rec = case.setdefault("validation_record", {
            "consistent": 0, "inconsistent": 0, "self_consistent": 0, "last_verified": "",
        })
        if rc_ok is True:
            field = "self_consistent" if self_ref else "consistent"
            rec[field] = rec.get(field, 0) + 1
            tag = f"{field}（自证：replay issue = case 来源）" if self_ref else f"{field}（外部验证）"
        else:
            rec["inconsistent"] = rec.get("inconsistent", 0) + 1
            tag = "inconsistent（复审信号：命中但结论与 resolution 不符）"
            recheck.append({"case": hit_case, "issue": issue, "path": str(case_f)})
        rec["last_verified"] = iso_week_now()
        old = dict(rec)
        old[field] = old.get(field, 0) - 1 if rc_ok is True else old["inconsistent"] - 1
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
            case_f.write_text("\n".join(lines) + "\n", encoding="utf-8")
            settled[issue] = content_hash

    print(f"发现 {len(diffs)} 条 S2 结算变更（{len(recheck)} 条复审候选）。\n")
    for _, _, delta in diffs:
        print(f"  [diff] {delta}")
    if recheck:
        print("\n【复审候选】命中 case 但结论与 resolution 不符——case 内容可能错/过时/判别力不足：")
        for r in recheck:
            print(f"  - {r['case']}（replay issue #{r['issue']}，{r['path']}）")
    if apply:
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n--apply：case YAML 已写回 + 游标已更新。请走 knowledge_modification PR 提交。")
    else:
        print("\n--dry-run（默认）：未写任何文件。确认后加 --apply，再走 knowledge_modification PR。")


def main():
    ap = argparse.ArgumentParser(description="S2 replay 结果结算到 case 内容验证记录")
    ap.add_argument("--state", default="ingest-state.json")
    ap.add_argument("--apply", action="store_true", help="写回 case YAML（默认 dry-run 只输出 diff）")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()
    settle(args.root.resolve(), args.state, args.apply)


if __name__ == "__main__":
    main()
