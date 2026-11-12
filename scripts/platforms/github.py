#!/usr/bin/env python3
"""GitHub 平台适配器（可执行式，kind=exec；靠 gh CLI 取状态）。

为什么是 Python 而不是 YAML：GitHub 有标准 API，但本机通常已经用 `gh auth login`
登录过；再让用户配一个 token 等于多维护一份凭据。查 PR 状态是只读操作，交给 gh 最省配置。
代价是「装不装 gh」成了主路径上的依赖，所以 REQUIRES 里声明它，缺了就报 degraded，
不假装能查（设计 5.6 的「没有适配就显示本机没有对应工具」）。

边界：**import 时不得跑子进程**。模块导入只定义函数；`check()` 才会调 `gh`。
core（pr_status.py）用 importlib 加载本文件，加载失败会归一成 unknown，不中断列表。

宿主 host 只写 github.com：GitHub Enterprise 的 host 不固定，按设计 5.8 由部署侧另加
一个 `<id>.py`（固定 host），不在核心脚本里留后缀匹配规则。
"""

from __future__ import annotations

import json
import subprocess

ID = "github"
NAME = "GitHub"
HOSTS = ["github.com"]
AUTH_ENV = None
# gh 自己管鉴权（gh auth login）；不在这里声明 token 环境变量。
REQUIRES = ["gh"]
INSTALL_HINT = "安装 GitHub CLI（brew install gh / 发行版包管理器 / 内网离线包），再跑 gh auth login"

TIMEOUT_S = 20


def _state_of(payload: dict) -> str:
    """把 gh 返回的 state / mergedAt 归一成四种状态。

    单独成函数是为了 `selftest()` 不联网、也不跑 gh 就能测这段映射。
    先看 mergedAt：gh 的 state 在合入后是 `MERGED`，但旧版本/部分事件里可能仍是
    `CLOSED` + `mergedAt` 非空，所以 mergedAt 优先。
    """
    if not isinstance(payload, dict):
        return "unknown"
    state = str(payload.get("state") or "").upper()
    if payload.get("mergedAt") or state == "MERGED" or state == "MERGED_AT":
        return "merged"
    if state == "OPEN":
        return "open"
    if state == "CLOSED":
        return "closed"
    return "unknown"


def check(pr):
    """查一条 PR 的状态。失败一律返回 unknown + detail，不抛给调用方看 traceback。"""
    repo = str((pr or {}).get("repo") or "")
    number = str((pr or {}).get("number") or "")
    if not repo or not number:
        return {"state": "unknown", "detail": "缺 repo 或 number"}
    try:
        proc = subprocess.run(
            ["gh", "pr", "view", number, "--repo", repo,
             "--json", "state,mergedAt,url"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=TIMEOUT_S,
        )
    except FileNotFoundError:
        return {"state": "unknown", "detail": "找不到 gh 命令"}
    except subprocess.TimeoutExpired:
        return {"state": "unknown", "detail": f"gh 查询超时（{TIMEOUT_S}s）"}
    except OSError as exc:
        return {"state": "unknown", "detail": f"gh 启动失败：{exc}"}
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return {"state": "unknown", "detail": detail[:500] or f"gh 退出码 {proc.returncode}"}
    try:
        payload = json.loads(proc.stdout or "{}")
    except ValueError as exc:
        return {"state": "unknown", "detail": f"gh 输出不是 JSON：{exc}"}
    return {"state": _state_of(payload), "detail": str(payload.get("url") or "")}


def fetch(pr):
    """取收尾所需证据：状态、body、合入提交、base/head。失败返回 ok=False + detail。

    只在自动收尾里调用；与 check() 分开，避免「只查状态」的调用多拉一份 body。
    """
    repo = str((pr or {}).get("repo") or "")
    number = str((pr or {}).get("number") or "")
    if not repo or not number:
        return {"ok": False, "detail": "缺 repo 或 number"}
    try:
        proc = subprocess.run(
            ["gh", "pr", "view", number, "--repo", repo,
             "--json", "state,mergedAt,url,body,mergeCommit,baseRefName,headRefOid"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=TIMEOUT_S,
        )
    except FileNotFoundError:
        return {"ok": False, "detail": "找不到 gh 命令"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": f"gh 取证超时（{TIMEOUT_S}s）"}
    except OSError as exc:
        return {"ok": False, "detail": f"gh 启动失败：{exc}"}
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return {"ok": False, "detail": detail[:500] or f"gh 退出码 {proc.returncode}"}
    try:
        payload = json.loads(proc.stdout or "{}")
    except ValueError as exc:
        return {"ok": False, "detail": f"gh 输出不是 JSON：{exc}"}
    if not isinstance(payload, dict):
        return {"ok": False, "detail": "gh 输出顶层不是对象"}
    merge = payload.get("mergeCommit")
    merge_sha = str((merge or {}).get("oid") or "") if isinstance(merge, dict) else str(merge or "")
    return {
        "ok": True,
        "state": _state_of(payload),
        "url": str(payload.get("url") or ""),
        "body": str(payload.get("body") or ""),
        "merge_commit": merge_sha,
        "base": str(payload.get("baseRefName") or ""),
        "head": str(payload.get("headRefOid") or ""),
    }


def create_hint(target):
    """给提 PR 指令用的命令模板；标签按目标配置追加，没配就不加。"""
    target = target or {}
    repo = str(target.get("repo") or "<owner/repo>")
    base = str(target.get("base") or "main")
    labels = target.get("labels") or {}
    label_args = " ".join(f"--label {value}" for value in labels.values()) if labels else ""
    return (f"gh pr create --repo {repo} --base {base} --body-file <pr-body.md>"
            + (f" {label_args}" if label_args else ""))


def check_hint(pr):
    """「查状态」指令里给人看的一行命令；不跑它，只生成。"""
    pr = pr or {}
    repo = str(pr.get("repo") or "<owner/repo>")
    number = str(pr.get("number") or "<number>")
    return f"gh pr view {number} --repo {repo} --json state,mergedAt,url"


def selftest():
    """不联网、不跑 gh：只测状态归一。返回 (passed, cases)。"""
    cases = [
        ("open", {"state": "OPEN", "mergedAt": None}, "open"),
        ("closed", {"state": "CLOSED", "mergedAt": None}, "closed"),
        ("merged", {"state": "MERGED", "mergedAt": None}, "merged"),
        ("closed-but-mergedAt", {"state": "CLOSED", "mergedAt": "2026-11-01T00:00:00Z"}, "merged"),
        ("unknown", {"state": "DRAFT"}, "unknown"),
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
