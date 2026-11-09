#!/usr/bin/env python3
# pr_status.py —— 提 PR 的目标（target）与每份草稿的 PR 台账（prs），带平台适配器派发
#
# 为什么需要它：队列停在「已提 PR · 合入未确认」之后，界面要回答两个问题——「提到哪」
# 与「合入没有」——而这两件事实都有多个写侧（agent 开完 PR 写台账、人手动确认、平台查询）。
# 让每个写侧各自手编 JSON 会漂移：字段名不一致、状态被推断、丢 checked_at。所以台账只有
# 这一个读写入口：原子写 + 文件字节 sha256 CAS，agent 不手编 JSON（设计 5.6、5.7）。
#
# 它做什么：
#   1. 台账读写（`<inbox>/.groom/pr-state.json`，共享 inbox，同一克隆的 worktree 共用）；
#   2. 列远端并识别平台（`--list-targets`，不探测网络）；
#   3. 写目标与 PR 记录（`--set-target` / `--set` / `--mark`）；删掉一条已关闭的
#      PR 记录（`--forget`，只有 `closed` 可以删，撤销沉淀时用）；
#   4. 按 PR URL 的 host 查状态（`--check` / `--check-all`）。状态只由平台查询或人手确认
#      更新，不由「分支是否存在」「commit 是否在 main」推断（设计 5.6）。
#
# 平台适配两层（加平台不改本文件，设计 5.8）：
#   - 声明式：`scripts/platforms/<id>.yaml`，REST + token；本文件用 urllib 执行；
#   - 可执行：`scripts/platforms/<id>.py`，暴露 ID/NAME/HOSTS/REQUIRES/check()/create_hint()/
#     可选 selftest()。本文件用 importlib 加载，**import 时不跑子进程**——只有 check() 跑 CLI。
#
# 输出纪律：每条命令都往 stdout 写一份 UTF-8 JSON（--json-lines 除外；末尾一个换行）。
# 业务失败（无适配器、无 token、网络错、CAS 冲突）`ok:false` 且退出 0（调用方只看 ok）；
# 参数错误退出 2。**任何路径都不打印 token**：HTTP 错误信息里的 query 值一律打码。
#
# --json-lines 契约（只给 --check-all 用，与 --json 互斥；默认输出不变）：
#   1. 每查完一条立刻打一行并 flush：
#      {"type":"row","draft":…,"ok":bool,"state":…,"checked_at":…,"error"?:<code>,"message"?:<失败原文>}
#   2. 全部查完并落盘后打最后一行，与 --json 的最终载荷同形、只多一个 type：
#      {"type":"done","ok":bool,"checked":[…],"ledger"?:{…},"sha256"?:"…","error"?:{"code","message"},
#       "write_failed"?:true}
#      成功时 sha256 是字符串；E_CHECK_PARTIAL / E_CAS / E_LEDGER 都在 error 里给 code 与 message；
#      write_failed 只在落盘被系统拒绝（E_LEDGER）时出现，面板据此给可复制指令。
#   3. row 的行序是查询完成序；done 里 checked[] 仍是台账键序（与 --json 相同），面板以 done 为准。
#   4. 未预期异常（E_INTERNAL）与参数错误（E_ARGS）不在 done 行里。E_ARGS 出现在任何 row 之前；
#      E_INTERNAL 可能出现在已打出的 row 之后。两者都是**一行 compact JSON**（不含 type，退出码不变），
#      读端按「最后一段行首 { 到末尾」整体解析一次即可还原 error.code / message。
#
# 用法：
#   python3 scripts/pr_status.py --root <repo> --json
#   python3 scripts/pr_status.py --root <repo> --list-targets
#   python3 scripts/pr_status.py --root <repo> --set-target --remote origin --base main
#   python3 scripts/pr_status.py --root <repo> --set-identity --remote team
#   python3 scripts/pr_status.py --root <repo> --set --draft <key> --platform gitcode \
#       --repo owner/repo --number 418 --url <url> [--remote origin]
#   python3 scripts/pr_status.py --root <repo> --mark --draft <key> --state merged
#   python3 scripts/pr_status.py --root <repo> --forget --draft <key>
#   python3 scripts/pr_status.py --root <repo> --check --draft <key>
#   python3 scripts/pr_status.py --root <repo> --check-all
#   python3 scripts/pr_status.py --root <repo> --list-platforms
#   python3 scripts/pr_status.py --root <repo> --selftest gitcode
#
# 退出码：0 正常（含业务失败）；2 参数错误；1 未预期异常。

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

import kb_sync
from _stdio import pin_utf8_stdio
from exec_log_path import log_lock, write_refused_message
from groom_common import (
    atomic_write_text, dump_json, load_json, now_iso, run_git, shared_inbox,
)

SCHEMA = "groom-pr-state/v1"
LEDGER_REL = Path(".groom") / "pr-state.json"
PLATFORMS_DIR = Path(__file__).resolve().parent / "platforms"
STATES = ("open", "merged", "closed", "unknown")
#: 只有这两个状态需要去平台查；merged/closed 是终态，不重复查。
CHECKABLE = ("open", "unknown")

#: --check-all 查询阶段的并发度。取 4 而不是更大：一个批次是 N 次独立的平台请求，
#: 并发太高会撞平台速率限制，也把本机连接与请求日志放大到难排查；4 路已能把 N 次
#: 请求压到 N/4 波。落盘仍是全部查完后的一次 CAS 写，不并发写台账。
CHECK_ALL_WORKERS = 4

DEFAULT_BASE = "main"
HTTP_TIMEOUT_S = 10

# 未预期异常统一折成 JSON，调用方不必解析 traceback。
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ARGS = 2


class LedgerError(RuntimeError):
    """台账读不出来（坏 JSON / 不是对象）。调用方折成 E_LEDGER。"""


class CasConflict(LedgerError):
    """写前发现文件字节已变（别的进程写过）。调用方折成 E_CAS，不覆盖。"""

    def __init__(self, expected: str, actual: str):
        super().__init__(f"台账已被改动：expect {expected or '（文件不存在）'}，实际 {actual or '（文件不存在）'}")
        self.expected = expected
        self.actual = actual


class PrRecordError(RuntimeError):
    """按请求改动一份 PR 记录被拒（记录不存在 / 状态不是 closed）。带协议码。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- 台账：路径 / 读 / 原子写 + CAS

def ledger_path(root) -> Path:
    return Path(shared_inbox(Path(root))) / LEDGER_REL


def empty_ledger() -> dict:
    return {"schema": SCHEMA, "updated_at": "", "target": None, "prs": {}}


def file_sha256(path: Path):
    """文件字节的 sha256（不归一换行：CAS 比的是磁盘上的那一份）。文件不存在返回 None。"""
    import hashlib
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LedgerError(f"读台账失败：{exc}") from exc


def ledger_sha256(root) -> str:
    return file_sha256(ledger_path(root))


def load_ledger(root) -> dict:
    """读台账。不存在返回空台账（首次使用不是错误）；坏文件抛 LedgerError。"""
    path = ledger_path(root)
    if not path.exists():
        return empty_ledger()
    try:
        data = load_json(path)
    except Exception as exc:
        raise LedgerError(f"台账不是合法 JSON（{path}）：{exc}") from exc
    if not isinstance(data, dict):
        raise LedgerError(f"台账顶层不是对象（{path}）")
    data.setdefault("schema", SCHEMA)
    data.setdefault("updated_at", "")
    data.setdefault("target", None)
    prs = data.get("prs")
    if prs is None:
        data["prs"] = {}
    elif not isinstance(prs, dict):
        raise LedgerError("台账 `prs` 不是对象")
    return data


def _load_ledger_soft(root) -> dict:
    """只读场景（列目标）用：坏台账不阻断远端列表，退化成空台账。"""
    try:
        return load_ledger(root)
    except LedgerError:
        return empty_ledger()


def save_ledger(root, data: dict, expect_sha=None) -> str:
    """原子写台账，并做文件字节 sha256 CAS。

    CAS 语义：`expect_sha` 给了就必须等于写前读到的那一版字节哈希，否则抛 CasConflict
    （两个 agent 同时写台账时，后写者不能静默覆盖先写者）。写后重新读一遍字节校验，
    确认落盘的就是本次序列化的内容。返回新文件哈希，供下一次 CAS 用。

    文件层失败（开锁文件、建目录、替换台账被系统拒绝）一律折成 LedgerError：
    调用方按 E_LEDGER 显示路径与原因，不落成 E_INTERNAL 的裸异常。
    """
    import hashlib
    path = ledger_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data["schema"] = SCHEMA
        data["updated_at"] = now_iso()
        text = dump_json(data)
        with log_lock(path) as locked:
            if not locked:
                raise LedgerError(f"台账写锁不可用：{path}")
            actual = file_sha256(path)
            if expect_sha is not None and actual != expect_sha:
                raise CasConflict(expect_sha, actual or "")
            atomic_write_text(path, text)
            written = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise LedgerError(write_refused_message("台账", path, exc)) from exc
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if written != expected:
        raise LedgerError("台账写后校验失败（磁盘内容与本次序列化不一致）")
    return written


def forget_pr(root, key: str, expect_sha=None) -> dict:
    """删掉一份草稿的 PR 台账记录；返回被删掉的记录与新文件哈希。

    只有 `state: closed` 的记录可以删：PR 关闭后这次提交流程已经结束，本地再留着它只会让
    队列把一条结束了的 PR 当现行状态显示。`open` / `unknown` 还可能变成合入，`merged` 已有
    knowledge/ 里的落点——删掉记录会让队列与审计失去依据，都拒绝。

    写前按文件字节 sha256 做 CAS（`expect_sha` 显式给的时候用调用方的令牌，否则用本次读到
    的那一版），两个写者并发时后写者不会静默覆盖先写者。记录不存在抛 `PrRecordError`
    （E_NOT_FOUND），记录不是对象抛 `PrRecordError`（E_BAD_RECORD），状态不是 closed 抛
    `PrRecordError`（E_PR_ACTIVE），读写失败照旧抛 `LedgerError` / `CasConflict`。
    """
    key = str(key or "").strip()
    if not key:
        raise PrRecordError("E_ARGS", "--forget 需要 --draft")
    before = ledger_sha256(root)
    data = load_ledger(root)
    if key not in data["prs"]:
        raise PrRecordError("E_NOT_FOUND", f"台账里没有这份草稿的 PR 记录：{key}")
    pr = data["prs"].get(key)
    if not isinstance(pr, dict):
        raise PrRecordError(
            "E_BAD_RECORD",
            f"台账里这份草稿的记录不是对象（台账可能被手改坏了）：{key}。先修台账再清记录。")
    state = str(pr.get("state") or "unknown").strip().lower()
    if state not in STATES:
        state = "unknown"
    if state != "closed":
        raise PrRecordError(
            "E_PR_ACTIVE",
            f"这份草稿的 PR 是 {state}，不能删记录：只有已关闭（closed）的 PR 才不再拦撤销。"
            "PR 仍是外部事实，先在平台上处理它；状态还没确认就先跑 --check 确认。")
    del data["prs"][key]
    digest = save_ledger(root, data, expect_sha=before if expect_sha is None else expect_sha)
    return {"draft": key, "pr": pr, "sha256": digest}


# ---------------------------------------------------------------- 远端 URL / 平台适配器

def parse_remote_url(url) -> dict:
    """远端 URL → {scheme, host, repo}。支持 https/ssh:// 与 scp 风格 `git@host:o/r.git`。

    远端用 SSH 还是 HTTPS 都要能识别 host（设计 5.7 的边界）；本地路径/纯镜像返回空 host，
    由调用方按「没有适配器」处理。
    """
    text = str(url or "").strip()
    if not text:
        return {"scheme": "", "host": "", "repo": "", "path": ""}
    scheme, host, path = "", "", ""
    match = re.match(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<rest>.+)$", text)
    if match:
        scheme = match.group("scheme").lower()
        rest = match.group("rest")
        hostpart, _, raw_path = rest.partition("/")
        host = hostpart.rsplit("@", 1)[-1]
        if host.startswith("["):            # IPv6
            host = host.split("]")[0].lstrip("[")
        elif ":" in host:                    # host:port
            host = host.rsplit(":", 1)[0]
        path = raw_path
    elif "@" in text and ":" in text.split("@", 1)[1]:
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
    parts = [p for p in path.split("/") if p]
    return {"scheme": scheme, "host": host.strip().lower(), "repo": "/".join(parts),
            "path": path}


def _split_repo(repo: str):
    """`owner/repo` → (owner, repo)；子组路径归到第一段后，避免占位符留下空串。"""
    parts = [p for p in str(repo or "").split("/") if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], "/".join(parts[1:])


def _subst(text, adapter: dict, repo: str, number) -> str:
    """替换适配器清单里的占位符：{owner} {repo} {number} {env:NAME}，以及 {TOKEN_ENV}。

    为什么同时支持两种 token 写法：契约规定 `{env:NAME}`，而设计稿与示例清单写的是
    `{GITCODE_TOKEN}`。两者读起来一样，只支持一种就会让照设计稿写的新适配器拿不到值。
    未知占位符原样保留（能看见「哪里没替换」，而不是变成空串）。
    """
    owner, name = _split_repo(repo)

    def repl(match):
        key = match.group(1)
        if key == "owner":
            return owner
        if key == "repo":
            return name
        if key == "number":
            return "" if number is None else str(number)
        if key.startswith("env:"):
            return os.environ.get(key[4:], "")
        if key == (adapter.get("auth_env") or ""):
            return os.environ.get(key, "")
        if key in os.environ:
            return os.environ[key]
        return match.group(0)

    return re.sub(r"\{([A-Za-z0-9_:]+)\}", repl, str(text))


def _redact_url(url: str) -> str:
    """错误信息里的 URL：query 值全部打码（token 常在 query 里）。"""
    try:
        parts = urllib.parse.urlsplit(url)
        if parts.query:
            pairs = [(urllib.parse.quote(k), "***")
                     for k, _ in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)]
            query = "&".join(f"{key}={value}" for key, value in pairs)
            return urllib.parse.urlunsplit(
                (parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    except Exception:
        pass
    return url


def _norm_state(value) -> str:
    state = str(value or "").strip().lower()
    return state if state in STATES else "unknown"


def _json_path(data, expr):
    """`$.a.b` / `a.b` 取值；路径断开返回 None（不抛）。"""
    if not isinstance(expr, str):
        return None
    path = expr[2:] if expr.startswith("$.") else ("$" if expr == "$" else expr.lstrip("$."))
    if path == "$" or path == "":
        return data
    current = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _json_set(data, expr, value) -> None:
    """按同一种点路径写值；只给 selftest 造响应，运行时不使用。"""
    path = expr[2:] if expr.startswith("$.") else expr.lstrip("$.")
    current = data
    parts = [p for p in path.split(".") if p]
    for part in parts[:-1]:
        if not isinstance(current.get(part), dict):
            current[part] = {}
        current = current[part]
    if parts:
        current[parts[-1]] = value


def _when_matches(actual, expected) -> bool:
    """normalize 的 when 比较：只支持 true / false / 字符串 / null，不实现表达式语言。"""
    if expected is True:
        return actual is True
    if expected is False:
        return actual is False
    if expected is None:
        return actual is None
    return actual == expected


def _normalize(rules, mapped: dict) -> str:
    fallback = None
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        state = _norm_state(rule.get("state"))
        when = rule.get("when")
        if not when:
            if fallback is None:
                fallback = state
            continue
        if isinstance(when, dict) and all(_when_matches(mapped.get(k), v) for k, v in when.items()):
            return state
    return fallback if fallback is not None else "unknown"


def _manifest_problem(doc: dict) -> str:
    if not isinstance(doc, dict):
        return "清单顶层不是对象"
    if not str(doc.get("id") or "").strip():
        return "缺 id"
    if not str(doc.get("name") or "").strip():
        return "缺 name"
    hosts = doc.get("hosts")
    if not isinstance(hosts, list) or not [h for h in hosts if str(h or "").strip()]:
        return "hosts 不是非空列表"
    check = doc.get("check")
    if not isinstance(check, dict):
        return "缺 check 段"
    if not str(check.get("url") or "").strip():
        return "check 缺 url"
    method = str(check.get("method") or "GET").upper()
    if method not in ("GET", "POST"):
        return f"check.method 不支持：{method}"
    if not isinstance(check.get("map"), dict) or not check.get("map"):
        return "check 缺 map"
    normalize = check.get("normalize")
    if not isinstance(normalize, list) or not normalize:
        return "check 缺 normalize"
    for rule in normalize:
        if not isinstance(rule, dict) or _norm_state(rule.get("state")) == "unknown":
            return "normalize 的 state 不在 open/merged/closed/unknown 里"
    scheme = urllib.parse.urlsplit(str(check.get("url"))).scheme.lower()
    if scheme not in ("http", "https"):
        return f"check.url 只允许 http/https：{scheme or '（无 scheme）'}"
    return ""


def _profile(adapter: dict) -> dict:
    """适配器的人读状态：清单是否完整、依赖与 token 在不在（不做网络探测）。"""
    base = {
        "id": adapter.get("id", ""),
        "name": adapter.get("name", ""),
        "hosts": list(adapter.get("hosts") or []),
        "kind": adapter.get("kind", ""),
        "auth_env": adapter.get("auth_env") or "",
        "requires": list(adapter.get("requires") or []),
        "install_hint": adapter.get("install_hint") or "",
        "broken": bool(adapter.get("broken")),
        "reason": adapter.get("reason") or "",
        "token_ready": False,
        "requires_ok": False,
        "available": False,
    }
    if adapter.get("broken"):
        base["reason"] = "清单损坏：" + (adapter.get("reason") or "未知原因")
        return base
    missing = [cmd for cmd in base["requires"] if shutil.which(cmd) is None]
    base["requires_ok"] = not missing
    base["token_ready"] = not base["auth_env"] or bool(os.environ.get(base["auth_env"]))
    if not base["requires_ok"]:
        base["reason"] = "缺少命令：" + "、".join(missing)
    elif not base["token_ready"]:
        base["reason"] = f"未配置 token 环境变量：{base['auth_env']}"
    base["available"] = base["requires_ok"] and base["token_ready"]
    return base


def _base_adapter(path: Path) -> dict:
    return {"id": path.stem, "name": path.stem, "hosts": [], "kind": "",
            "auth_env": None, "requires": [], "install_hint": "",
            "path": str(path)}


def _load_yaml_adapter(path: Path) -> dict:
    adapter = _base_adapter(path)
    adapter["kind"] = "http"
    try:
        with open(path, encoding="utf-8-sig") as fh:
            doc = yaml.safe_load(fh)
    except Exception as exc:
        adapter.update(broken=True, reason=f"YAML 解析失败：{exc}")
        return adapter
    problem = _manifest_problem(doc)
    if problem:
        adapter.update(broken=True, reason=problem)
        if isinstance(doc, dict):
            adapter["id"] = str(doc.get("id") or path.stem)
            adapter["name"] = str(doc.get("name") or path.stem)
        return adapter
    adapter.update({
        "id": str(doc["id"]),
        "name": str(doc["name"]),
        "hosts": [str(h).strip().lower() for h in doc["hosts"] if str(h).strip()],
        "auth_env": str(doc.get("auth_env") or "") or None,
        "requires": [str(c) for c in (doc.get("requires") or [])],
        "install_hint": str(doc.get("install_hint") or ""),
        "spec": doc,
        "create_hint": str(doc.get("create_hint") or ""),
    })
    return adapter


def _load_py_adapter(path: Path) -> dict:
    adapter = _base_adapter(path)
    adapter["kind"] = "exec"
    module_name = f"_pr_platform_{re.sub(r'[^A-Za-z0-9_]', '_', path.stem)}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            adapter.update(broken=True, reason="无法构造 importlib spec")
            return adapter
        module = importlib.util.module_from_spec(spec)
        # 只加载模块：适配器契约要求 import 时不跑子进程（命令只在 check() 里跑）。
        spec.loader.exec_module(module)
    except Exception as exc:
        adapter.update(broken=True, reason=f"import 失败：{type(exc).__name__}: {exc}")
        return adapter
    hosts = getattr(module, "HOSTS", None)
    problems = []
    if not str(getattr(module, "ID", "") or "").strip():
        problems.append("缺 ID")
    if not str(getattr(module, "NAME", "") or "").strip():
        problems.append("缺 NAME")
    if not isinstance(hosts, list) or not hosts:
        problems.append("HOSTS 不是非空列表")
    if not callable(getattr(module, "check", None)):
        problems.append("缺 check()")
    if problems:
        adapter.update(broken=True, reason="、".join(problems))
        return adapter
    adapter.update({
        "id": str(module.ID),
        "name": str(module.NAME),
        "hosts": [str(h).strip().lower() for h in hosts if str(h).strip()],
        "auth_env": str(getattr(module, "AUTH_ENV", "") or "") or None,
        "requires": [str(c) for c in (getattr(module, "REQUIRES", None) or [])],
        "install_hint": str(getattr(module, "INSTALL_HINT", "") or ""),
        "module": module,
    })
    return adapter


def load_adapters() -> list:
    """读 `platforms/*.yaml` 与 `*.py`。清单坏了不抛：标 broken + reason，列表照出。"""
    base = Path(PLATFORMS_DIR)
    if not base.is_dir():
        return []
    adapters = []
    seen = set()
    for path in sorted(base.iterdir()):
        if path.name.startswith((".", "_")) or not path.is_file():
            continue
        if path.suffix not in (".yaml", ".yml", ".py"):
            continue
        adapter = _load_yaml_adapter(path) if path.suffix in (".yaml", ".yml") \
            else _load_py_adapter(path)
        key = str(adapter.get("id") or path.stem)
        if key in seen:
            continue
        seen.add(key)
        adapters.append(adapter)
    return adapters


def find_adapter(adapters, platform_id):
    for adapter in adapters:
        if adapter.get("id") == platform_id:
            return adapter
    return None


def adapter_for_host(adapters, host):
    host = str(host or "").strip().lower()
    if not host:
        return None
    for adapter in adapters:
        if host in (adapter.get("hosts") or []):
            return adapter
    return None


def adapter_for_url(adapters, url):
    return adapter_for_host(adapters, parse_remote_url(url)["host"])


# ---------------------------------------------------------------- 远端清单与目标推荐

def _git_remotes(root) -> list:
    proc = run_git(["remote", "-v"], cwd=root, check=False)
    if proc.returncode != 0:
        return []
    pairs = []
    seen = set()
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[2] != "(fetch)":
            continue
        name, url = parts[0], parts[1]
        if name in seen:
            continue
        seen.add(name)
        pairs.append((name, url))
    return pairs


def _remote_base(root, name: str) -> str:
    """远端 HEAD 指向的分支名；取不到用 main（设计 5.7：base 不写死 main，但没有信息时兜底）。"""
    proc = run_git(["symbolic-ref", f"refs/remotes/{name}/HEAD"], cwd=root, check=False)
    ref = (proc.stdout or "").strip()
    if proc.returncode == 0 and ref:
        tail = ref.rsplit("/", 1)[-1]
        if tail and tail != "HEAD":
            return tail
    return DEFAULT_BASE


def _upstream_remote(root) -> str:
    proc = run_git(["rev-parse", "--abbrev-ref", "@{u}"], cwd=root, check=False)
    ref = (proc.stdout or "").strip()
    if proc.returncode != 0 or "/" not in ref:
        return ""
    return ref.split("/", 1)[0]


def identity_target(root) -> dict:
    """settings 的归属仓 → `{"remote", "base", "url", "explicit"}`。

    名字缺省为 origin；`base` 是该远端的默认分支（取不到用 main），`url` 在本机没有这个
    远端时为空串。`explicit` 来自 `kb_sync.load_settings` 的内存字段：文件里写没写
    `identity.remote`。
    """
    settings, _source, _problem = kb_sync.load_settings(Path(root))
    identity = settings.get("identity") or {}
    remote = str(identity.get("remote") or kb_sync.DEFAULT_REMOTE).strip()
    url = dict(_git_remotes(root)).get(remote, "") if remote else ""
    return {"remote": remote,
            "base": _remote_base(root, remote) if remote else DEFAULT_BASE,
            "url": url,
            "explicit": bool(identity.get("explicit"))}


def effective_base(root) -> str:
    """写侧的比较基准 ref：提 PR 目标优先，其次归属仓默认分支，最后 origin/main。

    目标未配置时不再一律回到 origin/main：归属仓配成团队中央仓时，写侧（复核、收尾、
    生成物同步）都以它为准。归属仓在本机解析不到才退回 origin/main。
    """
    root = Path(root)
    try:
        target = load_target(root)
    except Exception:
        target = None
    if isinstance(target, dict) and target.get("remote") and target.get("base"):
        return f"{target['remote']}/{target['base']}"
    identity = identity_target(root)
    if identity["remote"] and identity["url"]:
        return f"{identity['remote']}/{identity['base']}"
    return f"{kb_sync.DEFAULT_REMOTE}/{DEFAULT_BASE}"


def _normalize_target(target):
    """与 `kb_sync.normalize_target` 同一份结构（target 已迁到 settings，这里保留旧入口）。"""
    return kb_sync.normalize_target(target)


def _settings_expect_sha(settings_sha, explicit=None):
    """settings 写点的 CAS 令牌：显式令牌优先，否则用读配置那一刻取的文件指纹。

    令牌与配置内容来自同一段窗口（先取 sha 再读配置），写时由 `save_settings` 在
    `log_lock` 内重新读一遍比对：这段窗口里别的写者（例如面板的 `--set-sync`）改过的
    字节会被拦下，不会用这份旧快照覆盖掉对方刚写的 `sync` 段。先取 sha 的代价是变化
    落在「取 sha 之后、读配置之前」时会多报一次冲突——方向安全，重试即可。

    `--set-target` 的 `--expect-sha256` 是**台账**令牌（面板从 `--list-targets` 的
    `sha256` 取），不能拿来当 settings 令牌；那个写点不传 explicit。
    """
    return explicit if explicit is not None else settings_sha


def _settings_sha_or_none(root):
    """读 settings 的文件指纹；文件读不出时返回 None，让调用方走原来的错误路径。

    `load_settings` 对读不出的文件会退回默认值（并给 problem），迁移写回是只读入口的
    顺手动作，不能因为指纹读不出就把列表也弄失败。
    """
    try:
        return kb_sync.settings_sha256(root)
    except kb_sync.SettingsError:
        return None


def load_target(root):
    """读 target：主检出 `.local/settings.json` 优先；没有则从旧台账迁一次。

    迁移写回 settings，旧 `.groom/pr-state.json` 不删——两个界面版本可能同时在用。
    写回带读配置时取的文件指纹：迁移期间配置被别的写者改过就不覆盖（下次再迁）。
    """
    settings_sha = _settings_sha_or_none(root)
    data, _source, _problem = kb_sync.load_settings(Path(root))
    target = kb_sync.normalize_target(data.get("target"))
    if target is not None:
        return target
    legacy = _normalize_target(_load_ledger_soft(root).get("target"))
    if legacy is None:
        return None
    data["target"] = legacy
    try:
        kb_sync.save_settings(Path(root), data, expect_sha=settings_sha)
    except kb_sync.SettingsError:
        pass
    return legacy


def _last_used(ledger: dict, remote_name: str, repo: str, platform: str) -> str:
    """该远端「上次使用」= 台账里最近一条相关 PR 的 created_at。

    PR 台账没有远端字段时按 repo（owner/repo）、再按 platform 兜底；有 `remote` 字段的条目
    只按 remote 匹配——否则同一个 platform 的两个远端会互相冒充「上次使用」。
    """
    prs = [p for p in (ledger.get("prs") or {}).values() if isinstance(p, dict)]
    direct = [str(p.get("created_at") or "") for p in prs
              if str(p.get("remote") or "") == remote_name and p.get("created_at")]
    if direct:
        return max(direct)
    fallback = []
    for pr in prs:
        if pr.get("remote") or not pr.get("created_at"):
            continue
        pr_repo = str(pr.get("repo") or "")
        if repo and pr_repo.lower() == repo.lower():
            fallback.append(str(pr["created_at"]))
        elif not repo and platform and str(pr.get("platform") or "") == platform:
            fallback.append(str(pr["created_at"]))
    return max(fallback) if fallback else ""


def _recommend(root, target, remotes, identity=None) -> dict:
    """推荐顺序：已保存目标（有适配器）→ 归属仓（已解析）→ 分支上游 → 唯一远端。"""
    by_name = {r["name"]: r for r in remotes}
    if target and target.get("remote") in by_name:
        saved = by_name[target["remote"]]
        # 已保存的目标只在平台仍可识别时推荐（远端还在但适配器没了，等于换了平台）。
        if saved["has_adapter"]:
            return {"remote": saved["name"], "base": target.get("base") or saved["base"],
                    "reason": "上次选择的目标"}
    identity = identity or {}
    identity_remote = str(identity.get("remote") or "")
    if identity_remote and identity_remote in by_name:
        return {"remote": identity_remote, "base": by_name[identity_remote]["base"],
                "reason": "归属仓"}
    upstream = _upstream_remote(root)
    if upstream and upstream in by_name:
        return {"remote": upstream, "base": by_name[upstream]["base"],
                "reason": "当前分支的上游"}
    if len(remotes) == 1:
        return {"remote": remotes[0]["name"], "base": remotes[0]["base"],
                "reason": "只有一个远端"}
    return None


def list_targets(root) -> dict:
    """远端清单 + 已保存目标 + 归属仓 + 推荐。只读、不探测网络（设计 5.7）。"""
    root = Path(root)
    ledger = _load_ledger_soft(root)
    target = load_target(root)
    identity = identity_target(root)
    adapters = load_adapters()
    remotes = []
    for name, url in _git_remotes(root):
        parsed = parse_remote_url(url)
        adapter = adapter_for_host(adapters, parsed["host"])
        profile = _profile(adapter) if adapter else {}
        remotes.append({
            "name": name,
            "url": url,
            "host": parsed["host"],
            "platform": adapter.get("id", "") if adapter else "",
            "platform_name": adapter.get("name", "") if adapter else "",
            "base": _remote_base(root, name),
            "has_adapter": bool(adapter),
            "token_ready": bool(profile.get("token_ready")),
            "requires_ok": bool(profile.get("requires_ok")),
            "note": target.get("note", "") if target and target.get("remote") == name else "",
            "last_used": _last_used(ledger, name, parsed["repo"],
                                    adapter.get("id", "") if adapter else ""),
        })
    identity_out = {key: identity.get(key) for key in ("remote", "url", "explicit")}
    return {"target": target, "remotes": remotes, "identity": identity_out,
            "recommendation": _recommend(root, target, remotes, identity),
            # 面板写回时的 CAS 令牌：与 `--status` 的 `sha256` 同一算法。台账不存在时为 null。
            "sha256": ledger_sha256(root)}


# ---------------------------------------------------------------- 平台查询（http / exec）

def _yaml_selftest(adapter: dict) -> list:
    """用适配器自己的 map/normalize 反推样例，不联网、不新增每个平台专属 fixture。

    对每条带 `when` 的规则造一份「能让它命中」的响应，再造一份「谁都不命中」的响应测兜底。
    这样新加一个 YAML 平台时，核心脚本不需要认识它（设计 5.8 的「加平台不改核心」）。
    """
    spec = (adapter.get("spec") or {}).get("check") or {}
    mapping = spec.get("map") or {}
    rules = spec.get("normalize") or []
    cases = []

    def evaluate(response):
        mapped = {key: _json_path(response, path) for key, path in mapping.items()}
        return _normalize(rules, mapped)

    for rule in rules:
        when = rule.get("when") if isinstance(rule, dict) else None
        if not isinstance(when, dict) or not when:
            continue
        response = {}
        for field, value in when.items():
            path = mapping.get(field)
            if path:
                _json_set(response, path, value)
        expected = _norm_state(rule.get("state"))
        actual = evaluate(response)
        cases.append({"name": "when-" + "-".join(f"{k}={v}" for k, v in when.items()),
                      "ok": actual == expected, "expected": expected, "actual": actual})

    fallback = None
    for rule in rules:
        when = rule.get("when") if isinstance(rule, dict) else None
        if not when:
            fallback = _norm_state(rule.get("state"))
            break
    if fallback is not None:
        response = {}
        for rule in rules:
            when = rule.get("when") if isinstance(rule, dict) else None
            for field, value in (when or {}).items():
                path = mapping.get(field)
                if not path:
                    continue
                if isinstance(value, bool):
                    _json_set(response, path, not value)
                elif value is None:
                    _json_set(response, path, "not-null")
                else:
                    _json_set(response, path, "not-" + str(value))
        actual = evaluate(response)
        cases.append({"name": "fallback", "ok": actual == fallback,
                      "expected": fallback, "actual": actual})
    return cases


def _exec_selftest(adapter: dict) -> list:
    module = adapter.get("module")
    fn = getattr(module, "selftest", None)
    if not callable(fn):
        return [{"name": "import", "ok": True, "expected": "import", "actual": "import"}]
    try:
        passed, cases = fn()
    except Exception as exc:
        return [{"name": "selftest", "ok": False, "expected": "passed",
                 "actual": f"{type(exc).__name__}: {exc}"}]
    out = []
    for case in cases or []:
        if isinstance(case, dict):
            item = dict(case)
            item["ok"] = bool(item.get("ok"))
        else:
            item = {"name": str(case), "ok": True}
        out.append(item)
    return out


def http_check(adapter: dict, pr: dict):
    """执行 YAML 适配器的一次查询 → (state, detail, error)。error 是 {code, message} 或 None。"""
    spec = (adapter.get("spec") or {}).get("check") or {}
    auth_env = adapter.get("auth_env") or ""
    if auth_env and not os.environ.get(auth_env):
        return "unknown", "", {"code": "E_NO_AUTH",
                               "message": f"未配置 token 环境变量 {auth_env}"}
    repo = str(pr.get("repo") or "")
    number = pr.get("number")
    url = _subst(str(spec.get("url") or ""), adapter, repo, number)
    query = spec.get("query") or {}
    if isinstance(query, dict) and query:
        params = urllib.parse.urlencode(
            {str(k): _subst(str(v), adapter, repo, number) for k, v in query.items()})
        url += ("&" if "?" in url else "?") + params
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        return "unknown", "", {"code": "E_PLATFORM",
                               "message": f"适配器 URL 只允许 http/https：{scheme or '（无 scheme）'}"}
    headers = {}
    for key, value in (spec.get("headers") or {}).items():
        headers[str(key)] = _subst(str(value), adapter, repo, number)
    method = str(spec.get("method") or "GET").upper()
    try:
        timeout = float(spec.get("timeout_s") or HTTP_TIMEOUT_S)
    except (TypeError, ValueError):
        timeout = HTTP_TIMEOUT_S
    request = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        return "unknown", "", {"code": "E_FETCH",
                               "message": f"HTTP {exc.code}：{_redact_url(url)}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return "unknown", "", {"code": "E_FETCH",
                               "message": f"请求失败：{exc}（{_redact_url(url)}）"}
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        return "unknown", "", {"code": "E_FETCH", "message": f"返回不是 JSON：{exc}"}
    mapping = spec.get("map") or {}
    mapped = {key: _json_path(payload, path) for key, path in mapping.items()}
    state = _normalize(spec.get("normalize") or [], mapped)
    return state, _redact_url(url), None


def exec_check(adapter: dict, pr: dict):
    """执行 Python 适配器的一次查询 → (state, detail)。异常归一成 unknown，不抛给调用方。"""
    module = adapter.get("module")
    try:
        result = module.check({"repo": pr.get("repo"), "number": pr.get("number"),
                               "url": pr.get("url")})
    except Exception as exc:
        return "unknown", f"{type(exc).__name__}: {exc}"
    if not isinstance(result, dict):
        return "unknown", "适配器 check() 返回的不是对象"
    return _norm_state(result.get("state")), str(result.get("detail") or "")


def _run_check(ledger: dict, key: str, adapters: list):
    """查一份草稿的 PR。返回 (新条目, error, detail)。error 非空时新条目是 unknown 态。"""
    pr = (ledger.get("prs") or {}).get(key)
    if not isinstance(pr, dict):
        return None, {"code": "E_NOT_FOUND", "message": f"台账里没有这份草稿的 PR 记录：{key}"}, ""
    url = str(pr.get("url") or "")
    adapter = adapter_for_url(adapters, url)
    if adapter is None:
        host = parse_remote_url(url)["host"]
        return _unknown_entry(pr), {"code": "E_NO_ADAPTER",
                                    "message": f"本机没有 host 为 {host or '（空）'} 的 PR 适配器"}, ""
    profile = _profile(adapter)
    if not profile["requires_ok"]:
        return _unknown_entry(pr), {"code": "E_NO_ADAPTER",
                                    "message": profile["reason"] or "适配器依赖缺失"}, ""
    if not profile["token_ready"]:
        return _unknown_entry(pr), {"code": "E_NO_AUTH",
                                    "message": profile["reason"] or "未配置 token"}, ""
    if adapter.get("kind") == "http":
        state, detail, error = http_check(adapter, pr)
    else:
        state, detail = exec_check(adapter, pr)
        error = None
    entry = dict(pr)
    entry["platform"] = adapter.get("id") or str(pr.get("platform") or "")
    entry["state"] = state
    entry["source"] = "platform"
    entry["checked_at"] = now_iso()
    return entry, error, detail


def _unknown_entry(pr: dict) -> dict:
    """查不了也要留痕：写 unknown + source=platform + checked_at，不删旧 PR（契约 §1）。"""
    entry = dict(pr)
    entry["state"] = "unknown"
    entry["source"] = "platform"
    entry["checked_at"] = now_iso()
    return entry


# ---------------------------------------------------------------- 命令实现

def _ok(payload: dict, code: int = EXIT_OK) -> int:
    payload["ok"] = True
    print(dump_json(payload), end="")
    return code


def _fail(code_name: str, message: str, extra: dict = None,
          exit_code: int = EXIT_OK) -> int:
    payload = {"ok": False, "error": {"code": code_name, "message": message}}
    if extra:
        payload.update(extra)
    print(dump_json(payload), end="")
    return exit_code


def _arg_fail(message: str) -> int:
    return _fail("E_ARGS", message, exit_code=EXIT_ARGS)


def _resolve_root(value) -> Path:
    path = Path(value or ".").expanduser().resolve()
    if not path.is_dir():
        raise NotADirectoryError(f"目录不存在：{path}")
    try:
        top = run_git(["rev-parse", "--show-toplevel"], cwd=path, check=False)
        if top.returncode == 0 and top.stdout.strip():
            return Path(top.stdout.strip()).resolve()
    except Exception:
        pass
    return path


def cmd_status(root) -> int:
    data = load_ledger(root)
    settings, source, problem = kb_sync.load_settings(Path(root))
    return _ok({
        "ledger": data,
        "sha256": ledger_sha256(root),
        "settings": {
            "path": str(kb_sync.settings_path(root)),
            "config": source,
            "problem": problem,
            "sync": settings.get("sync"),
            "target": settings.get("target"),
        },
        "settings_sha256": kb_sync.settings_sha256(root),
    })


def cmd_migrate(root, args) -> int:
    """把旧台账的 target 搬进 settings 一次；旧文件保留。

    令牌：显式 `--expect-sha256` 优先，否则取读配置时的文件指纹。写动作在
    `save_settings` 的 `log_lock` 内重新读 sha 比对，读配置后被人改过就拒绝覆盖。
    """
    settings_sha = _settings_sha_or_none(root)
    settings, source, problem = kb_sync.load_settings(Path(root))
    current = kb_sync.normalize_target(settings.get("target"))
    legacy = _normalize_target(_load_ledger_soft(root).get("target"))
    base = {
        "settings": str(kb_sync.settings_path(root)),
        "legacy": str(ledger_path(root)),
        "config": source,
        "config_problem": problem,
        "sha256": settings_sha,
    }
    if current is not None:
        return _ok({"migrated": False, "reason": "settings 已有 target",
                    "target": current, **base})
    if legacy is None:
        return _ok({"migrated": False, "reason": "旧台账没有 target",
                    "target": None, **base})
    settings["target"] = legacy
    try:
        digest = kb_sync.save_settings(
            Path(root), settings,
            expect_sha=_settings_expect_sha(settings_sha, args.expect_sha256))
    except kb_sync.SettingsCasConflict as exc:
        return _fail("E_CAS", str(exc), extra=base)
    except kb_sync.SettingsError as exc:
        return _fail("E_SETTINGS", str(exc), extra=base)
    return _ok({"migrated": True, "target": legacy, **base, "sha256": digest})


def cmd_set_sync(root, args) -> int:
    """写 settings 的 sync 段；CAS 令牌是 settings 文件字节 sha256。

    没给 `--expect-sha256` 时用读配置那一刻的指纹：面板一直显式给令牌，命令行手写
    也走同一条「读 sha → 比对 → 写」路径，读后被别人改过就拒绝覆盖。
    """
    if not any((args.remote is not None, args.branch is not None, args.enable,
                args.disable, args.auto_merge is not None)):
        return _arg_fail("--set-sync 至少给一个 --remote / --branch / --enable / --disable / --auto-merge")
    settings_sha = _settings_sha_or_none(root)
    settings, source, problem = kb_sync.load_settings(Path(root))
    sync = dict(settings.get("sync") or {})
    remotes = dict(_git_remotes(root))
    if args.remote is not None:
        remote = str(args.remote).strip()
        if not remote:
            return _arg_fail("--set-sync 的 --remote 不能为空")
        if remote not in remotes:
            return _arg_fail(f"远端不存在：{remote}（本机远端：{'、'.join(remotes) or '无'}）")
        sync["remote"] = remote
    if args.branch is not None:
        branch = str(args.branch).strip()
        if not branch:
            return _arg_fail("--set-sync 的 --branch 不能为空")
        sync["branch"] = branch
    if args.enable:
        sync["enabled"] = True
    if args.disable:
        sync["enabled"] = False
    if args.auto_merge is not None:
        sync["auto_merge"] = args.auto_merge == "on"
    settings["sync"] = sync
    try:
        digest = kb_sync.save_settings(
            Path(root), settings,
            expect_sha=_settings_expect_sha(settings_sha, args.expect_sha256))
    except kb_sync.SettingsCasConflict as exc:
        return _fail("E_CAS", str(exc))
    except kb_sync.SettingsError as exc:
        return _fail("E_SETTINGS", str(exc), extra={"write_failed": True})
    return _ok({"sync": kb_sync.normalize_sync(sync), "config": source,
                "config_problem": problem,
                "settings": str(kb_sync.settings_path(root)),
                "sha256": digest})


def cmd_set_identity(root, args) -> int:
    """写 settings 的归属仓（`identity.remote`）；CAS 令牌与 `--set-sync` 同一个写点。

    远端必须在本机存在：写一个解析不到的名字会让读侧只拉不合并，写成配置事故。
    """
    remote = str(args.remote or "").strip()
    if not remote:
        return _arg_fail("--set-identity 需要 --remote")
    remotes = dict(_git_remotes(root))
    if remote not in remotes:
        return _arg_fail(f"远端不存在：{remote}（本机远端：{'、'.join(remotes) or '无'}）")
    settings_sha = _settings_sha_or_none(root)
    settings, source, problem = kb_sync.load_settings(Path(root))
    settings["identity"] = {"remote": remote}
    try:
        digest = kb_sync.save_settings(
            Path(root), settings,
            expect_sha=_settings_expect_sha(settings_sha, args.expect_sha256))
    except kb_sync.SettingsCasConflict as exc:
        return _fail("E_CAS", str(exc))
    except kb_sync.SettingsError as exc:
        return _fail("E_SETTINGS", str(exc), extra={"write_failed": True})
    return _ok({"identity": {"remote": remote}, "config": source,
                "config_problem": problem,
                "settings": str(kb_sync.settings_path(root)),
                "sha256": digest})


def cmd_list_targets(root) -> int:
    return _ok(list_targets(root))


def cmd_set_target(root, args) -> int:
    remote = str(args.remote or "").strip()
    base = str(args.base or DEFAULT_BASE).strip()
    if not remote:
        return _arg_fail("--set-target 需要 --remote")
    if not base:
        return _arg_fail("--set-target 的 --base 不能为空")
    remotes = dict(_git_remotes(root))
    if remote not in remotes:
        return _arg_fail(f"远端不存在：{remote}（本机远端：{'、'.join(remotes) or '无'}）")
    labels = {}
    if args.labels:
        try:
            labels = json.loads(args.labels)
        except ValueError as exc:
            return _arg_fail(f"--labels 不是合法 JSON：{exc}")
        if not isinstance(labels, dict):
            return _arg_fail("--labels 必须是 JSON 对象（映射）")
    url = remotes[remote]
    adapter = adapter_for_url(load_adapters(), url)
    target = {
        "remote": remote, "base": base,
        # 无适配器的远端也能选：平台留空，界面显示「无适配器」（设计 5.7）。
        "platform": adapter.get("id", "") if adapter else "",
        "url": url, "note": str(args.note or ""), "labels": labels,
        "source": "user", "chosen_at": now_iso(),
    }
    data = load_ledger(root)
    data["target"] = target
    # 先取文件指纹、再读 settings 内容：台账写完后才写 settings，这一段窗口里别的写者
    # （面板 --set-sync）改过配置就必须放弃覆盖，而不是拿旧 sync 段盖回去。
    # 这里不传 --expect-sha256：那个令牌是台账的（面板从 --list-targets 的 sha256 取）。
    settings_sha = _settings_sha_or_none(root)
    settings, _source, _problem = kb_sync.load_settings(Path(root))
    try:
        digest = save_ledger(root, data, expect_sha=args.expect_sha256)
    except CasConflict as exc:
        return _fail("E_CAS", str(exc))
    except LedgerError as exc:
        return _fail("E_LEDGER", str(exc), extra={"write_failed": True})
    # target 的读侧已迁到 settings；台账里仍写一份，旧版本面板与 --migrate 都能读到。
    settings["target"] = target
    try:
        settings_digest = kb_sync.save_settings(Path(root), settings, expect_sha=settings_sha)
    except kb_sync.SettingsCasConflict as exc:
        return _fail("E_CAS", str(exc), extra={"target": target, "sha256": digest})
    except kb_sync.SettingsError as exc:
        return _fail("E_SETTINGS", str(exc),
                     extra={"target": target, "sha256": digest, "write_failed": True})
    return _ok({"target": target,
                "platformName": adapter.get("name", "") if adapter else "",
                "sha256": digest,
                "settings_sha256": settings_digest})


def _validate_pr_args(args):
    draft = str(args.draft or "").strip()
    platform = str(args.platform or "").strip()
    repo = str(args.repo or "").strip()
    url = str(args.url or "").strip()
    if not draft:
        return None, "--set 需要 --draft"
    if not platform:
        return None, "--set 需要 --platform"
    if "/" not in repo:
        return None, "--set 的 --repo 需要 owner/repo 形式"
    try:
        number = int(args.number)
    except (TypeError, ValueError):
        return None, "--set 的 --number 必须是正整数"
    if number <= 0:
        return None, "--set 的 --number 必须是正整数"
    if urllib.parse.urlsplit(url).scheme.lower() not in ("http", "https"):
        return None, "--set 的 --url 需要 http/https 地址"
    state = str(args.state or "unknown").strip().lower()
    if state not in STATES:
        return None, f"--state 只能是 {'/'.join(STATES)}"
    return {"draft": draft, "platform": platform, "repo": repo, "number": number,
            "url": url, "state": state,
            "remote": str(getattr(args, "remote", None) or "").strip()}, None


def cmd_set(root, args) -> int:
    values, problem = _validate_pr_args(args)
    if problem:
        return _arg_fail(problem)
    entry = {
        "platform": values["platform"], "repo": values["repo"], "number": values["number"],
        "url": values["url"], "state": values["state"], "source": "ledger",
        "created_at": now_iso(),
    }
    if values["remote"]:
        entry["remote"] = values["remote"]
    data = load_ledger(root)
    data["prs"][values["draft"]] = entry
    try:
        digest = save_ledger(root, data, expect_sha=args.expect_sha256)
    except CasConflict as exc:
        return _fail("E_CAS", str(exc))
    except LedgerError as exc:
        return _fail("E_LEDGER", str(exc), extra={"write_failed": True})
    return _ok({"draft": values["draft"], "pr": entry, "sha256": digest})


def cmd_mark(root, args) -> int:
    draft = str(args.draft or "").strip()
    state = str(args.state or "").strip().lower()
    if not draft:
        return _arg_fail("--mark 需要 --draft")
    if state not in STATES:
        return _arg_fail(f"--mark 的 --state 只能是 {'/'.join(STATES)}")
    data = load_ledger(root)
    pr = data["prs"].get(draft)
    if not isinstance(pr, dict):
        return _fail("E_NOT_FOUND", f"台账里没有这份草稿的 PR 记录：{draft}")
    entry = dict(pr)
    entry.update({"state": state, "source": "manual", "checked_at": now_iso()})
    data["prs"][draft] = entry
    try:
        digest = save_ledger(root, data, expect_sha=args.expect_sha256)
    except CasConflict as exc:
        return _fail("E_CAS", str(exc))
    except LedgerError as exc:
        return _fail("E_LEDGER", str(exc), extra={"write_failed": True})
    return _ok({"draft": draft, "pr": entry, "sha256": digest})


def cmd_forget(root, args) -> int:
    draft = str(args.draft or "").strip()
    if not draft:
        return _arg_fail("--forget 需要 --draft")
    try:
        result = forget_pr(root, draft, expect_sha=args.expect_sha256)
    except PrRecordError as exc:
        return _fail(exc.code, str(exc))
    except CasConflict as exc:
        return _fail("E_CAS", str(exc))
    except LedgerError as exc:
        return _fail("E_LEDGER", str(exc), extra={"write_failed": True})
    return _ok(result)


def cmd_check(root, args) -> int:
    draft = str(args.draft or "").strip()
    if not draft:
        return _arg_fail("--check 需要 --draft")
    adapters = load_adapters()
    data = load_ledger(root)
    before = ledger_sha256(root)
    expected = getattr(args, "expect_sha256", None)
    if expected is not None and expected != before:
        # 面板拿的是旧队列时，查询与写回都建立在过期快照上。查询前按 CAS 拒绝；
        # 写回仍用函数内 read-before CAS 兜底。
        return _fail("E_CAS", str(CasConflict(expected, before or "")))
    entry, error, detail = _run_check(data, draft, adapters)
    if entry is None:
        return _fail(error["code"], error["message"])
    data["prs"][draft] = entry
    try:
        digest = save_ledger(root, data, expect_sha=before)
    except CasConflict as exc:
        return _fail("E_CAS", str(exc))
    except LedgerError as exc:
        # 平台结果已经拿到，只是没写进台账：把 state / checked_at 一起带出去，
        # 面板能说「查到 X，但没写进台账」，读者不必白查一遍。
        return _fail("E_LEDGER", str(exc), extra={"draft": draft,
                                                  "state": entry["state"],
                                                  "checked_at": entry["checked_at"],
                                                  "write_failed": True})
    if error:
        return _fail(error["code"], error["message"],
                     extra={"draft": draft, "state": entry["state"],
                            "checked_at": entry["checked_at"], "sha256": digest})
    return _ok({"draft": draft, "platform": entry.get("platform", ""),
                "state": entry["state"], "source": "platform",
                "checked_at": entry["checked_at"], "detail": detail, "sha256": digest})


def _print_json_line(payload: dict) -> None:
    """--json-lines 的一行：单行 JSON + 立即 flush，面板要边收边显示。"""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _done_line(*, ok: bool, checked: list, ledger: dict = None, sha256: str = None,
               error_code: str = None, message: str = None, write_failed: bool = False) -> dict:
    """done 行：与 --json 的最终载荷同形，只多一个 type（见文件头的契约）。"""
    payload = {"type": "done", "ok": ok, "checked": checked}
    if error_code:
        payload["error"] = {"code": error_code, "message": message or ""}
    if write_failed:
        payload["write_failed"] = True
    if ledger is not None:
        payload["ledger"] = ledger
    if sha256 is not None:
        payload["sha256"] = sha256
    return payload


def _row_line(draft: str, result) -> dict:
    """row 行：一条查完就发。失败原文放 message，面板直接显示原因，不等整批。"""
    entry, error, detail = result
    row = {"type": "row", "draft": draft, "ok": error is None,
           "state": "unknown", "checked_at": now_iso()}
    if entry is not None:
        row["state"] = entry.get("state") or "unknown"
        row["checked_at"] = entry.get("checked_at") or row["checked_at"]
    if error:
        row["ok"] = False
        row["error"] = error["code"]
        message = error.get("message") or detail
        if message:
            row["message"] = message
    return row


def cmd_check_all(root, args) -> int:
    json_lines = bool(getattr(args, "json_lines", False))
    adapters = load_adapters()
    data = load_ledger(root)
    before = ledger_sha256(root)
    # 查询走只读快照：worker 只返回结果，不改台账；写回统一在主线程按台账键顺序做。
    snapshot = {"prs": {key: dict(value) if isinstance(value, dict) else value
                        for key, value in (data.get("prs") or {}).items()}}
    drafts = [draft for draft in sorted(snapshot["prs"].keys())
              if isinstance(snapshot["prs"].get(draft), dict)
              and str(snapshot["prs"][draft].get("state") or "") in CHECKABLE]
    results = {}
    if drafts:
        with ThreadPoolExecutor(max_workers=CHECK_ALL_WORKERS) as pool:
            futures = {pool.submit(_run_check, snapshot, draft, adapters): draft
                       for draft in drafts}
            for future in as_completed(futures):
                # _run_check 已把适配器异常归一成 unknown；这里仍不吞异常，交给 main 折 JSON。
                draft = futures[future]
                results[draft] = future.result()
                # 行序是完成序（面板按 draft 覆盖，不看顺序）；checked[] 仍是台账键序。
                if json_lines:
                    _print_json_line(_row_line(draft, results[draft]))
    checked = []
    all_ok = True
    for draft in drafts:  # 按台账键排序输出，与并发完成顺序无关
        entry, error, detail = results[draft]
        if entry is None:
            checked.append({"draft": draft, "ok": False, "state": "unknown",
                            "error": error["code"]})
            all_ok = False
            continue
        data["prs"][draft] = entry
        item = {"draft": draft, "ok": error is None, "state": entry["state"]}
        if error:
            item["error"] = error["code"]
            all_ok = False
        checked.append(item)
    try:
        digest = save_ledger(root, data, expect_sha=before)
    except CasConflict as exc:
        if json_lines:
            _print_json_line(_done_line(ok=False, checked=checked,
                                        error_code="E_CAS", message=str(exc)))
            return EXIT_OK
        return _fail("E_CAS", str(exc), extra={"checked": checked})
    except LedgerError as exc:
        if json_lines:
            _print_json_line(_done_line(ok=False, checked=checked,
                                        error_code="E_LEDGER", message=str(exc),
                                        write_failed=True))
            return EXIT_OK
        return _fail("E_LEDGER", str(exc), extra={"checked": checked, "write_failed": True})
    if json_lines:
        if all_ok:
            _print_json_line(_done_line(ok=True, checked=checked,
                                        ledger=data, sha256=digest))
            return EXIT_OK
        _print_json_line(_done_line(ok=False, checked=checked, ledger=data, sha256=digest,
                                    error_code="E_CHECK_PARTIAL",
                                    message="有 PR 状态没查到（见 checked）"))
        return EXIT_OK
    return _ok({"checked": checked, "ledger": data, "sha256": digest}, code=EXIT_OK) \
        if all_ok else _fail("E_CHECK_PARTIAL", "有 PR 状态没查到（见 checked）",
                             extra={"checked": checked, "ledger": data, "sha256": digest})


def cmd_list_platforms(root) -> int:
    platforms = [_profile(adapter) for adapter in load_adapters()]
    platforms.sort(key=lambda p: p.get("id", ""))
    return _ok({"platforms": platforms})


def cmd_selftest(root, platform_id: str) -> int:
    adapters = load_adapters()
    adapter = find_adapter(adapters, platform_id)
    if adapter is None:
        return _fail("E_NOT_FOUND", f"没有这个平台适配器：{platform_id}")
    if adapter.get("broken"):
        return _fail("E_PLATFORM", "清单损坏：" + (adapter.get("reason") or "未知原因"),
                     extra={"platform": platform_id, "passed": 0, "cases": []})
    cases = _yaml_selftest(adapter) if adapter.get("kind") == "http" else _exec_selftest(adapter)
    cases = [case for case in cases if isinstance(case, dict)]
    passed = sum(1 for case in cases if case.get("ok"))
    payload = {"platform": platform_id, "passed": passed, "total": len(cases),
               "cases": cases}
    if not cases:
        return _fail("E_PLATFORM", "适配器没有可执行的自检样例", extra=payload)
    if passed != len(cases):
        payload["ok"] = False
        payload["error"] = {"code": "E_SELFTEST",
                            "message": f"{len(cases) - passed} 条自检未通过"}
        print(dump_json(payload), end="")
        return EXIT_OK
    return _ok(payload)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="提 PR 目标与 PR 状态台账（只写本地台账）")
    ap.add_argument("--root", default=None, help="ascend-sleuth 检出根；默认当前目录")
    ap.add_argument("--json", action="store_true", help="输出 JSON（所有命令都输出 JSON，保留兼容）")
    ap.add_argument("--json-lines", action="store_true", dest="json_lines",
                    help="配合 --check-all：每查完一条输出一行 JSON，最后输出汇总行（契约见文件头）")
    ap.add_argument("--expect-sha256", default=None,
                    help="写前 CAS 令牌：--set-target / --set / --mark / --forget / --check 用台账 sha256，"
                         "--migrate / --set-sync / --set-identity 用 settings 的 sha256")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--list-targets", action="store_true", help="列远端、平台与推荐目标")
    group.add_argument("--set-target", action="store_true", help="写 target 段")
    group.add_argument("--migrate", action="store_true", help="把旧台账的 target 搬进 settings")
    group.add_argument("--set-sync", action="store_true", dest="set_sync",
                       help="写 settings 的 sync 段")
    group.add_argument("--set-identity", action="store_true", dest="set_identity",
                       help="写 settings 的归属仓（identity.remote）")
    group.add_argument("--set", action="store_true", dest="set_pr", help="写/覆盖一份草稿的 PR 记录")
    group.add_argument("--mark", action="store_true", help="人手确认 PR 状态")
    group.add_argument("--forget", action="store_true", help="删掉一份已关闭的 PR 记录（其余状态拒绝）")
    group.add_argument("--check", action="store_true", help="按平台查一份 PR 的状态")
    group.add_argument("--check-all", action="store_true", dest="check_all", help="查所有 open/unknown 的 PR")
    group.add_argument("--list-platforms", action="store_true", dest="list_platforms",
                       help="列平台适配器与依赖状态")
    group.add_argument("--selftest", default=None, metavar="PLATFORM",
                       help="适配器自检（不联网）")
    # --set-target / --set-sync
    ap.add_argument("--remote", default=None)
    ap.add_argument("--branch", default=None)
    ap.add_argument("--base", default=None)
    enable_group = ap.add_mutually_exclusive_group()
    enable_group.add_argument("--enable", action="store_true", help="sync.enabled = true")
    enable_group.add_argument("--disable", action="store_true", help="sync.enabled = false")
    ap.add_argument("--auto-merge", choices=("on", "off"), default=None,
                    help="sync.auto_merge 开关")
    ap.add_argument("--note", default="")
    ap.add_argument("--labels", default=None, help="目标标签映射，JSON 对象")
    # --set
    ap.add_argument("--draft", default=None)
    ap.add_argument("--platform", default=None)
    ap.add_argument("--repo", default=None)
    ap.add_argument("--number", default=None)
    ap.add_argument("--url", default=None)
    ap.add_argument("--state", default=None)
    return ap


def main(argv=None) -> int:
    pin_utf8_stdio()
    args = build_parser().parse_args(argv)
    if args.json and args.json_lines:
        return _arg_fail("--json 与 --json-lines 互斥")
    if args.json_lines and not args.check_all:
        return _arg_fail("--json-lines 只配合 --check-all 使用")
    try:
        root = _resolve_root(args.root)
    except NotADirectoryError as exc:
        return _arg_fail(str(exc))
    try:
        if args.list_platforms:
            return cmd_list_platforms(root)
        if args.selftest:
            return cmd_selftest(root, args.selftest)
        if args.list_targets:
            return cmd_list_targets(root)
        if args.set_target:
            return cmd_set_target(root, args)
        if args.migrate:
            return cmd_migrate(root, args)
        if args.set_sync:
            return cmd_set_sync(root, args)
        if args.set_identity:
            return cmd_set_identity(root, args)
        if args.set_pr:
            return cmd_set(root, args)
        if args.mark:
            return cmd_mark(root, args)
        if args.forget:
            return cmd_forget(root, args)
        if args.check:
            return cmd_check(root, args)
        if args.check_all:
            return cmd_check_all(root, args)
        return cmd_status(root)
    except LedgerError as exc:
        if args.json_lines:
            # 台账读坏发生在任何 row 之前；仍折成一行 compact JSON，与 E_INTERNAL 同形。
            _print_json_line({"ok": False, "error": {"code": "E_LEDGER", "message": str(exc)}})
            return EXIT_OK
        return _fail("E_LEDGER", str(exc))
    except Exception as exc:  # 未预期异常也走 JSON，调用方不用解析 traceback
        message = f"{type(exc).__name__}: {exc}"
        if args.json_lines:
            # 可能已经打过若干 row：这里必须是一行 compact JSON，面板才能从行尾整段还原。
            _print_json_line({"ok": False, "error": {"code": "E_INTERNAL", "message": message}})
            return EXIT_ERROR
        return _fail("E_INTERNAL", message, exit_code=EXIT_ERROR)


if __name__ == "__main__":
    sys.exit(main())
