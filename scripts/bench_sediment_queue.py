#!/usr/bin/env python3
# bench_sediment_queue.py —— 沉淀队列一次取数的开销（不进 CI，按需跑）
#
# 为什么单独一个脚本：
#   缓存过期后打开沉淀视图会起一个子进程跑 `dsh-plugins/dsh-sleuth-copilot/lib/sediment_state.py`。
#   这个子进程对每份评估记录都要查三类 git（目标 ref 解析、祖先判定、知识库 diff），并把批次
#   指令复制进每一行。条目数上来以后打开就变成秒级，本脚本量三个随条目数增长的量：
#   取数耗时、git 子进程数、payload 字节数。
#
# 量的是当前检出（或用 --plugin 指定的另一份插件）的代码。改前 / 改后对照：两次运行分别用
# 两份检出的 `--plugin`，夹具相同（同一套构造逻辑）。
#
# 用法：
#   python3 scripts/bench_sediment_queue.py                     # 300 份草稿 + 600 条 trace
#   python3 scripts/bench_sediment_queue.py --drafts 600 --decided
#   python3 scripts/bench_sediment_queue.py --plugin /path/to/ascend-sleuth/dsh-plugins/dsh-sleuth-copilot
#   python3 scripts/bench_sediment_queue.py --json              # 机器读一行 JSON
#
# 口径：耗时是 collect 调用本身（取 repeat 次的最小值），不含 Python 启动与脚本 import；
# git 子进程数按 `groom_common.run_git` 计数；payload 是 collect 返回值的 UTF-8 JSON 字节数。
#
# 退出码：0 正常；2 参数错误（argparse）；1 环境缺 git / 夹具构造失败。

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

from _stdio import pin_utf8_stdio

REPO = Path(__file__).resolve().parents[1]
DEFAULT_PLUGIN = REPO / "dsh-plugins" / "dsh-sleuth-copilot"

# 与 tests/groom_fixtures.py 的 CASE_TMPL 同形（脚本不 import tests/：夹具要能单独跑）。
CASE_TMPL = """cases:
  - id: {cid}
    title: "{title}"
    category: interrupt
    tags: [bench]
    symptoms:
      - "测试症状"
    root_cause: "测试根因"
    fix: "测试修复"
    severity: service-affecting
    fix_type: config-change
    quickly_check:
      primary:
        command_template: "echo {cid}"
        expected: "regex:{cid}"
"""


def parse_args(argv):
    parser = argparse.ArgumentParser(description="沉淀队列取数开销")
    parser.add_argument("--drafts", type=int, default=300, help="草稿数（默认 300）")
    parser.add_argument("--traces", type=int, default=0, help="trace 数（默认 2 × 草稿数）")
    parser.add_argument("--decided", action="store_true",
                        help="所有草稿写有效人决定（队列变成待提 PR，批次指令最长）")
    parser.add_argument("--repeat", type=int, default=3, help="计时次数，取最小值（默认 3）")
    parser.add_argument("--plugin", default=str(DEFAULT_PLUGIN),
                        help="插件目录（默认本检出的 dsh-plugins/dsh-sleuth-copilot）")
    parser.add_argument("--json", action="store_true", help="输出一行 JSON")
    args = parser.parse_args(argv)
    if args.drafts <= 0 or args.repeat <= 0:
        parser.error("--drafts 与 --repeat 需要正整数")
    if args.traces <= 0:
        args.traces = args.drafts * 2
    plugin = Path(args.plugin).expanduser().resolve()
    if not (plugin / "lib" / "sediment_state.py").is_file():
        parser.error(f"插件目录里没有 lib/sediment_state.py：{plugin}")
    repo = plugin.parents[1]
    if not (repo / "scripts").is_dir():
        parser.error(f"插件所在的检出里没有 scripts/：{repo}")
    if not (repo / "trace-status.yaml").is_file():
        parser.error(f"检出里没有 trace-status.yaml：{repo}")
    return args, plugin, repo


def git(repo: Path, *args, check: bool = True):
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败：{proc.stderr.strip()}")
    return proc


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def write_case(repo: Path, rel: str, cid: str) -> Path:
    return write_text(repo / rel, CASE_TMPL.format(cid=cid, title=f"夹具 {cid}"))


def build_fixture(base: Path, repo_root: Path, drafts: int, traces: int, decided: bool) -> Path:
    """临时 git 仓库 + N 份草稿 / 评估 / trace；评估之后知识库再前进一次（走 diff 分支）。"""
    repo = base / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "bench@example.com")
    git(repo, "config", "user.name", "Sediment Bench")
    shutil.copytree(repo_root / "scripts", repo / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(repo_root / "trace-status.yaml", repo / "trace-status.yaml")
    # 真实仓库的 inbox 草稿与评估 sidecar 是 gitignore 的运行时件；fixture 也照抄这份规则，
    # 否则下面的 `git add -A` 会把它们一起提交，夹具状态与真实仓库不一致。
    if (repo_root / ".gitignore").is_file():
        shutil.copy2(repo_root / ".gitignore", repo / ".gitignore")
    write_case(repo, "knowledge/inference/vllm-ascend/interrupt/CASE-BASE.yaml", "CASE-BASE")
    (repo / "README.md").write_text("bench\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    assessed_commit = git(repo, "rev-parse", "HEAD").stdout.strip()

    sys.path.insert(0, str(repo / "scripts"))
    import groom_common as gm
    inbox = repo / "postmortems" / "inbox"
    sidecars = inbox / ".groom" / "assessments"
    sidecars.mkdir(parents=True, exist_ok=True)
    for index in range(drafts):
        key = f"2026-10-{index % 28 + 1:02d}-draft-{index:04d}"
        case_path = write_text(inbox / f"{key}.case.yaml",
                               CASE_TMPL.format(cid=f"DRAFT-{index}", title=f"夹具草稿 {index}"))
        if index % 5 == 0 and not decided:
            continue                      # 未评估样本：走「未评估」分支
        case = gm.draft_cases(gm.Draft(key=key, case_path=case_path, layout="flat"))[0]
        # 默认夹具一半指向评估时的 ref（新鲜），一半指向会前进的 origin/main（过期）；
        # --decided 全部指向评估时的 ref，队列整体是「待提 PR」，批次指令最长。
        fresh = decided or index % 2 == 0
        sidecar = {
            "assessment": {
                "proposed_novelty": "new_pattern", "candidate_case": None,
                "confidence": "high", "rationale": "夹具", "review_required": False,
            },
            "provenance": {
                "compared_against_commit": assessed_commit,
                "compared_against_short": assessed_commit[:12],
                "snapshot_authoritative": True,
                "target_ref": ("refs/remotes/origin/assessed" if fresh
                               else "refs/remotes/origin/main"),
            },
            "assessment_id": f"assess-{index}",
            "human_decision": {},
            "human_decision_valid": False,
            "promotion_gate": {"allowed": True, "blocked_reason": None},
            "review_state": "pending",
        }
        if decided:
            sidecar["human_decision"] = {"decision": "new_pattern", "by": "夹具",
                                         "decided_at": "2026-11-01T09:00:00+08:00"}
            sidecar["human_decision_valid"] = True
        sidecar["draft_sha256"] = gm.case_fingerprint(case)
        with open(sidecars / f"{gm.sanitize_key(key)}.yaml", "w", encoding="utf-8",
                  newline="\n") as fh:
            yaml.safe_dump(sidecar, fh, allow_unicode=True, sort_keys=False)
    # 评估之后知识库前进一次：祖先成立、知识库 diff 非空，覆盖两个 git 分支。
    write_case(repo, "knowledge/inference/vllm-ascend/interrupt/CASE-MOVED.yaml", "CASE-MOVED")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "knowledge moves")
    new_commit = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "update-ref", "refs/remotes/origin/main", new_commit)
    git(repo, "update-ref", "refs/remotes/origin/assessed", assessed_commit)
    for index in range(traces):
        write_text(repo / "traces" / f"2026-10-sess-{index:04d}.yaml", "\n".join([
            f'session_id: "2026-10-sess-{index:04d}"',
            f'summary: "夹具会话 {index}"',
            "status: resolved",
            'updated_at: "2026-11-01T10:00:00+08:00"',
            "sedimented:",
            "  state: submitted",
            f'  case_id: "DRAFT-{index % max(drafts, 1)}"',
            "trace:",
            '  - {role: user, step: 1, content: "夹具"}',
            "",
        ]))
    return repo


def measure(plugin: Path, repo: Path, repeat: int) -> dict:
    sys.path.insert(0, str(plugin / "lib"))
    import groom_common as gm
    import sediment_state as ss

    calls = {"n": 0}
    original = gm.run_git

    def counted(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    times = []
    payload = None
    for attempt in range(repeat):
        calls["n"] = 0
        gm.run_git = counted
        try:
            started = time.perf_counter()
            payload = ss.collect(repo)
            times.append(time.perf_counter() - started)
        finally:
            gm.run_git = original
        if attempt == 0:
            git_calls = calls["n"]
    if payload is None:
        raise SystemExit("collect 没有返回结果")
    payload_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return {
        "seconds": min(times),
        "git_calls": git_calls,
        "payload_bytes": payload_bytes,
        "rows": len(payload.get("drafts") or []),
        "counts": payload.get("counts") or {},
    }


def main(argv=None) -> int:
    pin_utf8_stdio()
    args, plugin, repo_root = parse_args(sys.argv[1:] if argv is None else argv)
    with tempfile.TemporaryDirectory(prefix="sediment-bench-") as tmp:
        repo = build_fixture(Path(tmp), repo_root, args.drafts, args.traces, args.decided)
        result = measure(plugin, repo, args.repeat)
    result.update({
        "plugin": str(plugin),
        "drafts": args.drafts,
        "traces": args.traces,
        "decided": bool(args.decided),
    })
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0
    print(f"插件：{result['plugin']}")
    print(f"夹具：{result['drafts']} 份草稿 / {result['traces']} 条 trace"
          f"{'（全部已决定，队列 = 待提 PR）' if args.decided else '（1/5 未评估）'}，"
          f"队列 {result['rows']} 行")
    print(f"打开一次：{result['seconds']:.3f} s（{args.repeat} 次最小值）"
          f" · git 子进程 {result['git_calls']} 次"
          f" · payload {result['payload_bytes'] / 1024:.0f} KB")
    counts = result["counts"]
    if counts:
        print(f"状态：待决定 {counts.get('needDecision', 0)} · 需重跑 {counts.get('needRerun', 0)}"
              f" · 待提 PR {counts.get('decided', 0)} · 未评估 {counts.get('unassessed', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
