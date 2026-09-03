#!/usr/bin/env python3
# s2_replay.py —— S2 校准集的 diagnose replay 记录与对照评分（Phase C2 闸门：对照评分规则定稿）
#
# S2 = Issue-replay 校准（evolution-pipeline §2.1 / evolution-run §3）：拿校准集 issue 的
# 现象喂 diagnose（单发，无追问），产出诊断结论（路由 namespace / 命中 case / 根因判断），
# 与 issue 实际 resolution（维护者 fix PR/结论）对照评分。
#
# 本脚本做**记录与评分框架**，不做诊断本身（诊断由 agent 按 diagnose skill 执行）：
#   1. 读 eval/s2/<repo>.yaml 校准集，产 replay 工作清单（.s2-replay/<issue>.md 输入文件）
#   2. agent 对每条做 diagnose（单发），把结论写 .s2-replay/<issue>.result.yaml
#   3. 本脚本 collect：读结果，与 expected.resolution 自动对照（PR 引用匹配 + 关键词），
#      产评分报告（hit/miss/partial + 路由对错 + 缺口信号）
#
# 对照评分规则（定稿，诚实标注）：
#   - 路由对错：诊断的 namespace/category vs 该 issue 实际归属（人工预标或从 resolution 推断）
#   - 根因匹配：诊断结论是否命中 issue resolution 的**关键语义**（fix PR 意图/根因要点）
#     - 自动判定是弱信号（关键词重叠），只标 candidate_match；人工复核定稿
#   - 输出：replay 记录 + 缺口信号（知识库无 case 命中的 issue = 补 case 候选）
#
# 用法：
#   python3 scripts/s2_replay.py --prepare    # 产 replay 输入清单
#   python3 scripts/s2_replay.py --collect --report <out.md>   # 评分报告

import argparse
import re
from pathlib import Path

import yaml

S2_DIR = "eval/s2"
REPLAY_DIR = ".s2-replay"


def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"__yaml_error__": str(e)}


def prepare(root: Path):
    """读校准集，产 replay 输入（现象 + 提示，不含 resolution——盲测）。

    EV-2026-004 口径（完整诊断能力评测）：replay 验证 agent 推理 + 知识库 + 工具的
    完整诊断能力，不是阉割版文本推理。工具边界（写进每条输入提示）：
    - 允许：查公开模型 config.json / clone 上游源码 grep 报错行 / 查官方文档 /
      gh api 拉公开 issue 的关联修复 PR 编号前信息——这些是 agent 真实诊断能力；
    - 禁止：查本 issue 自身的评论/讨论/结论/resolution/fix PR（防泄题——那是答案）。
    "单发"只约束不向用户追问额外信息，不约束 agent 用自己的工具查公开信息。
    """
    out_dir = root / REPLAY_DIR
    out_dir.mkdir(exist_ok=True)
    n = 0
    tool_note = (
        "【工具边界：本评测验证完整诊断能力】\n"
        "- 允许使用工具查公开信息：gh api 拉模型 config.json / 查官方文档 / clone 上游源码 grep 报错行\n"
        "- 禁止：查本 issue 自身的评论/讨论/结论/关联 fix PR（那是答案，查了即泄题）\n"
        "- 不向用户追问（单发盲测）；但 agent 自己的推理与工具查证不受限\n"
        "- 结论写 .s2-replay/<issue>.result.yaml，含分层归因：\n"
        "  namespace/category/hit_case/root_cause/evidence_gap/routing_ok/tier2_hit/\n"
        "  root_cause_ok/tool_used(工具名+拿到什么)/evidence_gap_class(A客观缺失|B推理未收尾|C工具未用足)\n"
    )
    for f in sorted((root / S2_DIR).glob("*.yaml")):
        doc = load_yaml(f)
        if not isinstance(doc, dict):
            continue
        for e in doc.get("calibration", []):
            issue = e.get("issue")
            sym = (e.get("input") or {}).get("symptoms", "")
            if not sym:
                continue
            content = (
                f"# S2 Replay: issue #{issue} ({f.stem})\n\n"
                f"标题：{e.get('title','')}\n\n"
                f"{tool_note}\n"
                f"请诊断以下昇腾问题（基于现象定位根因方向；标注证据缺口，不猜测）：\n\n{sym}\n"
            )
            (out_dir / f"{issue}.md").write_text(content, encoding="utf-8")
            n += 1
    print(f"s2_replay: 已产出 {n} 个 replay 输入 → {out_dir}/（含工具边界与分层归因提示）")


def collect(root: Path, report_path: Path):
    """读 replay 结果，与 resolution 对照评分。"""
    results_dir = root / REPLAY_DIR
    rows = []
    attribution_entries = []
    for f in sorted((root / S2_DIR).glob("*.yaml")):
        doc = load_yaml(f)
        if not isinstance(doc, dict):
            continue
        for e in doc.get("calibration", []):
            issue = e.get("issue")
            expected = e.get("expected", {})
            res_txt = expected.get("resolution", "") or ""
            fix_ref = expected.get("fix_commit", "") or ""
            conf = expected.get("confidence", "pending")

            result_file = results_dir / f"{issue}.result.yaml"
            if not result_file.exists():
                rows.append({"issue": issue, "status": "not_replayed", "note": "未跑 replay"})
                continue
            res = load_yaml(result_file)
            got_rc = res.get("root_cause", "") or ""
            got_ns = res.get("namespace", "") or ""
            got_hit = res.get("hit_case", "")
            got_cat = res.get("category", "") or ""
            # EV-2026-004 分层归因字段（旧 result 无则缺省）
            gap_class = res.get("evidence_gap_class", "") or ""
            tool_used = res.get("tool_used", "") or ""
            root_cause_ok = res.get("root_cause_ok")  # True/False/None
            tier2_hit_flag = res.get("tier2_hit")      # True/False/None
            routing_ok = res.get("routing_ok")         # True/False/None

            # 对照评分（诚实：自动判定是弱信号）
            # 简化关键词匹配：取 resolution 的核心名词，看是否出现在诊断结论
            res_kw = set(re.findall(r"[a-z_]{5,}", res_txt.lower()))
            got_kw = set(re.findall(r"[a-z_]{5,}", got_rc.lower()))
            overlap = res_kw & got_kw
            rc_match = len(overlap) >= 2  # ≥2 个核心词重叠 = candidate_match

            # 路由对照（S2 路由 miss 归因，S1 无关——pipeline §2.1：错例自动累积不等人回报）
            # 人工预标 expected.namespace/category 是路由正确归属基准；对照 diagnose 输出。
            exp_ns = expected.get("namespace", "") or ""
            exp_cat = expected.get("category", "") or ""
            route_miss = False
            route_note = ""
            if exp_ns and got_ns and exp_ns not in got_ns and got_ns not in exp_ns:
                route_miss = True
                route_note = f"ns 错：应 {exp_ns}，得 {got_ns}"
            if exp_cat and got_cat and exp_cat != got_cat:
                route_miss = True
                route_note = (route_note + "；" if route_note else "") + f"category 错：应 {exp_cat}，得 {got_cat}"
            if route_miss and not got_hit:
                # 路由错 + 未命中 → 归因 triage 组件（got 分支把 issue 引向错误方向）
                got_branch = f"triage:inference_{got_cat}" if got_cat else "triage:未归因"
                attribution_entries.append({
                    "issue": issue,
                    "component": got_branch,
                    "verdict": "execution_error",   # 路由执行错（非 case 内容错——S2 无 S1 职权判 case 错）
                    "expected": {"namespace": exp_ns, "category": exp_cat},
                    "got": {"namespace": got_ns, "category": got_cat},
                    "note": route_note,
                    "source": "s2-replay",
                })

            rows.append({
                "issue": issue,
                "status": "replayed",
                "res_conf": conf,
                "fix_ref": fix_ref or "-",
                "ns": got_ns or "-",
                "hit_case": got_hit or "-",
                "rc_match": rc_match,
                "overlap": sorted(overlap)[:5],
                "route": ("MISS" if route_miss else "ok") if (exp_ns or exp_cat) else "-",
                "gap_class": gap_class or "-",
                "tool_used": tool_used or "-",
            })

    # 写路由归因（供 component_tally.py --emit 合并进组件台账；无归因则写空文件不报错）
    attr_path = root / REPLAY_DIR / "attributions.yaml"
    attr_path.parent.mkdir(parents=True, exist_ok=True)
    attr_path.write_text(
        yaml.safe_dump({
            "_comment": "GENERATED by scripts/s2_replay.py --collect；S2 路由 miss 归因（S1 无关）。"
                        "component=got 分支（把 issue 引向错误方向的 triage 分支），verdict=execution_error。"
                        "由 component_tally.py --emit 合并进 metrics/component-tally.yaml。",
            "attributions": attribution_entries,
        }, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if attribution_entries:
        print(f"s2_replay: {len(attribution_entries)} 条路由归因 → {attr_path}（component_tally --emit 合并）")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# S2 Replay 评分报告", "",
        "- 说明：自动关键词匹配是弱信号（candidate_match），根因判定需人工复核；无 case 命中的 issue = 覆盖缺口信号（补 case 候选）",
        "- EV-2026-004 口径：replay 验证完整诊断能力（推理+知识库+工具）；evidence_gap_class: A客观缺失 / B推理未收尾 / C工具未用足", "",
        "| issue | status | res_conf | fix_ref | ns | hit_case | rc_match | route | gap_class | tool_used | overlap |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['issue']} | {r['status']} | {r.get('res_conf','-')} | {r.get('fix_ref','-')} | "
            f"{r.get('ns','-')} | {r.get('hit_case','-')} | {r.get('rc_match','-')} | {r.get('route','-')} | "
            f"{r.get('gap_class','-')} | {str(r.get('tool_used','-'))[:28]} | {','.join(r.get('overlap',[]))[:30]} |"
        )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"s2_replay: 报告已写 {report_path}")


def todo(root: Path):
    """列出未 replay 的校准集条目（供 agent 驱动批量测试），按 confidence 优先。"""
    conf_order = {"high": 0, "medium": 1, "pending": 2}
    rows = []
    for f in sorted((root / S2_DIR).glob("*.yaml")):
        doc = load_yaml(f)
        if not isinstance(doc, dict):
            continue
        for e in doc.get("calibration", []):
            issue = e.get("issue")
            res_file = root / REPLAY_DIR / f"{issue}.result.yaml"
            if res_file.exists():
                continue
            rows.append((
                conf_order.get(e.get("expected", {}).get("confidence", "pending"), 3),
                issue, f.stem, e.get("title", ""), e.get("expected", {}).get("confidence", "?"),
            ))
    rows.sort(key=lambda r: r[0])
    if not rows:
        print("s2_replay: 校准集全部已 replay（无待测）")
        return
    print(f"s2_replay: {len(rows)} 条待 replay（按 confidence 优先）：\n")
    print("对每条：读 .s2-replay/<issue>.md（现象 + 工具边界）→ 按 diagnose 流程诊断（可用工具查公开信息）→ 结论写 .s2-replay/<issue>.result.yaml")
    print("（result 结构: namespace/category/hit_case/root_cause/evidence_gap/routing_ok/tier2_hit/")
    print("  root_cause_ok/tool_used/evidence_gap_class/replayed_at——EV-2026-004 分层归因）\n")
    for _, issue, repo, title, conf in rows:
        print(f"  #{issue} [{conf}] ({repo}) {title[:60]}")


def main():
    ap = argparse.ArgumentParser(description="S2 校准集 replay 记录与对照评分")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--todo", action="store_true", help="列未 replay 条目（驱动批量测试）")
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--report", type=Path, default=Path(".s2-replay-report.md"))
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()
    root = args.root.resolve()
    if args.prepare:
        prepare(root)
    elif args.todo:
        todo(root)
    elif args.collect:
        collect(root, args.report)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
