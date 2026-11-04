#!/usr/bin/env python3
# groom_snapshot.py —— Groom 的知识快照：取到**一个确定的 commit**，不碰工作区
#
# 为什么需要它（groom 现在的问题）：
#   预分诊读的是"当前检出里的 knowledge/"。那个目录可能落后 origin/main 几十个 commit，
#   也可能带着别人未提交的改动。于是同一份草稿在不同人的机器上会得到不同的候选集，
#   而报告里没有任何字段能说清"这次到底比的是哪一版知识"。
#
# 本脚本只做四件事：
#   1. `git fetch <remote> <branch>`（只更新远端跟踪引用，不 pull / 不 merge / 不 rebase）；
#   2. 解析 `<remote>/<branch>` 的 commit，作为**唯一比较基准**；
#   3. 在独立路径建一个 detach 的 git worktree（或 git archive 退路），只读地展开该 commit；
#   4. 校验（必要时重建）快照里的索引，把 commit / 索引状态 / 是否 fresh 写进 meta JSON。
#
# 边界（必须如实读）：
#   - 快照是**某一时刻**的远端状态。fetch 之后 main 仍可前进，所以"fresh"只表示
#     "抓取成功且与 fetch 那一刻的 <remote>/<branch> 一致"，不是"合入时仍最新"。
#   - fetch 失败时**默认失败退出（2）**；显式 `--offline`、settings 的 `sync.enabled: false`、
#     `deployment.yaml` 的 `sync.mode: offline` 三种情况不联网，用本地已有引用，
#     并标 `fresh: false, authoritative: false`。stale 数据不会被静默当成权威。
#   - 不修改源工作区：worktree 是另一个目录；源工作区的本地改动与未跟踪 inbox 均不变。
#
# 用法：
#   python3 scripts/groom_snapshot.py --list-remotes          # 多个远端时让用户选；只有一个可跳过
#   python3 scripts/groom_snapshot.py --require-fresh         # 默认同步源读主检出 .local/settings.json 的 sync 段
#   python3 scripts/groom_snapshot.py --remote origin --require-fresh  # 有多个远端且未配置时由用户选
#   python3 scripts/groom_snapshot.py --remote origin --json   # 同上，stdout 输出 meta JSON
#   python3 scripts/groom_snapshot.py --remote origin --offline  # 用本地已有引用，显式降级
#   python3 scripts/groom_snapshot.py --prune                 # 清理旧的 groom 快照 worktree
#
# 同步源：优先读主检出 `.local/settings.json` 的 `sync.remote` / `sync.branch`（未进 git，
# 各 worktree 共用一份）。配置缺失时保持原行为：`--list-remotes` 列出远端、由 agent 问用户，
# `--remote` 显式指定时以它为准。
#
# 退出码：0 = 快照可用；2 = 同步失败 / 索引不可用 / --require-fresh 不满足；3 = 用法错误。

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import kb_sync
from _stdio import pin_utf8_stdio
from exec_log_path import main_checkout
from groom_common import (
    SCHEMA_SNAPSHOT, atomic_write_text, dump_json, find_drafts, load_json, now_iso,
    repo_root, run_git, shared_inbox, short_sha,
)

INDEX_CHECK = ["scripts/build_index.py", "--check"]
INDEX_BUILD = ["scripts/build_index.py"]

SETTINGS_REL = Path(".local/settings.json")
SETTINGS_SCHEMA_PREFIX = "ascend-sleuth-settings/"


def _child_env():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run_py(cwd: Path, args):
    return subprocess.run(
        [sys.executable, *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=_child_env(), timeout=600,
    )


def list_remotes(root: Path):
    """列出本机已配置的远端名，供 agent 让用户选择同步源。

    不判断托管平台、不输出 URL：远端别名由用户自己维护，agent 只负责问。
    """
    proc = run_git(["remote", "-v"], cwd=root, check=False)
    names, seen = [], set()
    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) < 2 or parts[0] in seen:
                continue
            seen.add(parts[0])
            names.append({"name": parts[0]})
    return names


def load_sync_settings(root: Path):
    """读主检出 `.local/settings.json` 的 `sync` 段 → (remote, branch, enabled, error)。

    配置缺失（没有文件、或文件里没有 `sync`）返回 (None, None, True, None)：调用方退回
    `--list-remotes` 那套问用户的行为。文件在但读不出或结构不对返回 error，调用方会说明一句后
    按未配置处理——拼错的配置若被当成"没配置"而不出声，同步源会静默换成另一个远端。
    """
    base = main_checkout(root) or root
    path = base / SETTINGS_REL
    if not path.is_file():
        return None, None, True, None
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        return None, None, True, f"{path} 读不出：{e}"
    if not isinstance(doc, dict):
        return None, None, True, f"{path} 顶层不是对象"
    schema = str(doc.get("schema") or "")
    if schema and not schema.startswith(SETTINGS_SCHEMA_PREFIX):
        return None, None, True, f"{path} 的 schema {schema!r} 不认（本脚本认 {SETTINGS_SCHEMA_PREFIX}*）"
    sync = doc.get("sync")
    if sync is None:
        return None, None, True, None
    if not isinstance(sync, dict):
        return None, None, True, f"{path} 的 sync 段不是对象"
    remote = str(sync.get("remote") or "").strip() or None
    branch = str(sync.get("branch") or "").strip() or None
    enabled = kb_sync.normalize_sync(sync)["enabled"]
    return remote, branch, enabled, None


def _fetch_policy(root: Path, offline: bool):
    """本次是否联网 → (allow_fetch, skip_reason)。

    `--offline` 与 `deployment.yaml` 声明 `sync.mode: offline` 两种情况不 fetch，改用本机
    已有 ref 建快照：meta 按现有 `fresh` / `authoritative` 语义标 false，不联网的原因写进
    `fetch_error`。个人配置的 `sync.enabled` 只管诊断读侧的自动检查，不影响 groom——
    groom 是显式动作，`--require-fresh` 要求这一版是最新的。整机离线请用 deployment 声明。
    """
    if offline:
        return False, "offline 模式：未尝试 fetch"
    if kb_sync.deployment_sync_mode(root) == "offline":
        return False, "deployment.yaml 声明 sync.mode: offline，未尝试 fetch；使用本机已有引用"
    return True, None


def persist_sync_source(root: Path, remote: str, branch: str):
    """把本次选定的同步源写回 `.local/settings.json` 一次 → (ok, error)。

    只在配置里没有可用同步源时调用（已有配置时不覆盖用户的选择）。写失败不阻塞建快照：
    记住同步源只是省下一次选择，不是快照的前置条件。
    """
    try:
        sha = kb_sync.settings_sha256(Path(root))
        settings, _source, _problem = kb_sync.load_settings(Path(root))
        sync = dict(settings.get("sync") or {})
        sync["remote"] = remote
        if branch:
            sync["branch"] = branch
        settings["sync"] = sync
        kb_sync.save_settings(Path(root), settings, expect_sha=sha)
        return True, ""
    except Exception as exc:  # noqa: BLE001 - 写配置失败只是少一次记忆，不能拦住快照
        return False, f"{type(exc).__name__}: {exc}"


def _fetch(root: Path, remote: str, branch: str):
    proc = run_git(["fetch", "--no-tags", remote, branch], cwd=root, check=False, timeout=300)
    if proc.returncode == 0:
        return True, None
    err = (proc.stderr or proc.stdout or "").strip().splitlines()
    return False, (err[-1] if err else f"git fetch 退出码 {proc.returncode}")


def _resolve_commit(root: Path, remote: str, branch: str, offline: bool):
    """返回 (ref, commit, error)。fresh fetch 后优先远端跟踪引用；离线才退回本地分支。"""
    candidates = []
    if not offline:
        candidates.append(f"refs/remotes/{remote}/{branch}")
    else:
        candidates += [f"refs/remotes/{remote}/{branch}", f"refs/heads/{branch}"]
    for ref in candidates:
        proc = run_git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=root, check=False)
        if proc.returncode == 0 and proc.stdout.strip():
            return ref, proc.stdout.strip(), None
    return None, None, f"找不到 {remote}/{branch} 的本地引用（先 fetch，或确认分支名）"


def _worktree_path(snapshot_dir: Path, branch: str, commit: str) -> Path:
    safe_branch = branch.replace("/", "_").replace("\\", "_")
    return snapshot_dir / f"{safe_branch}-{short_sha(commit)}"


def _is_generated_index(rel: str) -> bool:
    return rel == "knowledge/_index.yaml" or rel.startswith("knowledge/_index/")


#: 快照只物化**索引的输入集**，不是整棵树（见 docs/mechanism/agent-groom.md 3.1）。
#: 三项都是实测出来的最小依赖：knowledge（case 本体）、scripts（生成器与其 import 链）、
#: metrics（`metrics/entry-activity/` 决定每行的 score）。缺 metrics 时生成器不报错，
#: 但分数会退回先验值，索引与仓库那份不同；其余目录（docs/ 一家 23 MB）没有任何读者。
#: 顺序即检出顺序；commit 里不存在的路径会被跳过（测试夹具的小仓库只有 knowledge/scripts），
#: 缺项记进 meta 的 `checkout.missing`。**只放顶层目录**：cone 模式下 `sparse-checkout list`
#: 会把 `knowledge` 与 `knowledge/common` 归一成 `knowledge`，嵌套项会让 `_sparse_ok` 的
#: 集合相等恒假、每次 groom 都重建。
#:
#: 根目录文件现在被 cone 模式**自动带上**，这不是多余的：`scripts/verify_case_draft.py`
#: 在 import 期加载 `_trace_state`，后者读根目录的 `trace-status.yaml`。若将来改成非 cone
#: （为了再省掉约 1.2 MB 根文件），必须把 `trace-status.yaml` 显式加进清单，否则快照里
#: 任何跑升格闸门的步骤都会在 import 期就失败。
SNAPSHOT_SPARSE_PATHS = ("knowledge", "scripts", "metrics")


def _paths_in_commit(root: Path, commit: str, paths):
    """只保留该 commit 里真实存在的路径：稀疏清单不因夹具仓库缺目录而报错。"""
    present = []
    for p in paths:
        proc = run_git(["cat-file", "-e", f"{commit}:{p}"], cwd=root, check=False)
        if proc.returncode == 0:
            present.append(p)
    return present


def _sparse_ok(path: Path, sparse_paths) -> bool:
    """复用前的第二道检查：检出范围必须与期望一致。

    稀疏检出下「没检出」与「没改」在 `git status` 里长得一样，所以只看工作区是不够的：
    范围变了（例如上一次是整树、这一次要求稀疏）也必须重建，否则快照的内容范围会悄悄漂移。

    两种「空列表」必须分开：非稀疏 worktree 上 `sparse-checkout list` 以 128 退出（
    "this worktree is not sparse"）——那是整树，可以复用；而 `init` 过却没 `set` 的半成品
    会以 0 退出并给出空列表——那种树什么都没铺，不能当整树用。
    """
    proc = run_git(["sparse-checkout", "list"], cwd=path, check=False)
    current = {l.strip() for l in (proc.stdout or "").splitlines() if l.strip()}
    expected = set(sparse_paths)
    if not expected:
        return proc.returncode != 0 and not current
    if proc.returncode != 0 or current != expected:
        return False
    # 范围对但目录没真正落盘（例如检出中断）同样不可复用
    return all((path / p).exists() for p in expected)


def _existing_worktree_ok(path: Path, commit: str, sparse_paths=()) -> bool:
    """可复用 = HEAD 对 + 检出范围对 + 没有**源文件**改动。

    快照内重建索引会写 `knowledge/_index*`，那是预期副作用；除它之外的 tracked/untracked
    改动（尤其是 `knowledge/**/*.yaml` Case 本体）意味着这棵树已经不是该 commit 的
    权威表示，必须重建。否则下一个 groom 会把被改过的 Case 当成 origin/main 的内容。
    """
    if not (path / ".git").exists():
        return False
    proc = run_git(["rev-parse", "HEAD"], cwd=path, check=False)
    if proc.returncode != 0 or proc.stdout.strip() != commit:
        return False
    if not _sparse_ok(path, sparse_paths):
        return False
    changed = run_git(["diff", "--name-only", "HEAD"], cwd=path, check=False)
    untracked = run_git(["ls-files", "--others", "--exclude-standard"], cwd=path, check=False)
    paths = []
    if changed.returncode == 0:
        paths += [p for p in changed.stdout.splitlines() if p.strip()]
    if untracked.returncode == 0:
        paths += [p for p in untracked.stdout.splitlines() if p.strip()]
    dirty_source = [p for p in paths if not _is_generated_index(p.replace("\\", "/"))]
    return not dirty_source


def _make_worktree(root: Path, path: Path, commit: str, sparse_paths=()):
    """优先 git worktree（保留 .git，可继续用 git 读对象）；失败退到 git archive。

    有稀疏清单时用 `--no-checkout` + sparse-checkout + checkout 三步：只把清单里的路径
    写进磁盘，不先铺一遍整棵树。清单为空（小仓库没有这些目录）时退回整树检出。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if _existing_worktree_ok(path, commit, sparse_paths):
            return "worktree", None
        # 只清理我们自己快照目录下的路径；绝不动仓库工作区。
        # 先让 git 注销 worktree（Windows 上文件可能被占用，直接 rmtree 会失败），
        # 再删目录；删不干净就别硬上 archive（会把新树铺在旧树上，产生"commit 对、
        # 内容却是旧版"的假快照）。
        run_git(["worktree", "remove", "--force", str(path)], cwd=root, check=False)
        shutil.rmtree(path, ignore_errors=True)
        if path.exists():
            return None, f"旧快照目录无法清理：{path}"
    run_git(["worktree", "prune"], cwd=root, check=False)
    add_args = ["worktree", "add"]
    if sparse_paths:
        add_args.append("--no-checkout")
    add_args += ["--detach", str(path), commit]
    proc = run_git(add_args, cwd=root, check=False, timeout=300)
    wt_error = None
    if proc.returncode == 0:
        if sparse_paths:
            steps = (
                ["sparse-checkout", "init", "--cone"],
                ["sparse-checkout", "set", *sparse_paths],
                ["checkout"],
            )
            for step in steps:
                sub = run_git(step, cwd=path, check=False, timeout=300)
                if sub.returncode != 0:
                    err = (sub.stderr or sub.stdout or "").strip().splitlines()
                    wt_error = (f"稀疏检出失败（git {' '.join(step)}）："
                                f"{err[-1] if err else sub.returncode}")
                    break
        if wt_error is None:
            head = run_git(["rev-parse", "HEAD"], cwd=path, check=False).stdout.strip()
            if head == commit:
                return "worktree", None
            wt_error = f"worktree 检出的 HEAD {head[:12]} 与目标 commit {commit[:12]} 不一致"
        # 失败后先注销 worktree 再退到 archive：不能把半成品留在快照目录里
        run_git(["worktree", "remove", "--force", str(path)], cwd=root, check=False)
        shutil.rmtree(path, ignore_errors=True)
    # 退路：git archive 展开（没有 worktree 元数据，但同样不改源工作区）。
    # 稀疏失败也走这里（例如 git 版本没有 sparse-checkout）：宁可退化成一次性、
    # 不复用的快照，也不要让整轮 groom 直接失败。
    archive_args = ["git", "archive", "--format=tar", commit]
    if sparse_paths:
        archive_args += list(sparse_paths)
    archive = subprocess.run(archive_args, cwd=str(root),
                             capture_output=True, timeout=300)
    if archive.returncode != 0:
        detail = (proc.stderr or "").strip() or archive.stderr.decode("utf-8", "replace")
        if wt_error:
            detail = f"{wt_error} / archive: {detail}"
        return None, f"worktree 与 archive 都失败：{detail}"
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        return None, f"archive 前无法清理快照目录：{path}"
    path.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as tar:
        tar.extractall(path)
    return "archive", None


def _ensure_index(worktree: Path):
    """索引必须与快照 commit 对得上。对不上就重建（只写快照目录，不写源工作区）。"""
    check = _run_py(worktree, INDEX_CHECK)
    if check.returncode == 0:
        return {"state": "verified", "detail": None}
    build = _run_py(worktree, INDEX_BUILD)
    if build.returncode != 0:
        detail = (build.stderr or build.stdout or "").strip().splitlines()
        return {"state": "unavailable", "detail": detail[-1] if detail else "build_index 失败"}
    recheck = _run_py(worktree, INDEX_CHECK)
    if recheck.returncode == 0:
        return {"state": "rebuilt", "detail": "快照内索引与 commit 不一致，已在快照内重建"}
    detail = (recheck.stderr or recheck.stdout or "").strip().splitlines()
    return {"state": "unavailable", "detail": detail[-1] if detail else "重建后仍不一致"}


def _source_worktree_state(root: Path):
    proc = run_git(["status", "--porcelain"], cwd=root, check=False)
    dirty = [l for l in (proc.stdout or "").splitlines() if l.strip()] if proc.returncode == 0 else []
    return dirty


def _prune(snapshot_dir: Path, keep: Path, root: Path):
    """清理旧快照 worktree；只删 snapshot_dir 之下、且不是本次 keep 的目录。"""
    removed = []
    if not snapshot_dir.is_dir():
        return removed
    for child in sorted(snapshot_dir.iterdir()):
        if not child.is_dir() or child == keep or child.name.startswith("."):
            continue
        # 有 .git 的先让 git 注销 worktree，避免源仓库留下悬空元数据
        if (child / ".git").exists():
            run_git(["worktree", "remove", "--force", str(child)], cwd=root, check=False)
        shutil.rmtree(child, ignore_errors=True)
        removed.append(child.name)
    run_git(["worktree", "prune"], cwd=root, check=False)
    return removed


def cleanup_snapshot(root: Path, snapshot_dir=None, branch="main", commit=None):
    """删掉一份快照的 worktree 与 per-commit JSON，`latest.json` 只标 `cleaned_at`。

    为什么用完就删：下一次 groom 会重新 fetch origin/main，commit 多半已经前进，
    留着的目录只是磁盘占用（本仓一份约 4.5 MB）。评估的过期判定靠 git 里的 commit
    比较（`assessed_commit` vs 目标 commit），与这份本地目录无关；只有「重跑 record」
    才需要它，所以清理放在收尾、不放在开头。

    保留 `latest.json`（约 2 KB）：它是"上一次 groom 比的是哪个 commit"的唯一记录，
    `groom_status --snapshot` 仍可用它复现目标版本；目录删掉后 `worktree_state=removed`。
    """
    root = Path(root).resolve()
    inbox = shared_inbox(root)
    snapshot_dir = Path(snapshot_dir).resolve() if snapshot_dir else (inbox / ".groom" / "snapshots")
    latest = snapshot_dir / "latest.json"
    if not commit:
        commit = (load_json(latest) or {}).get("commit") if latest.exists() else None
        if not commit:
            return {"ok": False, "error": "找不到可清理的 commit（没有 latest.json，也没显式指定）"}

    path = _worktree_path(snapshot_dir, branch, commit)
    result = {"ok": True, "commit": commit, "worktree_removed": False, "meta_removed": False}
    if path.exists():
        run_git(["worktree", "remove", "--force", str(path)], cwd=root, check=False)
        shutil.rmtree(path, ignore_errors=True)
        if path.exists():
            return {"ok": False, "error": f"快照目录无法删除：{path}", **result}
        result["worktree_removed"] = True
    run_git(["worktree", "prune"], cwd=root, check=False)

    meta_path = snapshot_dir / f"{branch.replace('/', '_')}-{short_sha(commit)}.json"
    if meta_path.exists():
        meta_path.unlink()
        result["meta_removed"] = True

    if latest.exists():
        doc = load_json(latest) or {}
        if doc.get("commit") == commit:
            doc["cleaned_at"] = now_iso()
            doc["worktree_state"] = "removed"
            atomic_write_text(latest, dump_json(doc))
    return result


def build_snapshot(root: Path, remote="origin", branch="main", snapshot_dir=None,
                   offline=False, require_fresh=False, prune=False):
    """返回 (meta, exit_code)。供 CLI 与测试共用。"""
    root = Path(root).resolve()
    inbox = shared_inbox(root)
    snapshot_dir = Path(snapshot_dir).resolve() if snapshot_dir else (inbox / ".groom" / "snapshots")

    allow_fetch, skip_reason = _fetch_policy(root, offline)
    if not allow_fetch:
        # 同步关闭 / 部署声明离线：不联网，用本机已有 ref；fresh=false、authoritative=false。
        fetched, fetch_error = False, skip_reason
    else:
        fetched, fetch_error = _fetch(root, remote, branch)
    if not fetched and allow_fetch:
        meta = {
            "schema": SCHEMA_SNAPSHOT, "ok": False, "repo": str(root),
            "branch": branch, "remote": remote,
            "fresh": False, "authoritative": False,
            "fetch_error": fetch_error, "created_at": now_iso(),
        }
        return meta, 2
    if require_fresh and not fetched:
        meta = {
            "schema": SCHEMA_SNAPSHOT, "ok": False, "repo": str(root),
            "branch": branch, "remote": remote,
            "fresh": False, "authoritative": False,
            "fetch_error": fetch_error, "created_at": now_iso(),
        }
        return meta, 2

    ref, commit, err = _resolve_commit(root, remote, branch, offline=offline or not fetched)
    if not commit:
        meta = {
            "schema": SCHEMA_SNAPSHOT, "ok": False, "repo": str(root),
            "branch": branch, "remote": remote,
            "fresh": False, "authoritative": False,
            "fetch_error": err, "created_at": now_iso(),
        }
        return meta, 2

    worktree = _worktree_path(snapshot_dir, branch, commit)
    requested = list(SNAPSHOT_SPARSE_PATHS)
    sparse_paths = _paths_in_commit(root, commit, requested)
    missing = [p for p in requested if p not in sparse_paths]
    if "knowledge" in missing:
        # 没有 knowledge/ 就没有任何可比的 case 与索引：直接失败，不产出"空但权威"的快照
        meta = {
            "schema": SCHEMA_SNAPSHOT, "ok": False, "repo": str(root),
            "branch": branch, "remote": remote,
            "commit": commit, "short": short_sha(commit),
            "fresh": fetched, "authoritative": False,
            "fetch_error": "该 commit 没有 knowledge/ 目录（或路径不可读），无法建知识快照",
            "created_at": now_iso(),
        }
        return meta, 2
    method, wt_error = _make_worktree(root, worktree, commit, sparse_paths)
    if not method:
        meta = {
            "schema": SCHEMA_SNAPSHOT, "ok": False, "repo": str(root),
            "branch": branch, "remote": remote,
            "commit": commit, "short": short_sha(commit),
            "fresh": fetched, "authoritative": False, "fetch_error": wt_error,
            "created_at": now_iso(),
        }
        return meta, 2

    index = _ensure_index(worktree)
    dirty = _source_worktree_state(root)
    drafts = find_drafts(inbox)
    authoritative = bool(fetched and index["state"] in ("verified", "rebuilt"))

    meta = {
        "schema": SCHEMA_SNAPSHOT,
        "ok": True,
        "repo": str(root),
        "branch": branch,
        "remote": remote,
        "ref": ref,
        "commit": commit,
        "short": short_sha(commit),
        "fetched_at": now_iso(),
        "fresh": bool(fetched),
        "authoritative": authoritative,
        "fetch_error": fetch_error,
        "worktree": str(worktree),
        "method": method,
        "checkout": {
            "mode": "sparse" if sparse_paths else "full",
            "paths": sparse_paths,
            "requested": requested,
            "missing": missing,
        },
        "index": index,
        "source_worktree_dirty": len(dirty) > 0,
        "source_worktree_dirty_count": len(dirty),
        "inbox_drafts": len(drafts),
        "inbox": str(inbox),
        "snapshot_dir": str(snapshot_dir),
        "created_at": now_iso(),
        "notes": (
            "fresh=a fetch 成功；authoritative=fresh 且索引可用。"
            "非 authoritative 的评估会带 promotion_blocked=stale-snapshot，不得据此升格。"
            "checkout.mode=sparse 时快照只物化索引的输入集，不是该 commit 的完整表示。"
        ),
    }
    meta_path = snapshot_dir / f"{branch.replace('/', '_')}-{short_sha(commit)}.json"
    atomic_write_text(meta_path, dump_json(meta))
    atomic_write_text(snapshot_dir / "latest.json", dump_json(meta))
    meta["meta_path"] = str(meta_path)

    removed = _prune(snapshot_dir, worktree, root) if prune else []
    if removed:
        meta["pruned"] = removed
        atomic_write_text(meta_path, dump_json(meta))
    return meta, 0


def print_summary(meta: dict):
    print("Groom 知识快照")
    print(f"  仓库    {meta.get('repo')}")
    print(f"  目标    {meta.get('remote')}/{meta.get('branch')} @ {meta.get('short')}")
    print(f"  快照    {meta.get('worktree')}（{meta.get('method')}）")
    checkout = meta.get("checkout") or {}
    if checkout:
        scope = " ".join(checkout.get("paths") or []) or "整树"
        print(f"  检出    {checkout.get('mode', 'full')}：{scope}")
        missing = checkout.get("missing") or []
        if missing:
            print(f"  缺输入  {' '.join(missing)} 在该 commit 不存在——"
                  "索引输入集不完整，排名可能静默降级（见 checkout.missing）")
    idx = meta.get("index") or {}
    print(f"  索引    {idx.get('state')}" + (f"：{idx.get('detail')}" if idx.get("detail") else ""))
    print(f"  新鲜度  {'fresh' if meta.get('fresh') else 'STALE（离线/本地引用）'}"
          f" · {'authoritative' if meta.get('authoritative') else 'NOT authoritative'}")
    if meta.get("fetch_error"):
        print(f"  同步    {meta['fetch_error']}")
    if meta.get("source_worktree_dirty"):
        print(f"  工作区  源工作区有未提交改动（{meta.get('source_worktree_dirty_count')} 项）——"
              "快照不受影响；不要 pull/merge 覆盖它们")
    print(f"  草稿    inbox 中 {meta.get('inbox_drafts')} 份")


def main():
    pin_utf8_stdio()
    ap = argparse.ArgumentParser(description="Groom 知识快照（fetch + 只读 worktree + 索引校验）")
    ap.add_argument("--repo", default=None, help="仓库路径（默认当前目录）")
    ap.add_argument("--list-remotes", action="store_true",
                    help="列出已配置远端名；多个远端时由 agent 问用户")
    ap.add_argument("--remote", default=None,
                    help="同步源远端名；默认取配置 sync.remote，缺省按本机远端（单个自动用，多个须先问）")
    ap.add_argument("--branch", default=None, help="分支名（默认取配置 sync.branch，再缺省 main）")
    ap.add_argument("--snapshot-dir", default=None,
                    help="快照根目录（默认：共享 inbox 的 .groom/snapshots）")
    ap.add_argument("--offline", action="store_true",
                    help="不 fetch，用本地已有引用；meta 标 fresh=false / authoritative=false")
    ap.add_argument("--require-fresh", action="store_true", help="fetch 失败即退出 2")
    ap.add_argument("--prune", action="store_true", help="建完后清理旧快照（只删快照目录下）")
    ap.add_argument("--cleanup", action="store_true",
                    help="删掉本次/最近一次快照的 worktree 与 per-commit JSON（groom 收尾用；"
                         "latest.json 保留并标 cleaned_at）")
    ap.add_argument("--cleanup-commit", default=None,
                    help="配合 --cleanup：指定要清理的 commit（默认取 latest.json）")
    ap.add_argument("--json", action="store_true", help="stdout 输出完整 meta JSON")
    args = ap.parse_args()

    root = Path(args.repo).resolve() if args.repo else Path.cwd()
    root = repo_root(root)
    cfg_remote, cfg_branch, _cfg_enabled, cfg_error = load_sync_settings(root)
    config_broken = bool(cfg_error)
    if cfg_error:
        # 配置损坏不报错退出：退回"没配置"的既有行为（问用户），只说明一句。
        # 也**不写回**选定远端——覆盖一份读不出的配置会把用户原来的设置抹掉。
        print(f"groom_snapshot: {cfg_error}（本次按未配置处理）", file=sys.stderr)
        cfg_remote = cfg_branch = None
    if not args.branch:
        args.branch = cfg_branch or "main"
    if args.cleanup:
        result = cleanup_snapshot(root, snapshot_dir=args.snapshot_dir, branch=args.branch,
                                  commit=args.cleanup_commit)
        if args.json:
            print(dump_json(result), end="")
        elif result.get("ok"):
            print(f"快照已清理：{result['commit'][:12]}"
                  f"（worktree {'已删' if result['worktree_removed'] else '不存在'} · "
                  f"meta {'已删' if result['meta_removed'] else '不存在'}）")
            print("  latest.json 保留（记录本次比的是哪个 commit）；下一次 groom 会重新 fetch 并重建快照。")
        else:
            print(f"groom_snapshot: 清理失败 —— {result.get('error')}", file=sys.stderr)
        return 0 if result.get("ok") else 3
    if args.list_remotes:
        remotes = list_remotes(root)
        if args.json:
            payload = {"schema": "groom-sync-sources/v1", "repo": str(root), "remotes": remotes}
            # 没有配置时不加字段：保持既有输出形状，调用方不必改。
            if cfg_remote or cfg_branch:
                payload["configured"] = {"remote": cfg_remote, "branch": cfg_branch}
            print(dump_json(payload), end="")
        else:
            print("可用的同步源（把远端名给用户，由用户确认从哪个更新）：")
            for r in remotes:
                print(f"  {r['name']}")
            if not remotes:
                print("  （没有配置远端；由用户决定 git remote add <name> <url>）")
            if cfg_remote:
                suffix = f"（分支 {cfg_branch}）" if cfg_branch else ""
                print(f"  配置里的同步源：{cfg_remote}{suffix}——有配置时直接用，不必再选。")
        return 0
    if not args.remote and cfg_remote:
        args.remote = cfg_remote
        print(f"groom_snapshot: 同步源取自 .local/settings.json（sync.remote={cfg_remote}）。",
              file=sys.stderr)
    if not args.remote:
        names = [r["name"] for r in list_remotes(root)]
        if len(names) == 1:
            args.remote = names[0]
            print(f"groom_snapshot: 只有一个远端，使用 {args.remote}。", file=sys.stderr)
        elif not names:
            print("groom_snapshot: 没有配置远端；先由用户决定 git remote add <name> <url>。",
                  file=sys.stderr)
            return 3
        else:
            print("groom_snapshot: 有多个远端，先跑 --list-remotes 并让用户确认，"
                  "再用 --remote <name>。", file=sys.stderr)
            return 3
    if cfg_remote is None and not config_broken:
        # 配置里没有可用同步源，本次的远端是用户选的（--remote 或唯一远端）：写回一次。
        written, why = persist_sync_source(root, args.remote, args.branch)
        if written:
            print(f"groom_snapshot: 已把选定的同步源写回 .local/settings.json"
                  f"（{args.remote}/{args.branch}）。", file=sys.stderr)
        else:
            print(f"groom_snapshot: 选定的同步源写回 .local/settings.json 失败（{why}）；"
                  "本次照常建快照。", file=sys.stderr)
    allow_fetch, skip_reason = _fetch_policy(root, args.offline)
    meta, rc = build_snapshot(
        root, remote=args.remote, branch=args.branch, snapshot_dir=args.snapshot_dir,
        offline=args.offline, require_fresh=args.require_fresh, prune=args.prune,
    )
    if args.json:
        print(dump_json(meta), end="")
    elif rc == 0:
        print_summary(meta)
    elif not allow_fetch:
        print(f"groom_snapshot: 未 fetch（{skip_reason}）——--require-fresh 无法满足；"
              "去掉它可用本机已有引用建快照（结果标记为非权威）。", file=sys.stderr)
    else:
        print(f"groom_snapshot: 同步失败 —— {meta.get('fetch_error')}", file=sys.stderr)
        if not args.offline:
            print("  确认网络/权限后重试；确实要离线评估就显式加 --offline（结果标记为非权威）。",
                  file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
