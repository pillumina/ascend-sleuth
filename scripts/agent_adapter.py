"""把一个外部 agent 适配成 stage runner 的单次诊断 command。

stage runner 只认 SLEUTH_* 环境变量与写出的 trace/out；本模块负责构造
诊断 prompt、调用 agent、把报告和最小 trace 落盘。

注意：``agent="dsh"`` 指 dsh CLI 的 headless 模式，不是 DSH Desktop。
DSH Desktop 本身是 agent，提案与实验应由会话内 subagent 编排，不需要
本 adapter 去启动一个 Desktop 进程。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml


class AdapterError(ValueError):
    pass


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise AdapterError(f"missing {name}")
    return value


def _sample(output: Path, sample_id: str) -> Dict[str, Any]:
    tasks = json.loads((output / "tasks.json").read_text(encoding="utf-8"))
    for sample in tasks.get("samples") or []:
        if str(sample.get("id")) == sample_id:
            path = Path(sample["path"])
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raise AdapterError(f"sample not found in tasks: {sample_id}")


def _prompt(sample: Dict[str, Any], root: Path) -> str:
    skill = root / "skills" / "diagnose" / "SKILL.md"
    return (
        "你是 ascend-sleuth 诊断 agent。按仓库里的诊断流程工作。"
        f"先读 {skill}，再诊断下面的问题；不要读取 expected 或测试答案。\n\n"
        f"样本 id: {sample.get('id')}\n"
        f"来源: {sample.get('source')}\n"
        f"输入:\n{json.dumps(sample.get('input') or {}, ensure_ascii=False, indent=2)}\n\n"
        "把最终定位报告写到 SLEUTH_OUT，把完整诊断 trace 写到 SLEUTH_TRACE"
        "（按 skills/diagnose/references/diagnosis-trace.md 的事件结构）。\n"
        "给出最终定位报告（现象、证据、根因、修复建议）。"
    )


def _dsh_bin() -> str:
    return (os.environ.get("SLEUTH_DSH_BIN") or shutil.which("dsh") or
            "/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh")


def _dsh_preflight() -> None:
    if os.environ.get("DEEPSEEK_API_KEY"):
        return
    if os.environ.get("SLEUTH_DSH_ALLOW_STORED") == "1":
        return
    raise AdapterError(
        "agent=dsh needs DEEPSEEK_API_KEY for headless auth; "
        "export it or set SLEUTH_DSH_ALLOW_STORED=1 for a stored credential"
    )


def _run_agent(agent: str, prompt: str, root: Path, timeout: float) -> str:
    if agent == "echo":
        return "echo adapter: " + prompt.splitlines()[0]
    if agent == "claude":
        command = ["claude", "-p", prompt, "--output-format", "text"]
    elif agent == "dsh":
        _dsh_preflight()
        command = [_dsh_bin(), "headless", prompt, "--permission-mode", "workspace-write"]
    elif agent == "command":
        raw = os.environ.get("SLEUTH_AGENT_CMD")
        if not raw:
            raise AdapterError("SLEUTH_AGENT_CMD is required for agent=command")
        command = json.loads(raw)
        if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
            raise AdapterError("SLEUTH_AGENT_CMD must be a JSON list of strings")
        command = command + [prompt]
    else:
        raise AdapterError(f"unknown agent: {agent}")
    proc = subprocess.run(command, cwd=str(root), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, check=False)
    if proc.returncode != 0:
        raise AdapterError(f"agent exited {proc.returncode}: {proc.stderr[-400:]}")
    return proc.stdout


def run(agent: str, timeout: float = 600.0) -> Dict[str, Any]:
    output = Path(_env("SLEUTH_OUTPUT"))
    trace = Path(_env("SLEUTH_TRACE"))
    out = Path(_env("SLEUTH_OUT"))
    root = Path(_env("SLEUTH_ROOT"))
    sample = _sample(output, _env("SLEUTH_SAMPLE_ID"))
    prompt = _prompt(sample, root)
    report = _run_agent(agent, prompt, root, timeout)
    out.parent.mkdir(parents=True, exist_ok=True)
    trace.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    if not trace.exists() or not trace.read_text(encoding="utf-8").strip():
        doc = {
            "session_id": f"adapter-{os.environ.get('SLEUTH_STAGE')}-{os.environ.get('SLEUTH_SHORT_ID')}-"
                          f"{os.environ.get('SLEUTH_ARM')}",
            "model": agent,
            "trace": [
                {"role": "user", "content": prompt},
                {
                    "role": "agent", "step": 1, "action": "report",
                    "output": report,
                    "reason": "echo adapter: synthetic trace for smoke" if agent == "echo"
                              else "adapter fallback: agent did not write a trace",
                },
            ],
        }
        doc["adapter_fallback"] = True
        trace.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"sample": sample.get("id"), "agent": agent, "report_chars": len(report)}


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="dsh", choices=("echo", "claude", "dsh", "command"),
                        help="dsh 是 headless CLI，不是 DSH Desktop")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run:
        print(json.dumps({
            "agent": args.agent,
            "env": sorted(k for k in os.environ if k.startswith("SLEUTH_")),
            "dsh_bin": _dsh_bin() if args.agent == "dsh" else None,
            "credential_env": bool(os.environ.get("DEEPSEEK_API_KEY")) if args.agent == "dsh" else None,
        }, ensure_ascii=False))
        return 0
    try:
        result = run(args.agent, timeout=args.timeout)
    except (AdapterError, OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
