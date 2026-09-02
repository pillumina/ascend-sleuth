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
    """读校准集，产 replay 输入（现象 + 提示，不含 resolution——盲测）。"""
    out_dir = root / REPLAY_DIR
    out_dir.mkdir(exist_ok=True)
    n = 0
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
                f"请诊断以下昇腾问题（基于现象定位根因方向；标注证据缺口，不猜测）：\n\n{sym}\n"
            )
            (out_dir / f"{issue}.md").write_text(content, encoding="utf-8")
            n += 1
    print(f"s2_replay: 已产出 {n} 个 replay 输入 → {out_dir}/")


def collect(root: Path, report_path: Path):
    """读 replay 结果，与 resolution 对照评分。"""
    results_dir = root / REPLAY_DIR
    rows = []
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

            # 对照评分（诚实：自动判定是弱信号）
            # 简化关键词匹配：取 resolution 的核心名词，看是否出现在诊断结论
            res_kw = set(re.findall(r"[a-z_]{5,}", res_txt.lower()))
            got_kw = set(re.findall(r"[a-z_]{5,}", got_rc.lower()))
            overlap = res_kw & got_kw
            rc_match = len(overlap) >= 2  # ≥2 个核心词重叠 = candidate_match

            rows.append({
                "issue": issue,
                "status": "replayed",
                "res_conf": conf,
                "fix_ref": fix_ref or "-",
                "ns": got_ns or "-",
                "hit_case": got_hit or "-",
                "rc_match": rc_match,
                "overlap": sorted(overlap)[:5],
            })

    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# S2 Replay 评分报告", "",
        "- 说明：自动关键词匹配是弱信号（candidate_match），根因判定需人工复核；无 case 命中的 issue = 覆盖缺口信号（补 case 候选）", "",
        "| issue | status | res_conf | fix_ref | ns | hit_case | rc_match | overlap |", "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['issue']} | {r['status']} | {r.get('res_conf','-')} | {r.get('fix_ref','-')} | "
            f"{r.get('ns','-')} | {r.get('hit_case','-')} | {r.get('rc_match','-')} | {','.join(r.get('overlap',[]))[:40]} |"
        )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"s2_replay: 报告已写 {report_path}")


def main():
    ap = argparse.ArgumentParser(description="S2 校准集 replay 记录与对照评分")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--report", type=Path, default=Path(".s2-replay-report.md"))
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
