"""把一次评分适配成 stage 的 judge command。"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


class JudgeError(ValueError):
    pass


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise JudgeError(f"missing {name}")
    return value


def _prompt(output: str, expected: object) -> str:
    return (
        "你是诊断评测 judge。只判断候选输出是否解决了问题。\n"
        f"标准答案：{json.dumps(expected, ensure_ascii=False)}\n"
        f"候选输出：\n{output[-6000:]}\n\n"
        "只输出一行 JSON：{\"score\": 1} 或 {\"score\": 0}。"
    )


def _score(agent: str, prompt: str, timeout: float) -> int:
    if agent == "echo":
        return 1
    if agent == "dsh":
        dsh = os.environ.get("SLEUTH_DSH_BIN") or shutil.which("dsh") or \
            "/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh"
        command = [dsh, "headless", prompt, "--permission-mode", "workspace-write"]
    elif agent == "claude":
        command = ["claude", "-p", prompt, "--output-format", "text"]
    else:
        raise JudgeError(f"unknown judge agent: {agent}")
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, check=False)
    if proc.returncode != 0:
        raise JudgeError(f"judge exited {proc.returncode}: {proc.stderr[-400:]}")
    match = re.search(r'"?score"?\s*[:=]\s*([01])', proc.stdout)
    if not match:
        raise JudgeError(f"judge did not return score: {proc.stdout[-300:]}")
    return int(match.group(1))


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="dsh", choices=("dsh", "claude", "echo"))
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args(argv)
    try:
        output = Path(_env("SLEUTH_OUT")).read_text(encoding="utf-8")
        expected = json.loads(_env("SLEUTH_EXPECTED"))
        score = _score(args.agent, _prompt(output, expected), args.timeout)
        path = Path(_env("SLEUTH_JUDGE"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"score": score}, ensure_ascii=False) + "\n", encoding="utf-8")
    except (JudgeError, OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
