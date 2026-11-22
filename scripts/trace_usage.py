#!/usr/bin/env python3
"""把一次诊断的模型与 token 写进 trace 顶层（非 DSH agent 用）。

DSH 下 `trace_begin.py` 会按 `harness_session` 自动填 `model` 与
`tokens_start`；Claude Code / Codex 等没有 DSH 会话库时，由 agent 或
外层 harness 调本脚本写入。只改顶层三行，不碰 `trace[]` 与注释。

用法：
  python3 scripts/trace_usage.py --trace traces/<session>.yaml --tokens 12345
  python3 scripts/trace_usage.py --trace … --model claude-sonnet-4 --tokens-start 2000
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _stdio import write_text_lf  # noqa: E402

KEYS = ("model", "tokens", "tokens_start")


def _set_scalar(lines: list[str], key: str, value: str) -> list[str]:
    pattern = re.compile(rf"^{re.escape(key)}:")
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = f"{key}: {value}\n"
            return lines
    for index, line in enumerate(lines):
        if re.match(r"^trace:", line):
            lines.insert(index, f"{key}: {value}\n")
            return lines
    lines.append(f"{key}: {value}\n")
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="写 trace 顶层的 model / tokens")
    parser.add_argument("--trace", required=True, help="traces/<session>.yaml")
    parser.add_argument("--model", default=None, help="模型名；不传不改")
    parser.add_argument("--tokens", type=int, default=None, help="本次诊断 token 总数")
    parser.add_argument("--tokens-start", type=int, default=None, help="建单时累计 token")
    args = parser.parse_args(argv)
    if args.model is None and args.tokens is None and args.tokens_start is None:
        print("至少给 --model / --tokens / --tokens-start 之一", file=sys.stderr)
        return 2
    for name, value in (("tokens", args.tokens), ("tokens_start", args.tokens_start)):
        if value is not None and value < 0:
            print(f"--{name} 不能为负数", file=sys.stderr)
            return 2
    path = Path(args.trace)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"读不到 trace：{exc}", file=sys.stderr)
        return 2
    if not re.search(r"^trace:", text, re.M):
        print("不是诊断 trace（缺顶层 trace:）", file=sys.stderr)
        return 2
    lines = text.splitlines(keepends=True)
    if args.model is not None:
        lines = _set_scalar(lines, "model", json.dumps(args.model, ensure_ascii=False))
    if args.tokens is not None:
        lines = _set_scalar(lines, "tokens", str(args.tokens))
    if args.tokens_start is not None:
        lines = _set_scalar(lines, "tokens_start", str(args.tokens_start))
    write_text_lf(path, "".join(lines))
    print(str(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
