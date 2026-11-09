#!/usr/bin/env python3
"""kb_sync.py —— 知识库读侧的同步入口（fetch / 条件合并 / 只读状态）。

诊断读的是本机检出的 `knowledge/`，而它可能落后上游几个提交。开单前同步一次，能把
候选集与 case 内容拉到较新的版本；是否合并另判，因为合并会改当前检出的 HEAD。

配置在主检出的 `.local/settings.json`（schema `ascend-sleuth-settings/1`，不进 git）：

    {"schema": "ascend-sleuth-settings/1",
     "sync": {"remote": "origin", "branch": "main", "enabled": true, "auto_merge": true,
              "check_enabled": true, "check_minutes": 30},
     "identity": {"remote": "origin"},
     "target": {...}}

`identity.remote` 是归属仓（默认 origin）：同源比较拿它的 URL，写侧的比较基准也按它的默认
分支算，`sync.remote` 未显式配置时跟随它。归属仓显式配置却在本机解析不到时，合并前拦下
（reason `identity-unresolved`）。

配置文件缺失或读不出时用默认值（远端 origin、分支取当前分支上游（取不到则 main）、同步开），
结果里 `config: "default"`。失败结果缓存在 `.local/kb-sync-state.json`：自动同步在 10 分钟内
不重试，避免每次开单都等满超时。手动同步加 `--force` 跳过窗口立即重试（面板「立即同步」走这条），
否则刚失败过的网络在 10 分钟内点几次都只会拿回同一份缓存。

`sync.enabled` 只拦自动路径（开单时的自动 fetch 与自动合并）：`--check` 只 fetch、不合并，
也不看它；带 `--force` 的手动路径（`--merge --force`）同样不看它。后台提醒检查用 `--check`，
它的开关与间隔是 `sync.check_enabled`（默认 true）与 `sync.check_minutes`（默认 30，
夹在 5..720 之间）。

`--check` 的 fetch 被权限拒绝（沙箱或文件权限写不进检出）时改用只读探测：`git ls-remote`
问远端分支的 sha，再用 `git merge-base --is-ancestor` 判它是否从本地 HEAD 可达，只能判出
远端有没有本地 HEAD 未包含的提交。结果里 `degraded` 非空、`degraded_error` 是 fetch 的
原始一行错误、`surface_known` 为 false。

`--no-write-fetch-head` 让权限失败从写 `FETCH_HEAD` 后移到对象写入：stderr 变成
`insufficient permission for adding an object` 与 `failed to write object`，归类要覆盖这条
路径，否则探测不会触发。该选项要 git 2.29 才有；老 git 报 unknown / unrecognized option
时去掉它重试一次（全仓没有 `FETCH_HEAD` 消费点）。

探测成功也把本次核对记为成功（`reason` 清空、`last_ok_at` 前移）；探测失败按
`permission-denied` 记失败。落后数、领先数与改动面都要先把提交取回本地才算得出，这一路
一律未知。

自动合并只在这些条件同时成立时发生：当前分支 = 配置 `branch`、HEAD 是远端分支的祖先、
`git status --porcelain -uno` 为空、无进行中 merge / rebase / cherry-pick。worktree 与
detached HEAD 不自动合并——合并会改当前检出的 HEAD，而 worktree 可能正被另一单使用。
同步源与归属仓不同源时同样只 fetch、不合并（reason `same-repo`）：合并会把另一个仓的
提交带进当前检出。归属仓显式配置却解析不到时也不合并（reason `identity-unresolved`）。

用法：
  python3 scripts/kb_sync.py --show          # 只读，不联网：配置、HEAD、本地远端 ref、上次核对
  python3 scripts/kb_sync.py --sync          # fetch；不合并
  python3 scripts/kb_sync.py --check         # 只 fetch、不合并；不看 sync.enabled（后台提醒检查用）
  python3 scripts/kb_sync.py --merge         # fetch，条件满足时试 ff-only
  python3 scripts/kb_sync.py --merge --force # 跳过失败缓存立即重试（手动同步用；也不看 sync.enabled）
  python3 scripts/kb_sync.py --show --json   # 所有子命令都可加 --json
  python3 scripts/kb_sync.py --sync --timeout 3 --root <检出>

结果里的稳定取值（文档与测试可直接断言）：
  ok       true / false
  reason   "" | timeout | network | permission-denied | no-remote | not-a-repo | lock |
           exit-<n> | offline | disabled | dirty | branch-mismatch | not-ancestor |
           merge-in-progress | auto-merge-off | not-ff | same-repo | identity-unresolved
  fetch_error  本次 fetch 失败时 git 原始输出的末行（已抹掉 URL 里的凭据）；成功与 --show 时为空
  last_error   --show 时上次失败留下的同一条原文；没有失败记录时为空
  merge    ff-only | none
  surface  各键计数：knowledge / routing / reference / methodology / panel / other；
           ff-only 合并成功时表示本次合并带进来的改动面，没有合并时表示本地落后于远端的改动面
  surface_known  false 表示 surface 计数不可用（只在 degraded 时出现）
  degraded  "" | permission-denied；--check 的 fetch 被权限拒绝并完成只读探测时非空
  degraded_error  fetch 的原始一行错误（degraded 非空时）
  update_available  true / false（degraded 时只读探测的结论：远端有没有本地 HEAD 未包含的提交）
  config   file | default
  enabled  true / false（settings 的 sync.enabled；--show 也照实给）
          只拦自动路径：--check 与带 --force 的手动路径不看它，结果里仍照实上报
  offline  true / false（deployment.yaml 声明 sync.mode: offline）
  identity_remote     归属仓远端名（默认 origin）
  identity_url        归属仓解析到的 URL；取不到为空串
  identity_explicit   settings 里是否显式写了 identity.remote
  identity_resolved   归属仓在本机解析得到 URL
  same_repo           同步源与归属仓的 host+path 是否一致；取不到 null

退出码：0 = 已执行（含 fetch 失败、跳过、离线等降级）；2 = 参数不合法。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exec_log_path import log_lock, main_checkout, write_refused_message  # noqa: E402

SCHEMA_SETTINGS = "ascend-sleuth-settings/1"
SCHEMA_STATE = "ascend-sleuth-kb-sync-state/1"
SETTINGS_REL = Path(".local") / "settings.json"
STATE_REL = Path(".local") / "kb-sync-state.json"
DEFAULT_TIMEOUT = 10.0
FAILURE_COOLDOWN_S = 600
# fetch 失败时保留的 git 原始输出上限（字符）。状态文件与面板都读这一份。
FETCH_ERROR_LIMIT = 300
DEFAULT_REMOTE = "origin"
DEFAULT_BRANCH = "main"
#: 后台提醒检查的间隔缺省值与合法区间（分钟）。
DEFAULT_CHECK_MINUTES = 30
CHECK_MINUTES_MIN = 5
CHECK_MINUTES_MAX = 720
SURFACE_KEYS = ("knowledge", "routing", "reference", "methodology", "panel", "other")


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


def state_path(root: Path) -> Path:
    return repo_root(root) / STATE_REL


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _parse_iso(text: str):
    try:
        value = datetime.fromisoformat(str(text or "").strip())
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


# ---------------------------------------------------------------- settings

def default_settings() -> dict:
    return {
        "schema": SCHEMA_SETTINGS,
        "sync": {"remote": DEFAULT_REMOTE, "branch": DEFAULT_BRANCH,
                 "enabled": True, "auto_merge": True,
                 "check_enabled": True, "check_minutes": DEFAULT_CHECK_MINUTES},
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
    """`sync` 段 → 六个字段。缺项与类型不对的项取默认值。"""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "remote": str(raw.get("remote") or DEFAULT_REMOTE).strip() or DEFAULT_REMOTE,
        "branch": str(raw.get("branch") or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH,
        "enabled": _as_bool(raw.get("enabled"), True),
        "auto_merge": _as_bool(raw.get("auto_merge"), True),
        "check_enabled": _as_bool(raw.get("check_enabled"), True),
        "check_minutes": clamp_check_minutes(raw.get("check_minutes")),
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


def load_settings(root: Path):
    """→ (settings, config, problem)。config 是 `file`（读到了）或 `default`（缺失/损坏）。"""
    def fallback(problem: str):
        data = default_settings()
        data["identity"]["explicit"] = False
        data["sync"]["branch"] = default_branch(Path(root), data["sync"]["remote"])
        return data, "default", problem

    path = settings_path(root)
    if not path.is_file():
        return fallback("")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return fallback(f"读不出 {path}：{exc}")
    if not isinstance(raw, dict):
        return fallback(f"{path} 顶层不是对象")
    schema = str(raw.get("schema") or "")
    if schema and not schema.startswith("ascend-sleuth-settings/"):
        return fallback(f"{path} 的 schema {schema!r} 不认")
    data = dict(raw)
    data["schema"] = SCHEMA_SETTINGS
    raw_sync = raw.get("sync") if isinstance(raw.get("sync"), dict) else {}
    raw_identity = raw.get("identity") if isinstance(raw.get("identity"), dict) else None
    data["sync"] = normalize_sync(raw_sync)
    data["identity"] = normalize_identity(raw_identity)
    # explicit 只活在内存里：文件里写了 identity.remote 才算显式；写盘时丢掉。
    data["identity"]["explicit"] = bool(
        raw_identity is not None and str(raw_identity.get("remote") or "").strip())
    if not str(raw_sync.get("remote") or "").strip():
        data["sync"]["remote"] = data["identity"]["remote"]
    data["target"] = normalize_target(raw.get("target"))
    return data, "file", ""


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
    import hashlib
    try:
        return hashlib.sha256(settings_path(root).read_bytes()).hexdigest()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SettingsError(f"读配置失败：{exc}") from exc


def _write_json(path: Path, data: dict) -> str:
    """同目录临时文件 + fsync + os.replace；返回落盘文本。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return text


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
        with log_lock(path) as locked:
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


# ---------------------------------------------------------------- 失败缓存

def load_state(root: Path) -> dict:
    empty = {"schema": SCHEMA_STATE, "last_ok_at": "", "attempted_at": "",
             "reason": "", "remote": "", "branch": "", "fetch_error": ""}
    path = state_path(root)
    if not path.is_file():
        return empty
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return empty
    if not isinstance(raw, dict):
        return empty
    out = dict(empty)
    for key in empty:
        if key in raw:
            out[key] = raw[key]
    return out


def save_state(root: Path, state: dict) -> bool:
    try:
        _write_json(state_path(root), state)
        return True
    except OSError:
        return False


def _cooling_down(state: dict) -> bool:
    """上次失败是否还在 10 分钟窗口内。只认有原因且时间可解析的记录。"""
    if not str(state.get("reason") or "").strip():
        return False
    attempted = _parse_iso(state.get("attempted_at"))
    if attempted is None:
        return False
    return (datetime.now(timezone.utc) - attempted).total_seconds() < FAILURE_COOLDOWN_S


# ---------------------------------------------------------------- 部署声明

def deployment_sync_mode(root: Path) -> str:
    """`deployment.yaml` 的 `sync.mode` → `auto` / `offline`；读不出按 auto。

    没有 PyYAML 时退回按缩进读 `sync:` 段——离线声明必须在最小环境里也生效，
    否则会朝一个明确声明不可达的远端发 fetch。
    """
    path = Path(root) / "deployment.yaml"
    if not path.is_file():
        return "auto"
    try:
        from _yaml import load_text
        doc = load_text(path.read_text(encoding="utf-8")) or {}
        sync = doc.get("sync") if isinstance(doc, dict) else None
        mode = str((sync or {}).get("mode") or "").strip().lower() if isinstance(sync, dict) else ""
        return "offline" if mode == "offline" else "auto"
    except Exception:
        pass
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "auto"
    in_sync = False
    for line in lines:
        if re.match(r"^sync:\s*(#.*)?$", line):
            in_sync = True
            continue
        if not in_sync:
            continue
        if line and not line.startswith((" ", "\t")):
            break
        match = re.match(r"\s+mode:\s*[\"']?([A-Za-z-]+)", line)
        if match:
            return "offline" if match.group(1).lower() == "offline" else "auto"
    return "auto"


# ---------------------------------------------------------------- git 读操作

def run_git(args, cwd: Path, timeout: float):
    """跑一条 git 命令。stdout/stderr 一律按 UTF-8 解码。"""
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True,
        timeout=timeout, encoding="utf-8", errors="replace",
    )


# fetch 失败要留给读者看的原始输出：git 的 fatal / error 行通常才带得上原因。
# 凭据覆盖：任意 scheme 的 URL userinfo（含密码里带 @）与常见 token 查询参数。
_URL_USERINFO = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^/\s]*@")
_URL_QUERY_SECRET = re.compile(
    r"([?&](?:token|access_token|private_token|oauth_token|api_key|apikey|secret_key|"
    r"password|key|secret|signature|sig)=)[^&\s'\"]+",
    re.I)
_FATAL_LINE = re.compile(r"^(?:fatal|error):", re.I)


def redact_secrets(text: str) -> str:
    """抹掉 URL 里的账号密码与查询串里的凭据。git 的报错会带远端地址。"""
    out = _URL_USERINFO.sub(r"\1***@", str(text or ""))
    return _URL_QUERY_SECRET.sub(r"\1***", out)


def _last_fatal_line(text: str) -> str:
    """多行输出 → 一行：优先取最后一条 fatal / error 行，再脱敏与截断。"""
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    picked = lines[-1]
    for line in reversed(lines):
        if _FATAL_LINE.match(line):
            picked = line
            break
    return redact_secrets(picked)[:FETCH_ERROR_LIMIT]


def fetch_error_of(proc) -> str:
    """git fetch 的失败输出 → 一行（脱敏、截断）。"""
    return _last_fatal_line((proc.stderr or "") + "\n" + (proc.stdout or ""))


def timeout_error_of(exc) -> str:
    """超时被 kill 的 git 也可能已经吐出错误行；有就一起留存。"""
    text = getattr(exc, "stderr", None) or getattr(exc, "output", None) or ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    return _last_fatal_line(text)


_AUTH_ERROR = re.compile(
    r"authentication failed|could not read username|terminal prompts disabled|"
    r"permission denied \(publickey\)|returned error: 40[13]",
    re.I)
# 网络/代理/TLS 一类：git 与 libcurl 的常见文案都收进来，别只认前三条。
# 刻意不写裸的 ssl / tls / proxy：主机名或路径里带这些词时，404 也会被误归到网络。
_NETWORK_ERROR = re.compile(
    r"could not resolve|failed to connect|connection (?:refused|reset|timed out)|"
    r"operation timed out|network is unreachable|no route to host|"
    r"ssl_connect|ssl_error|ssl routines|ssl certificate|openssl|gnutls|"
    r"handshake|certificate (?:verification|verify|problem|has expired)|"
    r"self[- ]signed|empty reply from server|tunnel failed|"
    r"proxy (?:connect|connection|error|authentication)|(?:from|to|via) proxy|"
    r"rpc failed|remote end hung up|early eof|"
    r"recv failure|send failure|returned error: 5\d\d",
    re.I)
# ref 锁：只认 git 的锁冲突文案，别把 "blocked" 里的 lock 字样或临时文件创建失败当成锁。
_LOCK_ERROR = re.compile(
    r"cannot lock|unable to lock|lock(?:ed|ing)? (?:ref|file)|\.lock\b|"
    r"reference.*locked|ref lock",
    re.I)
# 权限拒绝：沙箱或文件权限不让 git 写检出。两条失败路径都收：写 FETCH_HEAD（permission
# denied / operation not permitted），以及 --no-write-fetch-head 之后的写对象（insufficient
# permission / failed to write object）。
# 比对顺序见 fetch_failure_reason：SSH 凭据失败里的 "Permission denied (publickey)" 先归凭据。
_PERMISSION_ERROR = re.compile(
    r"permission denied|access is denied|operation not permitted|"
    r"insufficient permission|failed to write object",
    re.I)


def fetch_failure_reason(proc) -> str:
    """失败原因归类：ref 锁 → 凭据 → 权限拒绝 → network → exit-<码>。

    凭据类（401 / 403 / 认不出用户名）不归到 network：带读者往网络与代理上查会查错方向。
    权限拒绝排在凭据之后：SSH 的 `Permission denied (publickey)` 是认不出凭据，不是沙箱拒绝。
    权限拒绝同时覆盖写 `FETCH_HEAD` 与写对象两条文案，见 `_PERMISSION_ERROR`。
    """
    text = (proc.stderr or "") + "\n" + (proc.stdout or "")
    if _LOCK_ERROR.search(text):
        return "lock"
    code = proc.returncode if isinstance(proc.returncode, int) else 1
    if _AUTH_ERROR.search(text):
        return f"exit-{code}"
    if _PERMISSION_ERROR.search(text):
        return "permission-denied"
    if _NETWORK_ERROR.search(text):
        return "network"
    return f"exit-{code}"


def _run_fetch(root: Path, argv, timeout: float):
    """跑一次 fetch。→ (proc, reason, error)：超时与起不来时 proc 为 None 并给出归类。"""
    try:
        proc = run_git(argv, root, timeout)
    except subprocess.TimeoutExpired as exc:
        return None, "timeout", timeout_error_of(exc)
    except (OSError, subprocess.SubprocessError):
        return None, "exit-1", ""
    return proc, "", ""


def _lacks_no_write_fetch_head(proc) -> bool:
    """git 2.29 之前不认 `--no-write-fetch-head`：stderr 报 unknown / unrecognized option。

    老 git 上这条参数会让 fetch 直接失败，先去掉重试一次再谈归类。
    """
    text = (proc.stderr or "") + "\n" + (proc.stdout or "")
    if "no-write-fetch-head" not in text:
        return False
    return bool(re.search(r"unknown option|unrecognized option", text, re.I))


def _git_text(root: Path, args, timeout: float):
    try:
        proc = run_git(args, root, timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip()


def _remote_url(root: Path, name: str, timeout: float):
    if not name:
        return None
    return _git_text(root, ["remote", "get-url", name], timeout)


def _url_key(url: str):
    """远端 URL → (host, path)。只比 host 与 path，不比远端别名。"""
    text = str(url or "").strip()
    if not text:
        return None
    scheme, host, path = "", "", ""
    match = re.match(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<rest>.+)$", text)
    if match:
        scheme = match.group("scheme").lower()
        authority, _, path = match.group("rest").partition("/")
        host = authority.rsplit("@", 1)[-1]
        if host.startswith("["):
            host = host.split("]")[0].lstrip("[")
        elif ":" in host:
            host = host.rsplit(":", 1)[0]
    elif re.match(r"^[^/\\]+@[^:]+:.+$", text):
        scheme = "ssh"
        userhost, _, path = text.partition(":")
        host = userhost.rsplit("@", 1)[-1]
    elif re.match(r"^[^/\\]+:.+$", text) and not re.match(r"^[A-Za-z]:[\\/]", text):
        scheme = "ssh"
        host, _, path = text.partition(":")
    else:
        scheme = "local"
        path = text
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not host:
        try:
            path = str(Path(path).resolve())
        except (OSError, ValueError):
            pass
    return host.lower(), path


def same_repo(root: Path, remote: str, timeout: float, identity_remote: str = DEFAULT_REMOTE):
    """配置的同步源与归属仓的 host+path 是否一致；取不到返回 None。"""
    remote_url = _remote_url(root, remote, timeout)
    identity_url = _remote_url(root, identity_remote, timeout)
    left, right = _url_key(remote_url), _url_key(identity_url)
    if left is None or right is None:
        return None
    return left == right


def _merge_in_progress(root: Path, timeout: float) -> bool:
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
        text = _git_text(root, ["rev-parse", "--git-path", name], timeout)
        if not text:
            continue
        path = Path(text)
        if not path.is_absolute():
            path = root / path
        if path.exists():
            return True
    return False


def classify_surface(path: str) -> str:
    path = str(path or "").replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    if path.startswith("knowledge/"):
        return "knowledge"
    if path.startswith("triage-tree.d/") or path == "triage-tree.yaml":
        return "routing"
    if path.startswith("references/"):
        return "reference"
    if path.startswith("skills/"):
        return "methodology"
    if path.startswith("dsh-plugins/"):
        return "panel"
    return "other"


def _empty_base(remote: str, branch: str, config: str, config_error: str = "") -> dict:
    return {
        "ok": False,
        "remote": remote,
        "branch": branch,
        "local_rev": "unknown",
        "remote_rev": None,
        "behind": "unknown",
        "ahead": "unknown",
        "surface": {key: 0 for key in SURFACE_KEYS},
        "merge": "none",
        "reason": "",
        "skipped": False,
        "enabled": True,
        "offline": False,
        "config": config,
        "same_repo": None,
        "identity_remote": DEFAULT_REMOTE,
        "identity_url": "",
        "identity_explicit": False,
        "identity_resolved": False,
        # 合并提示要用合并前的坐标；不属于必需字段，但人读输出与 trace 提示都读它。
        "local_rev_before": "unknown",
        "behind_before": "unknown",
        "last_ok_at": "",
        "attempted_at": "",
        "last_reason": "",
        "last_error": "",
        "fetch_error": "",
        "config_error": config_error,
    }


def local_snapshot(root: Path, remote: str, branch: str, *, timeout: float = DEFAULT_TIMEOUT,
                   config: str = "file", config_error: str = "", enabled: bool = True,
                   identity: dict = None, ignore_disabled: bool = False) -> dict:
    """只读本机 git 状态（不联网），填 local_rev / 远端 ref / 落后数 / 改动面。

    `identity` 是 settings 的归属仓（`{"remote", "explicit"}`，缺省按 origin 且未显式）；
    `same_repo` 拿它的 URL 与 `remote` 的 URL 比。`enabled` 由调用方从 settings 的 sync 段
    带进来，`offline` 就地读 deployment.yaml；两者只读本地文件，`--show` 因此能给出真实
    状态而不联网。关闭或离线时 `ok: false` 并写对应 reason，但仍照常算落后数与改动面
    （面板要显示"落后多少、为什么没同步"）。`ignore_disabled=True` 时不因关闭写 reason
    （`--check` 与带 `--force` 的手动路径用），`enabled` 字段仍照实上报。
    """
    root = Path(root)
    identity = identity if isinstance(identity, dict) else {}
    identity_remote = str(identity.get("remote") or DEFAULT_REMOTE)
    result = _empty_base(remote, branch, config, config_error)
    result["enabled"] = bool(enabled)
    result["offline"] = deployment_sync_mode(root) == "offline"
    identity_url = _remote_url(root, identity_remote, timeout) if identity_remote else None
    result.update(identity_remote=identity_remote,
                  identity_url=identity_url or "",
                  identity_explicit=bool(identity.get("explicit")),
                  identity_resolved=bool(identity_url))

    def finish(res: dict) -> dict:
        if res["offline"]:
            res.update(ok=False, reason="offline", merge="none")
        elif not res["enabled"] and not ignore_disabled:
            res.update(ok=False, reason="disabled", merge="none")
        return res

    state = load_state(root)
    result["last_ok_at"] = str(state.get("last_ok_at") or "")
    result["attempted_at"] = str(state.get("attempted_at") or "")
    result["last_reason"] = str(state.get("reason") or "")
    result["last_error"] = str(state.get("fetch_error") or "")
    if _git_text(root, ["rev-parse", "--git-dir"], timeout) is None:
        result["reason"] = "not-a-repo"
        return finish(result)
    result["local_rev"] = _git_text(root, ["rev-parse", "--short", "HEAD"], timeout) or "unknown"
    result["local_rev_before"] = result["local_rev"]
    result["same_repo"] = same_repo(root, remote, timeout, identity_remote) if remote else None
    remote_ref = f"{remote}/{branch}" if remote and branch else ""
    if not remote_ref:
        return finish(result)
    remote_rev = _git_text(root, ["rev-parse", "--short", remote_ref], timeout)
    if not remote_rev:
        return finish(result)
    result["remote_rev"] = remote_rev
    behind = _git_text(root, ["rev-list", "--count", f"HEAD..{remote_ref}"], timeout)
    ahead = _git_text(root, ["rev-list", "--count", f"{remote_ref}..HEAD"], timeout)
    if behind is not None and behind.isdigit():
        result["behind"] = int(behind)
        result["behind_before"] = int(behind)
    if ahead is not None and ahead.isdigit():
        result["ahead"] = int(ahead)
    diff = _git_text(root, ["diff", "--name-only", f"HEAD..{remote_ref}"], timeout)
    counts = {key: 0 for key in SURFACE_KEYS}
    for line in (diff or "").splitlines():
        if line.strip():
            counts[classify_surface(line)] += 1
    result["surface"] = counts
    result["ok"] = True
    return finish(result)


# ---------------------------------------------------------------- 同步主流程

def sync(root: Path, *, do_fetch: bool = True, do_merge: bool = False,
         honor_auto_merge: bool = False, timeout: float = DEFAULT_TIMEOUT,
         force: bool = False, ignore_enabled: bool = False,
         probe_on_denied: bool = False) -> dict:
    """fetch（可选条件 ff-only 合并）→ 结果映射。任何失败都返回结果，不抛给调用方。

    `force=True` 跳过失败缓存：手动同步要能立刻重试，否则刚失败过的网络在 10 分钟内
    点几次都只会拿回同一份缓存。自动同步（建单、续接漂移检查）不加这个参数。
    `ignore_enabled=True`（`--check` 用）与 `force=True`（手动路径）不看 `sync.enabled`：
    两种情况照常联网，结果里的 `enabled` 仍按设置照实上报。离线声明仍拦下它们。
    `probe_on_denied=True`（`--check` 用）在 fetch 被权限拒绝时改用只读探测，详见
    `_probe_on_denied`；手动路径保持失败返回。
    """
    root = Path(root)
    settings, config, config_error = load_settings(root)
    sync_cfg = settings["sync"]
    identity = settings.get("identity")
    remote, branch = sync_cfg["remote"], sync_cfg["branch"]
    # force 只跳失败缓存，但手动路径也靠它绕过 enabled——面板「立即同步」就是
    # `--merge --force`，两个语义在同一个参数上。
    ignore_disabled = bool(force or ignore_enabled)
    result = local_snapshot(root, remote, branch, timeout=timeout, config=config,
                            config_error=config_error, enabled=sync_cfg["enabled"],
                            identity=identity, ignore_disabled=ignore_disabled)

    if result["offline"]:
        return result
    if not result["enabled"] and not ignore_disabled:
        return result
    if do_fetch and not force and _cooling_down(load_state(root)):
        state = load_state(root)
        result.update(ok=False, skipped=True, reason=str(state.get("reason") or "recent-failure"),
                      attempted_at=str(state.get("attempted_at") or ""),
                      fetch_error=str(state.get("fetch_error") or ""))
        return result

    if not do_fetch:
        return result

    if result["reason"] == "not-a-repo":
        return result
    if _remote_url(root, remote, timeout) is None:
        result.update(ok=False, reason="no-remote")
        return result

    argv = ["fetch", "--no-tags", "--no-write-fetch-head", remote, branch]
    proc, fail_reason, fail_error = _run_fetch(root, argv, timeout)
    if proc is None:
        return _record_fetch_failure(root, result, fail_reason, fail_error)
    if proc.returncode != 0 and _lacks_no_write_fetch_head(proc):
        # 老 git（2.29 之前）不认该选项：去掉它重试一次。全仓没有 FETCH_HEAD 消费点，
        # 老 git 上写 FETCH_HEAD 只多一次本地写，不改变合并用的 ref。
        proc, fail_reason, fail_error = _run_fetch(
            root, ["fetch", "--no-tags", remote, branch], timeout)
        if proc is None:
            return _record_fetch_failure(root, result, fail_reason, fail_error)
    if proc.returncode != 0:
        reason = fetch_failure_reason(proc)
        error = fetch_error_of(proc)
        if probe_on_denied and reason == "permission-denied":
            return _probe_on_denied(root, result, remote=remote, branch=branch,
                                    timeout=timeout, fetch_error=error)
        return _record_fetch_failure(root, result, reason, error)

    _record_fetch_ok(root, remote, branch)
    fresh = local_snapshot(root, remote, branch, timeout=timeout, config=config,
                           config_error=config_error, enabled=sync_cfg["enabled"],
                           identity=identity, ignore_disabled=ignore_disabled)
    result.update(fresh)
    result.update(ok=True, reason="", skipped=False, offline=False,
                  local_rev_before=fresh.get("local_rev_before", "unknown"),
                  behind_before=fresh.get("behind_before", "unknown"))

    if not do_merge:
        return result
    # 归属仓显式配置却解析不到：先拦下，不拿同步源猜合并基准。
    if fresh.get("identity_explicit") and not fresh.get("identity_resolved"):
        result.update(merge="none", reason="identity-unresolved")
        return result
    # 同步源与归属仓不同源时只拉不合并：合并会把另一个仓的提交带进当前检出。
    if fresh.get("same_repo") is False:
        result.update(merge="none", reason="same-repo")
        return result
    if fresh["behind"] in (0, "unknown"):
        return result
    if honor_auto_merge and not sync_cfg["auto_merge"]:
        result["reason"] = "auto-merge-off"
        return result

    reason = _merge_blocker(root, branch, f"{remote}/{branch}", timeout)
    if reason:
        result["reason"] = reason
        return result

    result["local_rev_before"] = fresh["local_rev"]
    result["behind_before"] = fresh["behind"]
    # 合并后 HEAD 已前移，after 的改动面是合并后 HEAD..远端（恒为 0）；本次合并带进来的
    # 改动面在合并前的 fresh 里，合并成功后放回去。
    incoming_surface = dict(fresh.get("surface") or {})
    remote_ref = f"{remote}/{branch}"
    try:
        merged = run_git(["merge", "--ff-only", remote_ref], root, timeout)
    except subprocess.TimeoutExpired:
        result["reason"] = "timeout"
        return result
    except (OSError, subprocess.SubprocessError):
        result["reason"] = "not-ff"
        return result
    if merged.returncode != 0:
        result["reason"] = "not-ff"
        return result

    after = local_snapshot(root, remote, branch, timeout=timeout, config=config,
                           config_error=config_error, enabled=sync_cfg["enabled"],
                           identity=identity, ignore_disabled=ignore_disabled)
    before_rev, before_behind = result["local_rev_before"], result["behind_before"]
    result.update(after)
    result.update(ok=True, reason="", merge="ff-only",
                  local_rev_before=before_rev, behind_before=before_behind,
                  surface=incoming_surface)
    return result


def _linked_worktree(root: Path, timeout: float) -> bool:
    """当前检出是不是 worktree（非主检出）：git-dir ≠ git-common-dir。"""
    git_dir = _git_text(root, ["rev-parse", "--absolute-git-dir"], timeout)
    common = _git_text(root, ["rev-parse", "--git-common-dir"], timeout)
    if not git_dir or not common:
        return False
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = Path(root) / common_path
    try:
        return common_path.resolve() != Path(git_dir).resolve()
    except OSError:
        return False


def _merge_blocker(root: Path, branch: str, remote_ref: str, timeout: float) -> str:
    if _linked_worktree(root, timeout):
        return "worktree"
    current = _git_text(root, ["symbolic-ref", "--short", "HEAD"], timeout)
    if current != branch:
        return "branch-mismatch"
    if _merge_in_progress(root, timeout):
        return "merge-in-progress"
    status = _git_text(root, ["status", "--porcelain", "-uno"], timeout)
    if status is None:
        return "status-failed"
    if status.strip():
        return "dirty"
    try:
        proc = run_git(["merge-base", "--is-ancestor", "HEAD", remote_ref], root, timeout)
    except (OSError, subprocess.SubprocessError):
        return "not-ancestor"
    return "" if proc.returncode == 0 else "not-ancestor"


def _record_fetch_failure(root: Path, result: dict, reason: str, error: str = "") -> dict:
    state = load_state(root)
    state.update({"schema": SCHEMA_STATE, "attempted_at": now_iso(), "reason": reason,
                  "fetch_error": error,
                  "remote": result["remote"], "branch": result["branch"]})
    save_state(root, state)
    result.update(ok=False, reason=reason, skipped=False, last_reason=reason,
                  attempted_at=state["attempted_at"], last_ok_at=str(state.get("last_ok_at") or ""),
                  fetch_error=error, last_error=error)
    return result


def _record_fetch_ok(root: Path, remote: str, branch: str) -> None:
    state = load_state(root)
    stamp = now_iso()
    state.update({"schema": SCHEMA_STATE, "attempted_at": stamp, "last_ok_at": stamp,
                  "reason": "", "fetch_error": "", "remote": remote, "branch": branch})
    save_state(root, state)


# 完整 sha：SHA-1 40 位、SHA-256 64 位。ls-remote 输出解析出别的形态不认。
_SHA_FULL = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$", re.I)


def _remote_head_sha(root: Path, remote: str, branch: str, timeout: float) -> str:
    """只读问远端分支的完整 sha；`ls-remote` 不写本地任何文件。取不到返回空串。"""
    ref = f"refs/heads/{branch}"
    text = _git_text(root, ["ls-remote", "--heads", remote, ref], timeout)
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == ref and _SHA_FULL.match(parts[0]):
            return parts[0].lower()
    return ""


def _remote_sha_reachable(root: Path, remote_sha: str, local_sha: str, timeout: float) -> bool:
    """远端 sha 是否可从本地 HEAD 到达（即本地不落后）。

    `merge-base --is-ancestor` 退出码 0 = 远端是本地 HEAD 的祖先；1 = 不是祖先，本地落后或
    分叉。本地没有该对象（远端有新提交、上次 fetch 后再没取回）、git 起不来或其它退出码都
    算拿不准，返回 False：宁可多提示一次更新，也不静默把仍在的落后提示清掉。
    """
    try:
        proc = run_git(["merge-base", "--is-ancestor", remote_sha, local_sha], root, timeout)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _probe_on_denied(root: Path, result: dict, *, remote: str, branch: str,
                     timeout: float, fetch_error: str) -> dict:
    """fetch 被权限拒绝时的只读探测：`ls-remote` 拿远端 sha，判它是否从本地 HEAD 可达。

    不用本地远端跟踪 ref 判定：它只记上次 fetch 时的远端位置。远端没动而本地 HEAD 落后时，
    跟踪 ref 等于远端 sha，但本地仍落后（先正常 `--check` 一次、再遇到权限拒绝就是这个
    形态），拿它判会把仍成立的更新提示清掉。可达性看 HEAD：远端是 HEAD 的祖先才不提示。

    `ls-remote` 失败或解析不出 sha 时不猜，按 `permission-denied` 记这次失败。

    成功时把本次核对记为成功（`_record_fetch_ok`），结论只有「远端有没有本地 HEAD 未包含
    的提交」一项：落后数、领先数与改动面都要把提交取回本地才算得出，这里一律未知。
    """
    remote_sha = _remote_head_sha(root, remote, branch, timeout)
    local_sha = _git_text(root, ["rev-parse", "HEAD"], timeout)
    if not remote_sha or not local_sha:
        return _record_fetch_failure(root, result, "permission-denied", fetch_error)
    update_available = not _remote_sha_reachable(root, remote_sha, local_sha, timeout)
    _record_fetch_ok(root, remote, branch)
    state = load_state(root)
    result.update(
        ok=True, reason="", skipped=False,
        degraded="permission-denied", degraded_error=fetch_error,
        update_available=update_available,
        behind="unknown" if update_available else 0,
        ahead="unknown",
        surface={key: 0 for key in SURFACE_KEYS},
        surface_known=False,
        remote_rev=remote_sha[:7],
        local_rev=local_sha[:7],
        last_ok_at=str(state.get("last_ok_at") or ""),
        attempted_at=str(state.get("attempted_at") or ""),
        last_reason="", last_error="", fetch_error="",
    )
    return result


# ---------------------------------------------------------------- 人读输出

FETCH_REASONS = {
    "timeout": "fetch 超时",
    "network": "网络不通",
    "permission-denied": "没有写权限（git 被沙箱或文件权限拒绝）",
    "no-remote": "没有配置的远端",
    "not-a-repo": "不是 git 检出",
    "lock": "git 被锁",
    "offline": "部署声明离线",
    "disabled": "同步已关闭",
    "recent-failure": "10 分钟内的失败还在缓存里",
}

MERGE_REASONS = {
    "worktree": "当前检出是 linked worktree",
    "branch-mismatch": "当前分支与配置分支不一致",
    "not-ancestor": "HEAD 不是远端分支的祖先",
    "dirty": "工作区有未提交改动",
    "merge-in-progress": "有进行中的 merge/rebase/cherry-pick",
    "auto-merge-off": "自动合并已关闭",
    "same-repo": "同步源与归属仓不同源，只拉不合并",
    "identity-unresolved": "归属仓解析不到，只拉不合并",
    "not-ff": "ff-only 合并失败",
    "status-failed": "读不出工作区状态",
    "timeout": "合并超时",
}


def fetch_reason_text(reason: str) -> str:
    reason = str(reason or "")
    if reason in FETCH_REASONS:
        return FETCH_REASONS[reason]
    if reason.startswith("exit-"):
        return f"fetch 退出码 {reason[5:]}"
    return reason or "未知原因"


def merge_reason_text(reason: str) -> str:
    return MERGE_REASONS.get(str(reason or ""), str(reason or "未合并"))


def render_show(result: dict) -> str:
    source = "配置：.local/settings.json" if result.get("config") == "file" \
        else "配置：默认值（.local/settings.json 缺失或读不出）"
    if result.get("config_error"):
        source += f"；{result['config_error']}"
    lines = [f"知识库同步（{source}）"]
    if result.get("offline"):
        lines.append("  同步状态  离线（deployment.yaml 声明 sync.mode: offline）")
    elif not result.get("enabled", True):
        lines.append("  同步状态  已关闭（sync.enabled = false）")
    else:
        lines.append("  同步状态  可同步")
    yesno = {True: "是", False: "否", None: "未知"}
    identity_remote = str(result.get("identity_remote") or DEFAULT_REMOTE)
    identity_name = identity_remote if result.get("identity_explicit") \
        else f"{identity_remote}（默认）"
    identity_url = result.get("identity_url") or "URL 取不到"
    resolved = "是" if result.get("identity_resolved") else "否"
    same = yesno.get(result.get("same_repo"), "未知")
    lines.append(f"  远端      {result['remote']}/{result['branch']}")
    lines.append(f"  归属仓    {identity_name}（{identity_url}）"
                 f"· 解析：{resolved} · 同源：{same}")
    lines.append(f"  本机 HEAD {result['local_rev']}")
    remote_ref = f"{result['remote']}/{result['branch']}"
    if result.get("remote_rev"):
        lines.append(f"  {remote_ref} {result['remote_rev']}"
                     f"（落后 {result['behind']}，领先 {result['ahead']}）")
        counts = result.get("surface") or {}
        changed = "、".join(f"{key} {counts[key]}" for key in SURFACE_KEYS if counts.get(key))
        if changed:
            lines.append(f"  改动面    {changed}")
    else:
        lines.append(f"  {remote_ref} 本机没有这个 ref（先跑 --sync）")
    last_ok = result.get("last_ok_at") or "从未"
    lines.append(f"  上次核对  {last_ok}")
    attempted = result.get("attempted_at") or ""
    last_reason = result.get("last_reason") or ""
    if attempted and last_reason:
        lines.append(f"  上次失败  {fetch_reason_text(last_reason)}（{attempted}）")
        if result.get("last_error"):
            lines.append(f"  git 原始输出  {result['last_error']}")
    return "\n".join(lines)


def render_sync(result: dict) -> str:
    if result.get("offline"):
        return "deployment.yaml 声明 sync.mode: offline，未联网。"
    if result.get("reason") == "disabled":
        return "sync.enabled 为 false，未联网。"
    if result.get("skipped"):
        text = (f"距上次失败不足 10 分钟，跳过本次 fetch"
                f"（上次：{fetch_reason_text(result.get('reason'))}）。")
        if result.get("fetch_error"):
            text += f"\n  git 原始输出：{result['fetch_error']}"
        return text + "\n  要立即重试：在同一条命令上加 --force"
    if result.get("reason") == "not-a-repo":
        return "不是 git 检出，未联网。"
    if not result.get("ok"):
        text = (f"同步未完成（{fetch_reason_text(result.get('reason'))}）："
                f"本机按 {result.get('local_rev')} 诊断。")
        if result.get("fetch_error"):
            text += f"\n  git 原始输出：{result['fetch_error']}"
        return text
    if result.get("degraded"):
        remote_ref = f"{result['remote']}/{result['branch']}"
        head = f"fetch 失败：{fetch_reason_text(result['degraded'])}；改用只读探测："
        if result.get("update_available"):
            lines = [head + f"{remote_ref} 有新提交（{result.get('remote_rev')}），"
                            f"落后数与改动面未知。",
                     "恢复写权限后跑 --sync 取回提交。"]
        else:
            lines = [head + f"{remote_ref} 没有新提交（{result.get('remote_rev')}），"
                            f"领先数与改动面未知。"]
        if result.get("degraded_error"):
            lines.append(f"  git 原始输出：{result['degraded_error']}")
        return "\n".join(lines)
    remote_ref = f"{result['remote']}/{result['branch']}"
    lines = []
    if result.get("merge") == "ff-only":
        lines.append(f"已快进合并到 {result['local_rev']}"
                     f"（原 {result.get('local_rev_before')}，"
                     f"落后 {result.get('behind_before')} 个提交）。")
    elif isinstance(result.get("behind"), int) and result["behind"] > 0:
        lines.append(f"已 fetch {remote_ref} {result.get('remote_rev')}"
                     f"（本机落后 {result['behind']} 个提交）。")
        # fetch-only（--sync / --check）时 reason 为空：不写成「未合并（未合并）」。
        if result.get("reason"):
            lines.append(f"未合并（{merge_reason_text(result['reason'])}）。")
        else:
            lines.append("未合并。")
    else:
        lines.append(f"知识库已是 {remote_ref} {result.get('remote_rev')}。")
    if result.get("identity_explicit") and not result.get("identity_resolved"):
        lines.append("归属仓解析不到；把 settings 的 identity.remote 改成本机已有的远端。")
    elif result.get("same_repo") is False:
        lines.append("同步源与归属仓不同源；请核对 sync.remote 或归属仓。")
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI

def _positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"需要一个正数：{text}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError(f"需要一个正数：{text}")
    return value


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="知识库读侧同步：fetch / 条件合并 / 只读状态")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--show", action="store_const", const="show", dest="mode",
                      help="只读，不联网（默认）")
    mode.add_argument("--sync", action="store_const", const="sync", dest="mode",
                      help="fetch 远端分支")
    mode.add_argument("--check", action="store_const", const="check", dest="mode",
                      help="只 fetch、不合并；不看 sync.enabled（后台提醒检查用）")
    mode.add_argument("--merge", action="store_const", const="merge", dest="mode",
                      help="fetch 后按条件试 ff-only")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--force", action="store_true",
                    help="跳过失败缓存立即重试（手动路径；也不看 sync.enabled）")
    ap.add_argument("--timeout", type=_positive_float, default=DEFAULT_TIMEOUT,
                    help=f"单条 git 命令的超时秒数（默认 {DEFAULT_TIMEOUT:g}）")
    ap.add_argument("--root", default=None, help="仓库根（默认脚本上一级）")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    if not root.is_dir():
        print(f"kb_sync: 目录不存在 {root}", file=sys.stderr)
        return 2
    mode = args.mode or "show"
    if mode == "show":
        settings, config, config_error = load_settings(root)
        sync_cfg = settings["sync"]
        result = local_snapshot(root, sync_cfg["remote"], sync_cfg["branch"],
                                timeout=args.timeout, config=config,
                                config_error=config_error, enabled=sync_cfg["enabled"],
                                identity=settings.get("identity"))
    else:
        result = sync(root, do_fetch=True, do_merge=(mode == "merge"),
                      ignore_enabled=(mode == "check"), timeout=args.timeout,
                      force=args.force, probe_on_denied=(mode == "check"))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_show(result) if mode == "show" else render_sync(result))
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio

    pin_utf8_stdio()
    sys.exit(main())
