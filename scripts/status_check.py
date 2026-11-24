#!/usr/bin/env python3
"""status_check.py —— 把 `docs/mechanism/status.md` 的「确认方式」变成可执行检查。

status 表的每一行回答「这条机制现在真的能用吗」。多数确认方式是命令；人工只跑其中几条，
于是表里最弱的一类（`ls 文件存在`）曾经把「文件在」误当成「机制在工作」。本脚本读表、
抽出可执行命令（`python3 …` / `node …`），按行执行并汇总：

    python3 scripts/status_check.py            # 跑全部可执行确认方式
    python3 scripts/status_check.py --list     # 只列表：哪行有哪些命令
    python3 scripts/status_check.py --only 面板 # 按机制名过滤
    python3 scripts/status_check.py --json     # 机器可读

退出码：0 = 全部通过或没有可执行项；1 = 有确认失败；2 = 参数/读表失败。
`ls`/`grep` 这类只证明存在性的命令列在 `--list` 的「非执行项」里，不当作通过。
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cli import base_parser, fail, main_entry  # noqa: E402

STATUS_REL = Path("docs/mechanism/status.md")
EXECUTABLE_PREFIXES = ("python3 ", "node ", "python ")
DEFAULT_TIMEOUT = 180

CHECK_RE = re.compile(r"`([^`]+)`")


@dataclass(frozen=True)
class Check:
    mechanism: str
    status: str
    doc: str
    commands: tuple
    skipped: tuple


def _cells(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_checks(text: str) -> List[Check]:
    """从 status 表里抽确认方式；非表格行与表头/分隔行忽略。"""
    checks: List[Check] = []
    for line in text.splitlines():
        if not line.startswith("|") or line.count("|") < 4:
            continue
        cells = _cells(line)
        if len(cells) < 4:
            continue
        if set(cells[0]) <= {"-", " "} or cells[0] in ("机制",):
            continue
        mechanism, doc, status, how = cells[0], cells[1], cells[2], cells[3]
        commands, skipped = [], []
        landed = status.startswith("已落地")
        for token in CHECK_RE.findall(how):
            if landed and token.startswith(EXECUTABLE_PREFIXES) and "<" not in token:
                commands.append(token)
            else:
                skipped.append(token)
        if commands or skipped:
            checks.append(Check(mechanism, status, doc, tuple(commands), tuple(skipped)))
    return checks


def _argv(command: str) -> List[str]:
    argv = shlex.split(command)
    if argv and argv[0] == "python3":
        argv[0] = sys.executable
    return argv


Runner = Callable[[Sequence[str], Path, int], int]


def _default_runner(argv: Sequence[str], cwd: Path, timeout: int) -> int:
    try:
        return subprocess.run(argv, cwd=str(cwd), capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        return 124
    except OSError:
        return 127


def run_checks(checks: List[Check], root: Path, *, timeout: int = DEFAULT_TIMEOUT,
               runner: Runner = _default_runner,
               only: Optional[str] = None) -> List[Dict[str, object]]:
    results: List[Dict[str, object]] = []
    for check in checks:
        if only and only not in check.mechanism:
            continue
        for command in check.commands:
            code = runner(_argv(command), root, timeout)
            results.append({"mechanism": check.mechanism, "status": check.status,
                            "command": command, "exit": code,
                            "ok": code == 0})
    return results


def _summary(results: List[Dict[str, object]]) -> Dict[str, object]:
    failed = [row for row in results if not row["ok"]]
    return {"total": len(results), "passed": len(results) - len(failed),
            "failed": len(failed), "failures": failed}


def _check_skill(root: Path, name: str, as_json: bool) -> int:
    """核对 skill 的 frontmatter：文件在、name 与目录同名、description 非空。"""
    path = root / "skills" / name / "SKILL.md"
    problems = []
    text = ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        problems.append(f"读不到 {path}: {exc}")
    if text and not text.startswith("---"):
        problems.append("SKILL.md 没有 frontmatter")
    front = text.split("---", 2)[1] if text.startswith("---") and text.count("---") >= 2 else ""
    if not re.search(r"(?m)^name:\s*" + re.escape(name) + r"\s*$", front):
        problems.append(f"frontmatter 的 name 不是 {name!r}")
    if not re.search(r"(?m)^description:\s*\S", front):
        problems.append("frontmatter 缺 description")
    payload = {"skill": name, "path": str(path), "ok": not problems,
               "problems": problems}
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{'✓' if payload['ok'] else '✗'} skill {name}: {path}")
        for problem in problems:
            print(f"  {problem}")
    return 0 if payload["ok"] else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = base_parser("执行 status.md 里可执行的确认方式", json_output=True)
    ap.add_argument("--only", default=None, help="只跑机制名包含该子串的行")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="单条命令超时秒数")
    ap.add_argument("--list", action="store_true", help="只列出确认方式，不执行")
    ap.add_argument("--skill", default=None,
                    help="只核一个 skill 的 frontmatter（name/description 齐全）")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if args.skill:
        return _check_skill(root, args.skill, args.json)
    path = root / STATUS_REL
    try:
        checks = parse_checks(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return fail(f"读不到 {path}: {exc}", 2)

    if args.list:
        payload = [{"mechanism": c.mechanism, "status": c.status,
                    "commands": list(c.commands), "skipped": list(c.skipped)}
                   for c in checks if not args.only or args.only in c.mechanism]
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for row in payload:
                print(f"{row['mechanism']} [{row['status']}]")
                for command in row["commands"]:
                    print(f"  run: {command}")
                for command in row["skipped"]:
                    print(f"  skip: {command}")
        return 0

    results = run_checks(checks, root, timeout=args.timeout, only=args.only)
    if args.json:
        print(json.dumps(_summary(results), ensure_ascii=False, indent=2))
    else:
        for row in results:
            mark = "✓" if row["ok"] else "✗"
            print(f"{mark} {row['mechanism']}: {row['command']} (exit {row['exit']})")
        summary = _summary(results)
        print(f"\n确认 {summary['total']} 条：通过 {summary['passed']}，失败 {summary['failed']}")
    return 0 if all(row["ok"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main_entry(main))
