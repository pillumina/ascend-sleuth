#!/usr/bin/env python3
# replay_golden.py —— golden 套件 replay 编排（roadmap M2 雏形，docs/eval.md）
#
# M2 目标：skill 改动前后跑 golden 回放，比对"路由/命中是否倒退"——产出改前/改后报告。
# replay 的**执行**由 diagnose 的 replay 模式完成（agent 读 fixture 输入跑诊断），
# 本脚本做编排与比对：
#   1. 扫描 eval/golden/*.fixture.yaml，产出 replay 输入清单（每 fixture 一个输入文件，
#      供 diagnose replay 模式消费；也可直接喂给 agent 手跑）
#   2. 收集 replay 结果（诊断输出），与 fixture 的 expected 比对（top-3 命中断言，
#      容忍 LLM 非确定性——docs/eval.md 断言分层）
#   3. 产出改前/改后对照报告
#
# 用法：
#   python3 scripts/replay_golden.py --prepare      # 产出 replay 输入（.replay-input/）
#   python3 scripts/replay_golden.py --collect <dir> --report <out.md>   # 比对结果产报告
#
# 状态：M2 半自动化雏形——prepare 已脚本化；collect 的"诊断输出"来自 diagnose
# replay（agent 执行），脚本负责结构化比对与报告。

import argparse
import json
import re
from pathlib import Path

import yaml

GOLDEN_DIR = "eval/golden"
REPLAY_INPUT_DIR = ".replay-input"


def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"__yaml_error__": str(e)}


def prepare(root: Path):
    """扫描 fixture，产出 replay 输入（每个 fixture 一个 md，含 symptoms + 期望锚点）。"""
    golden = root / GOLDEN_DIR
    out_dir = root / REPLAY_INPUT_DIR
    out_dir.mkdir(exist_ok=True)
    n = 0
    for f in sorted(golden.glob("*.fixture.yaml")):
        doc = load_yaml(f)
        if not isinstance(doc, dict):
            print(f"  {f.name}: 解析失败")
            continue
        # 文件名唯一（fixture 名），case_id 是期望命中的 case（可被多 fixture 指向）
        stem = f.stem.replace(".fixture", "")
        case_id = doc.get("case_id", stem)
        inp = doc.get("input", {})
        symptoms = inp.get("symptoms", "")
        # 组装 replay 输入：现象 + 提示（期望不放进去——避免污染诊断，锚点单独存）
        content = f"# Replay: {stem} (期望 case: {case_id})\n\n请诊断以下昇腾问题：\n\n{symptoms}\n"
        out_file = out_dir / f"{stem}.md"
        out_file.write_text(content, encoding="utf-8")
        n += 1
    print(f"replay_golden: 已产出 {n} 个 replay 输入 → {out_dir}/")


def collect(root: Path, report_path: Path):
    """收集 replay 结果（.replay-results/<case_id>.yaml，来自 diagnose replay 输出），
    与 fixture expected 比对，产改前/改后报告。"""
    golden = root / GOLDEN_DIR
    results_dir = root / ".replay-results"
    rows = []
    n_pass = n_total = 0
    for f in sorted(golden.glob("*.fixture.yaml")):
        doc = load_yaml(f)
        if not isinstance(doc, dict):
            continue
        stem = f.stem.replace(".fixture", "")
        case_id = doc.get("case_id", stem)
        expected = doc.get("expected", {})
        # 期望：namespace / case_id / 关键词
        exp_ns = expected.get("namespace")
        exp_case = expected.get("case_id")
        exp_rc = expected.get("root_cause_contains", "")

        res_file = results_dir / f"{stem}.yaml"
        if not res_file.exists():
            rows.append({"case": stem, "status": "no_result", "note": f"未跑 replay（期望 case: {case_id}）"})
            continue
        res = load_yaml(res_file)
        got_ns = res.get("namespace")
        got_cases = res.get("candidates") or []
        got_rc = res.get("root_cause", "")

        # 断言：top-3 命中（容忍非确定性）+ 关键词
        hit_case = exp_case in got_cases[:3] if exp_case else True
        ns_ok = (not exp_ns) or (exp_ns in (got_ns or ""))
        rc_ok = (not exp_rc) or (exp_rc.lower() in (got_rc or "").lower())
        passed = hit_case and ns_ok and rc_ok
        n_total += 1
        if passed:
            n_pass += 1
        rows.append({
            "case": case_id,
            "status": "pass" if passed else "fail",
            "hit": hit_case, "ns_ok": ns_ok, "rc_ok": rc_ok,
            "detail": f"got_ns={got_ns} got_cases={got_cases[:3]}",
        })

    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Golden Replay 报告",
        "",
        f"- 通过: {n_pass}/{n_total}",
        f"- 时间: （人审补）",
        "",
        "| case | status | hit | ns | rc | detail |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['case']} | {r['status']} | {r.get('hit','-')} | {r.get('ns_ok','-')} | "
            f"{r.get('rc_ok','-')} | {r.get('detail', r.get('note',''))} |"
        )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"replay_golden: 报告已写 {report_path}（{n_pass}/{n_total} 通过）")


def main():
    ap = argparse.ArgumentParser(description="golden 套件 replay 编排（M2 雏形）")
    ap.add_argument("--prepare", action="store_true", help="产出 replay 输入")
    ap.add_argument("--collect", action="store_true", help="收集结果并产出报告")
    ap.add_argument("--report", type=Path, default=Path(".replay-report.md"))
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()
    root = args.root.resolve()
    if args.prepare:
        prepare(root)
    elif args.collect:
        collect(root, args.report)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
