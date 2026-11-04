#!/usr/bin/env python3
"""GitLab 平台适配器（可执行式，kind=exec；靠 glab CLI 取状态）。

为什么与 GitHub 一样走 Python：同样的事实（PR 状态）已经有 CLI 在管登录，另配 token
等于多维护一份凭据。差别只在本机可能根本没装 glab——所以 REQUIRES 声明它，缺了 core
按「没有对应工具」降级，不阻断提 PR（设计 5.6、5.7）。

边界：import 不跑子进程；`check()` 才调 `glab`。自建 GitLab 的 host 不固定，按设计 5.8
由部署侧照本文件另加一个（改 ID / NAME / HOSTS 与 INSTALL_HINT 即可），核心不改。
"""

from __future__ import annotations

import json
import subprocess

ID = "gitlab"
NAME = "GitLab"
HOSTS = ["gitlab.com"]
AUTH_ENV = None
# glab 自己管鉴权（glab auth login）；不在这里声明 token 环境变量。
REQUIRES = ["glab"]
INSTALL_HINT = "安装 GitLab CLI（glab），再跑 glab auth login；自建 GitLab 需先设 GITLAB_HOST"

TIMEOUT_S = 20


def _state_of(payload: dict) -> str:
    """glab 的 state 归一成四种状态。单独成函数，好让 selftest 不联网、不跑 glab。

    glab 可能返回 `opened` / `closed` / `merged` / `locked`（被锁的 MR 仍可能是开的，
    但状态语义不明确，归一成 unknown，不猜）。
    """
    if not isinstance(payload, dict):
        return "unknown"
    state = str(payload.get("state") or "").lower()
    if state == "merged":
        return "merged"
    if state == "opened" or state == "open":
        return "open"
    if state == "closed":
        return "closed"
    return "unknown"


def check(pr):
    """查一条 MR 的状态。失败一律返回 unknown + detail。"""
    repo = str((pr or {}).get("repo") or "")
    number = str((pr or {}).get("number") or "")
    if not repo or not number:
        return {"state": "unknown", "detail": "缺 repo 或 number"}
    try:
        proc = subprocess.run(
            ["glab", "mr", "view", number, "--repo", repo, "--json", "state"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=TIMEOUT_S,
        )
    except FileNotFoundError:
        return {"state": "unknown", "detail": "找不到 glab 命令"}
    except subprocess.TimeoutExpired:
        return {"state": "unknown", "detail": f"glab 查询超时（{TIMEOUT_S}s）"}
    except OSError as exc:
        return {"state": "unknown", "detail": f"glab 启动失败：{exc}"}
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return {"state": "unknown", "detail": detail[:500] or f"glab 退出码 {proc.returncode}"}
    try:
        payload = json.loads(proc.stdout or "{}")
    except ValueError as exc:
        return {"state": "unknown", "detail": f"glab 输出不是 JSON：{exc}"}
    return {"state": _state_of(payload), "detail": ""}


def create_hint(target):
    """给提 PR 指令用的命令模板；标签按目标配置追加，没配就不加。"""
    target = target or {}
    repo = str(target.get("repo") or "<owner/repo>")
    base = str(target.get("base") or "main")
    labels = target.get("labels") or {}
    label_args = " ".join(f"--label {value}" for value in labels.values()) if labels else ""
    return (f"glab mr create --repo {repo} --target-branch {base} --description <pr-body.md>"
            + (f" {label_args}" if label_args else ""))


def check_hint(pr):
    """「查状态」指令里给人看的一行命令；不跑它，只生成。"""
    pr = pr or {}
    repo = str(pr.get("repo") or "<owner/repo>")
    number = str(pr.get("number") or "<number>")
    return f"glab mr view {number} --repo {repo} --json state"


def selftest():
    """不联网、不跑 glab：只测状态归一。返回 (passed, cases)。"""
    cases = [
        ("opened", {"state": "opened"}, "open"),
        ("merged", {"state": "merged"}, "merged"),
        ("closed", {"state": "closed"}, "closed"),
        ("locked", {"state": "locked"}, "unknown"),
        ("unknown", {"state": "weird"}, "unknown"),
        ("not-a-dict", None, "unknown"),
    ]
    results = []
    passed = 0
    for name, payload, expected in cases:
        actual = _state_of(payload)
        ok = actual == expected
        passed += 1 if ok else 0
        results.append({"name": name, "ok": ok, "expected": expected, "actual": actual})
    return passed, results
