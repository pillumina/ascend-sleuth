#!/usr/bin/env python3
"""_settings.py —— 本机 settings（`.local/settings.json`）的唯一读写实现。

为什么单独一个模块：这份文件的 schema、默认值、归一化与 CAS 写入原先只有 `kb_sync`
一份实现，读侧却有四个消费点（`kb_sync` 的同步、`pr_status` 的目标与 sync 段写回、
`doctor` 的体检、`groom_snapshot` 的同步源选择）。每处各解析一次时，改 schema、加字段
或改夹取区间都要靠人记得同步——漏一处不报错，只是两边对同一份配置得出不同结论。

`kb_sync.py` 把这批名字 re-export 回原命名空间，`kb_sync.load_settings` 等既有调用不变。

`load_settings(with_meta=True)` 多回一个内部细节（文件里写没写 `sync` 段、错误种类），
给 groom 保留「配置里没写同步源就先问用户」的原有行为与旧错误文案；取值一律用前三项。

写锁的取法有个兼容约束：拆分前 `log_lock` 与 `save_settings` 在同一个命名空间，调用方与
测试用 `mock.patch.object(kb_sync, "log_lock")` 替换它。拆库后 `save_settings` 仍要打在这个
名字上，所以 `_write_lock` 先看 `sys.modules["kb_sync"]`；没有该模块（例如只 import
`_settings` 的 doctor）时用本模块导入的那一份。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from _fs import atomic_write_text
from exec_log_path import log_lock, main_checkout, write_refused_message

SCHEMA_SETTINGS = "ascend-sleuth-settings/1"
SETTINGS_REL = Path(".local") / "settings.json"
DEFAULT_TIMEOUT = 10.0
DEFAULT_REMOTE = "origin"
DEFAULT_BRANCH = "main"
#: 后台提醒检查的间隔缺省值与合法区间（分钟）。
DEFAULT_CHECK_MINUTES = 30
CHECK_MINUTES_MIN = 5
CHECK_MINUTES_MAX = 720


class SettingsError(RuntimeError):
    """settings 写不进去。调用方折成自己的错误码。"""


class SettingsCasConflict(SettingsError):
    """写前发现 settings 文件字节已变（别的进程写过）。调用方不覆盖。"""

    def __init__(self, expected: str, actual: str):
        super().__init__(f"配置已被改动：expect {expected or '（文件不存在）'}，"
                         f"实际 {actual or '（文件不存在）'}")
        self.expected = expected
        self.actual = actual


# ---------------------------------------------------------------- 路径与时间

def repo_root(root: Path) -> Path:
    """主检出根（settings 与状态文件锚在这里，同一克隆的 worktree 共用一份）。"""
    root = Path(root)
    return main_checkout(root) or root


def settings_path(root: Path) -> Path:
    return repo_root(root) / SETTINGS_REL


def _run_git(args, cwd: Path, timeout: float):
    """settings 只读默认分支用的一条 git 命令（不复用 kb_sync 的 run_git：避免循环 import）。"""
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True,
        timeout=timeout, encoding="utf-8", errors="replace",
    )


def _git_text(root: Path, args, timeout: float):
    try:
        proc = _run_git(args, root, timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip()


# ---------------------------------------------------------------- 归一化

def default_settings() -> dict:
    return {
        "schema": SCHEMA_SETTINGS,
        "sync": {"remote": DEFAULT_REMOTE, "branch": DEFAULT_BRANCH,
                 "enabled": True, "auto_merge": True,
                 "check_enabled": True, "check_minutes": DEFAULT_CHECK_MINUTES,
                 "check_full_access": True},
        "identity": {"remote": DEFAULT_REMOTE},
        "target": None,
    }


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "on", "yes", "1"):
            return True
        if text in ("false", "off", "no", "0"):
            return False
    return default


def clamp_check_minutes(value) -> int:
    """提醒检查间隔 → 5..720 的整数。非整数取默认 30，越界夹到边界。

    读侧只夹取不报错：坏配置不该让后台检查失败，写侧（`pr_status --set-sync`）在落盘前
    另行校验并拒绝越界值。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_CHECK_MINUTES
    return max(CHECK_MINUTES_MIN, min(CHECK_MINUTES_MAX, value))


def normalize_sync(raw) -> dict:
    """`sync` 段 → 七个字段。缺项与类型不对的项取默认值。"""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "remote": str(raw.get("remote") or DEFAULT_REMOTE).strip() or DEFAULT_REMOTE,
        "branch": str(raw.get("branch") or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH,
        "enabled": _as_bool(raw.get("enabled"), True),
        "auto_merge": _as_bool(raw.get("auto_merge"), True),
        "check_enabled": _as_bool(raw.get("check_enabled"), True),
        "check_minutes": clamp_check_minutes(raw.get("check_minutes")),
        # 后台提醒检查跑不跑在沙箱里：true（默认）时以完全权限跑，false 跟随部署默认档。
        "check_full_access": _as_bool(raw.get("check_full_access"), True),
    }


def normalize_identity(raw) -> dict:
    """`identity` 段 → `{"remote": ...}`。缺项与空值取 origin。

    `load_settings` 会在返回值里加一个内存字段 `explicit`；写盘前过这一步把它丢掉。
    """
    raw = raw if isinstance(raw, dict) else {}
    return {"remote": str(raw.get("remote") or DEFAULT_REMOTE).strip() or DEFAULT_REMOTE}


def normalize_target(raw):
    """`target` 段 → 与 pr_status 对外结构一致的映射；没有可用远端时返回 None。"""
    if not isinstance(raw, dict) or not str(raw.get("remote") or "").strip():
        return None
    labels = raw.get("labels")
    return {
        "remote": str(raw.get("remote")),
        "base": str(raw.get("base") or DEFAULT_BRANCH),
        "platform": str(raw.get("platform") or ""),
        "url": str(raw.get("url") or ""),
        "note": str(raw.get("note") or ""),
        "labels": labels if isinstance(labels, dict) else {},
        "source": str(raw.get("source") or "user"),
        "chosen_at": str(raw.get("chosen_at") or ""),
    }


def load_settings(root: Path, *, with_meta: bool = False):
    """→ (settings, config, problem)。config 是 `file`（读到了）或 `default`（缺失/损坏）。

    `with_meta=True` 时多回一个 dict（`path` / `sync_present` / `sync_is_mapping` /
    `raw_sync` / `error_kind` / `error_detail`），只给 groom 判断「配置里有没有写同步源」
    与还原旧错误文案；取值一律用前三项，不要从 meta 取配置值。
    """
    path = settings_path(root)
    meta = {"path": str(path), "sync_present": False, "sync_is_mapping": True,
            "raw_sync": None, "error_kind": "", "error_detail": ""}

    def done(data, config, problem, kind: str = "", detail=""):
        meta.update(error_kind=kind, error_detail=str(detail or ""))
        return (data, config, problem, meta) if with_meta else (data, config, problem)

    def fallback(problem: str, kind: str = "", detail=""):
        data = default_settings()
        data["identity"]["explicit"] = False
        data["sync"]["branch"] = default_branch(Path(root), data["sync"]["remote"])
        return done(data, "default", problem, kind, detail)

    if not path.is_file():
        return fallback("")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return fallback(f"读不出 {path}：{exc}", "read", exc)
    if not isinstance(raw, dict):
        return fallback(f"{path} 顶层不是对象", "shape")
    schema = str(raw.get("schema") or "")
    if schema and not schema.startswith("ascend-sleuth-settings/"):
        return fallback(f"{path} 的 schema {schema!r} 不认", "schema", schema)
    raw_sync = raw.get("sync") if isinstance(raw.get("sync"), dict) else {}
    raw_identity = raw.get("identity") if isinstance(raw.get("identity"), dict) else None
    meta.update(sync_present=raw.get("sync") is not None,
                sync_is_mapping=isinstance(raw.get("sync"), dict),
                raw_sync=raw_sync if isinstance(raw.get("sync"), dict) else None)
    data = dict(raw)
    data["schema"] = SCHEMA_SETTINGS
    data["sync"] = normalize_sync(raw_sync)
    data["identity"] = normalize_identity(raw_identity)
    # explicit 只活在内存里：文件里写了 identity.remote 才算显式；写盘时丢掉。
    data["identity"]["explicit"] = bool(
        raw_identity is not None and str(raw_identity.get("remote") or "").strip())
    if not str(raw_sync.get("remote") or "").strip():
        data["sync"]["remote"] = data["identity"]["remote"]
    data["target"] = normalize_target(raw.get("target"))
    return done(data, "file", "")


def default_branch(root: Path, remote: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    """配置没写分支时取当前分支的上游分支名；取不到用 main。"""
    upstream = _git_text(root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], timeout)
    if upstream and "/" in upstream:
        return upstream.split("/", 1)[1]
    head = _git_text(root, ["symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD"], timeout)
    if head and head.startswith(remote + "/"):
        return head.split("/", 1)[1]
    return DEFAULT_BRANCH


def settings_sha256(root: Path):
    try:
        return hashlib.sha256(settings_path(root).read_bytes()).hexdigest()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SettingsError(f"读配置失败：{exc}") from exc


def _write_json(path: Path, data: dict) -> str:
    """同目录临时文件 + fsync + os.replace；返回落盘文本。"""
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, text)
    return text


def _write_lock(path: Path):
    """配置写锁。优先取 `kb_sync.log_lock`（拆分前的同名补丁点），见模块头。"""
    host = sys.modules.get("kb_sync")
    lock = getattr(host, "log_lock", None) if host is not None else None
    return (lock or log_lock)(path)


def save_settings(root: Path, data: dict, expect_sha=None) -> str:
    """原子写 settings；`expect_sha` 给了就做文件字节 CAS。返回新 sha256。

    文件层失败（开锁文件、建目录、替换配置被系统拒绝）折成 SettingsError：
    调用方按 E_SETTINGS 显示路径与原因，不落成 E_INTERNAL 的裸异常。
    """
    path = settings_path(root)
    data = dict(data)
    data["schema"] = SCHEMA_SETTINGS
    data["sync"] = normalize_sync(data.get("sync"))
    # 归属仓默认 origin 且未显式配置时不落盘：否则一次普通的 --set-sync 会把默认值写成
    # 显式声明，默认 origin 缺失的单远端检出会从「放行」变成 identity-unresolved。
    identity_raw = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    identity_remote = str(identity_raw.get("remote") or DEFAULT_REMOTE).strip() or DEFAULT_REMOTE
    if bool(identity_raw.get("explicit")) or identity_remote != DEFAULT_REMOTE:
        data["identity"] = normalize_identity(identity_raw)
    else:
        data.pop("identity", None)
    data["target"] = normalize_target(data.get("target"))
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    try:
        with _write_lock(path) as locked:
            if not locked:
                raise SettingsError(f"配置写锁不可用：{path}")
            actual = settings_sha256(root)
            if expect_sha is not None and actual != expect_sha:
                raise SettingsCasConflict(expect_sha, actual or "")
            written_text = _write_json(path, data)
    except OSError as exc:
        raise SettingsError(write_refused_message("配置", path, exc)) from exc
    if written_text != text:  # 同一份序列化，防写后漂移
        raise SettingsError("配置写后校验失败（磁盘内容与本次序列化不一致）")
    return settings_sha256(root)
