#!/usr/bin/env python3
"""kb_sync.py —— 知识库读侧的同步入口（fetch / 条件合并 / 只读状态）。

诊断读的是本机检出的 `knowledge/`，而它可能落后上游几个提交。开单前同步一次，能把
候选集与 case 内容拉到较新的版本；是否合并另判，因为合并会改当前检出的 HEAD。

配置在主检出的 `.local/settings.json`（schema `ascend-sleuth-settings/1`，不进 git）：

    {"schema": "ascend-sleuth-settings/1",
     "sync": {"remote": "origin", "branch": "main", "enabled": true, "auto_merge": true},
     "target": {...}}

配置文件缺失或读不出时用默认值（远端 origin、分支取当前分支上游（取不到则 main）、同步开），
结果里 `config: "default"`。失败结果缓存在 `.local/kb-sync-state.json`：自动同步在 10 分钟内
不重试，避免每次开单都等满超时。手动同步加 `--force` 跳过窗口立即重试（面板「立即同步」走这条），
否则刚失败过的网络在 10 分钟内点几次都只会拿回同一份缓存。

自动合并只在这些条件同时成立时发生：当前分支 = 配置 `branch`、HEAD 是远端分支的祖先、
`git status --porcelain -uno` 为空、无进行中 merge / rebase / cherry-pick。worktree 与
detached HEAD 不自动合并——合并会改当前检出的 HEAD，而 worktree 可能正被另一单使用。
配置远端与 origin 不同源时同样只 fetch、不合并（reason `same-repo`）：合并会把另一个仓的
提交带进当前检出。

用法：
  python3 scripts/kb_sync.py --show          # 只读，不联网：配置、HEAD、本地远端 ref、上次核对
  python3 scripts/kb_sync.py --sync          # fetch；不合并
  python3 scripts/kb_sync.py --merge         # fetch，条件满足时试 ff-only
  python3 scripts/kb_sync.py --merge --force # 跳过失败缓存立即重试（手动同步用）
  python3 scripts/kb_sync.py --show --json   # 所有子命令都可加 --json
  python3 scripts/kb_sync.py --sync --timeout 3 --root <检出>

结果里的稳定取值（文档与测试可直接断言）：
  ok       true / false
  reason   "" | timeout | network | no-remote | not-a-repo | lock | exit-<n> | offline |
           disabled | dirty | branch-mismatch | not-ancestor | merge-in-progress |
           auto-merge-off | not-ff | same-repo
  fetch_error  本次 fetch 失败时 git 原始输出的末行（已抹掉 URL 里的凭据）；成功与 --show 时为空
  last_error   --show 时上次失败留下的同一条原文；没有失败记录时为空
  merge    ff-only | none
  config   file | default
  enabled  true / false（settings 的 sync.enabled；--show 也照实给）
  offline  true / false（deployment.yaml 声明 sync.mode: offline）

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

from exec_log_path import log_lock, main_checkout  # noqa: E402

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
SURFACE_KEYS = ("knowledge", "routing", "reference", "methodology", "other")


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
                 "enabled": True, "auto_merge": True},
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


def normalize_sync(raw) -> dict:
    """`sync` 段 → 四个字段。缺项与类型不对的项取默认值。"""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "remote": str(raw.get("remote") or DEFAULT_REMOTE).strip() or DEFAULT_REMOTE,
        "branch": str(raw.get("branch") or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH,
        "enabled": _as_bool(raw.get("enabled"), True),
        "auto_merge": _as_bool(raw.get("auto_merge"), True),
    }


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
    data["sync"] = normalize_sync(raw.get("sync"))
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
    """原子写 settings；`expect_sha` 给了就做文件字节 CAS。返回新 sha256。"""
    path = settings_path(root)
    data = dict(data)
    data["schema"] = SCHEMA_SETTINGS
    data["sync"] = normalize_sync(data.get("sync"))
    data["target"] = normalize_target(data.get("target"))
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with log_lock(path) as locked:
        if not locked:
            raise SettingsError(f"配置写锁不可用：{path}")
        actual = settings_sha256(root)
        if expect_sha is not None and actual != expect_sha:
            raise SettingsCasConflict(expect_sha, actual or "")
        written_text = _write_json(path, data)
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


def fetch_failure_reason(proc) -> str:
    """失败原因归类：ref 锁 → network → exit-<码>。

    凭据类（401 / 403 / 认不出用户名）不归到 network：带读者往网络与代理上查会查错方向。
    """
    text = (proc.stderr or "") + "\n" + (proc.stdout or "")
    if _LOCK_ERROR.search(text):
        return "lock"
    code = proc.returncode if isinstance(proc.returncode, int) else 1
    if _AUTH_ERROR.search(text):
        return f"exit-{code}"
    if _NETWORK_ERROR.search(text):
        return "network"
    return f"exit-{code}"


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


def same_repo(root: Path, remote: str, timeout: float):
    """配置远端与 origin 的 host+path 是否一致；取不到返回 None。"""
    remote_url = _remote_url(root, remote, timeout)
    origin_url = _remote_url(root, "origin", timeout)
    left, right = _url_key(remote_url), _url_key(origin_url)
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
                   config: str = "file", config_error: str = "", enabled: bool = True) -> dict:
    """只读本机 git 状态（不联网），填 local_rev / 远端 ref / 落后数 / 改动面。

    `enabled` 由调用方从 settings 的 sync 段带进来，`offline` 就地读 deployment.yaml；
    两者只读本地文件，`--show` 因此能给出真实状态而不联网。关闭或离线时 `ok: false`
    并写对应 reason，但仍照常算落后数与改动面（面板要显示"落后多少、为什么没同步"）。
    """
    root = Path(root)
    result = _empty_base(remote, branch, config, config_error)
    result["enabled"] = bool(enabled)
    result["offline"] = deployment_sync_mode(root) == "offline"

    def finish(res: dict) -> dict:
        if res["offline"]:
            res.update(ok=False, reason="offline", merge="none")
        elif not res["enabled"]:
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
    result["same_repo"] = same_repo(root, remote, timeout) if remote else None
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
         force: bool = False) -> dict:
    """fetch（可选条件 ff-only 合并）→ 结果映射。任何失败都返回结果，不抛给调用方。

    `force=True` 跳过失败缓存：手动同步要能立刻重试，否则刚失败过的网络在 10 分钟内
    点几次都只会拿回同一份缓存。自动同步（建单、续接漂移检查）不加这个参数。
    """
    root = Path(root)
    settings, config, config_error = load_settings(root)
    sync_cfg = settings["sync"]
    remote, branch = sync_cfg["remote"], sync_cfg["branch"]
    result = local_snapshot(root, remote, branch, timeout=timeout, config=config,
                            config_error=config_error, enabled=sync_cfg["enabled"])

    if result["offline"] or not result["enabled"]:
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

    try:
        proc = run_git(["fetch", "--no-tags", remote, branch], root, timeout)
    except subprocess.TimeoutExpired as exc:
        return _record_fetch_failure(root, result, "timeout", timeout_error_of(exc))
    except (OSError, subprocess.SubprocessError):
        return _record_fetch_failure(root, result, "exit-1")
    if proc.returncode != 0:
        return _record_fetch_failure(root, result,
                                     fetch_failure_reason(proc), fetch_error_of(proc))

    _record_fetch_ok(root, remote, branch)
    fresh = local_snapshot(root, remote, branch, timeout=timeout, config=config,
                           config_error=config_error, enabled=sync_cfg["enabled"])
    result.update(fresh)
    result.update(ok=True, reason="", skipped=False, offline=False,
                  local_rev_before=fresh.get("local_rev_before", "unknown"),
                  behind_before=fresh.get("behind_before", "unknown"))

    if not do_merge:
        return result
    # 配置远端与 origin 不同源时只拉不合并：合并会把另一个仓的提交带进当前检出。
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
                           config_error=config_error, enabled=sync_cfg["enabled"])
    before_rev, before_behind = result["local_rev_before"], result["behind_before"]
    result.update(after)
    result.update(ok=True, reason="", merge="ff-only",
                  local_rev_before=before_rev, behind_before=before_behind)
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


# ---------------------------------------------------------------- 人读输出

FETCH_REASONS = {
    "timeout": "fetch 超时",
    "network": "网络不通",
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
    "same-repo": "配置远端与 origin 不同源，只拉不合并",
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
    same = {True: "是", False: "否", None: "未知"}.get(result.get("same_repo"), "未知")
    lines.append(f"  远端      {result['remote']}/{result['branch']}（与 origin 同源：{same}）")
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
    remote_ref = f"{result['remote']}/{result['branch']}"
    lines = []
    if result.get("merge") == "ff-only":
        lines.append(f"已快进合并到 {result['local_rev']}"
                     f"（原 {result.get('local_rev_before')}，"
                     f"落后 {result.get('behind_before')} 个提交）。")
    elif isinstance(result.get("behind"), int) and result["behind"] > 0:
        lines.append(f"已 fetch {remote_ref} {result.get('remote_rev')}"
                     f"（本机落后 {result['behind']} 个提交）。")
        lines.append(f"未合并（{merge_reason_text(result.get('reason'))}）。")
    else:
        lines.append(f"知识库已是 {remote_ref} {result.get('remote_rev')}。")
    if result.get("same_repo") is False:
        lines.append("注意：配置远端与 origin 不同源；请核对 sync.remote。")
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
    mode.add_argument("--merge", action="store_const", const="merge", dest="mode",
                      help="fetch 后按条件试 ff-only")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--force", action="store_true",
                    help="跳过失败缓存立即重试（手动同步用；自动同步仍按 10 分钟窗口）")
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
                                config_error=config_error, enabled=sync_cfg["enabled"])
    else:
        result = sync(root, do_fetch=True, do_merge=(mode == "merge"), timeout=args.timeout,
                      force=args.force)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_show(result) if mode == "show" else render_sync(result))
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio

    pin_utf8_stdio()
    sys.exit(main())
