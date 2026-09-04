#!/usr/bin/env python3
# gate_diff.py —— gated 门禁基线对照（B3 EV-2026-027）
#
# 让"检索面 skill 改动 → golden 子集前后对照"的成本降下来：基线缓存复用 +
# 只跑改后侧 + 逐 fixture 机械对照（不再每次重跑改前）。
#
# 目录约定（.s2-replay/gates/，本地）：
#   .s2-replay/gates/<改动面>-baseline/   上次干净运行的 fixture 结果 JSON（每 fixture 一个）
#   .s2-replay/gates/<改动面>-after/       本次改后跑的结果 JSON
#   .s2-replay/gates/<改动面>.expected.yaml  可选：{fixture: expected_case} 断言
#
# 结果 JSON 字段（与 replay 执行者约定一致）：{fixture, route_ns, route_category,
# top3: [], hit_case, expected_ns, expected_category}
#
# 用法：
#   # 首次：把改前结果拷为 baseline
#   mkdir -p .s2-replay/gates/retrieval-baseline && cp /tmp/golden-*/xxx.json ...
#   # 改后对照：
#   python3 scripts/gate_diff.py --base .s2-replay/gates/retrieval-baseline \
#       --after .s2-replay/gates/retrieval-after [--expected .s2-replay/gates/retrieval.expected.yaml]
#   退出码：0=无回归（after 每个 fixture 的 top3 与 base 一致，或 expected case 仍在 top-3）；
#           1=有回归/缺结果
#
# 口径（docs/eval.md 断言分层）：LLM 非确定性 → 断言 top-3 命中而非 must-first；
# base 为 documented miss 的 fixture 在 after 也须 miss（或同样 documented）。

import argparse
import json
import sys
from pathlib import Path

import yaml


def load_results(d: Path):
    out = {}
    if not d.exists():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            out[f.stem] = None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="baseline 结果目录")
    ap.add_argument("--after", required=True, help="改后结果目录")
    ap.add_argument("--expected", default="", help="可选 expected.yaml：{fixture: case}")
    args = ap.parse_args()
    base = load_results(Path(args.base))
    after = load_results(Path(args.after))
    expected = {}
    if args.expected:
        expected = (yaml.safe_load(Path(args.expected).read_text()) or {})

    problems = []
    n = 0
    for stem, b in sorted(base.items()):
        a = after.get(stem)
        if a is None:
            problems.append(f"{stem}: after 缺结果")
            continue
        n += 1
        bt, at = b.get("top3") or [], a.get("top3") or []
        if bt == at:
            continue
        # top3 漂移：断言 expected case 仍在 top-3（防 must-first 过度严格）
        ec = expected.get(stem)
        if ec and ec in at:
            print(f"{stem}: top3 漂移但 expected {ec} 仍在 top-3（容忍）")
            continue
        problems.append(f"{stem}: top3 变化 base={bt} after={at}"
                         + (f"（expected {ec} 不在 after top-3）" if ec else ""))
    # after 多出的 fixture（新增）不视为回归
    print(f"gate_diff: {n} 个 fixture 对照完成")
    if problems:
        print("回归/异常：")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("无回归（top3 一致或 expected 保持在 top-3）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
