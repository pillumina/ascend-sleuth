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
#   - fetch 失败时**默认失败退出（2）**；只有显式 `--offline` 才用本地已有引用，
#     并标 `fresh: false, authoritative: false`。stale 数据不会被静默当成权威。
#   - 不修改源工作区：worktree 是另一个目录；源工作区的本地改动与未跟踪 inbox 均不变。
#
# 用法：
#   python3 scripts/groom_snapshot.py --list-remotes          # 多个远端时让用户选；只有一个可跳过
#   python3 scripts/groom_snapshot.py --remote origin --require-fresh  # 只有一个时可省略 --remote
#   python3 scripts/groom_snapshot.py --remote origin --json   # 同上，stdout 输出 meta JSON
#   python3 scripts/groom_snapshot.py --remote origin --offline  # 用本地已有引用，显式降级
#   python3 scripts/groom_snapshot.py --prune                 # 清理旧的 groom 快照 worktree
#
# 退出码：0 = 快照可用；2 = 同步失败 / 索引不可用 / --require-fresh 不满足；3 = 用法错误。

import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from _stdio import pin_utf8_stdio
from groom_common import (
    SCHEMA_SNAPSHOT, atomic_write_text, dump_json, find_drafts, now_iso, repo_root,
    run_git, shared_inbox, short_sha,
)

INDEX_CHECK = ["scripts/build_index.py", "--check"]
INDEX_BUILD = ["scripts/build_index.py"]


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


def _existing_worktree_ok(path: Path, commit: str) -> bool:
    """可复用 = HEAD 对 + 没有**源文件**改动。

    快照内重建索引会写 `knowledge/_index*`，那是预期副作用；除它之外的 tracked/untracked
    改动（尤其是 `knowledge/**/*.yaml` Case 本体）意味着这棵树已经不是该 commit 的
    权威表示，必须重建。否则下一个 groom 会把被改过的 Case 当成 origin/main 的内容。
    """
    if not (path / ".git").exists():
        return False
    proc = run_git(["rev-parse", "HEAD"], cwd=path, check=False)
    if proc.returncode != 0 or proc.stdout.strip() != commit:
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


def _make_worktree(root: Path, path: Path, commit: str):
    """优先 git worktree（保留 .git，可继续用 git 读对象）；失败退到 git archive。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if _existing_worktree_ok(path, commit):
            return "worktree", None
        # 只清理我们自己快照目录下的路径；绝不动仓库工作区。
        # 先让 git 注销 worktree（Windows 上文件可能被占用，直接 rmtree 会失败），
        # 再删目录；删不干净就别硬上 archive（会把新树铺在旧树上，产生"commit 对、
        # 内容却是旧版"的假快照）。
        run_git(["worktree", "remove", "--force", str(path)], cwd=root, check=False)
        shutil.rmtree(path, ignore_errors=True)
        if path.exists():
            return None, f"旧快照目录无法清理：{path}"
    proc = run_git(["worktree", "prune"], cwd=root, check=False)
    proc = run_git(["worktree", "add", "--detach", str(path), commit], cwd=root, check=False, timeout=300)
    if proc.returncode == 0:
        head = run_git(["rev-parse", "HEAD"], cwd=path, check=False).stdout.strip()
        if head != commit:
            return None, f"worktree 检出的 HEAD {head[:12]} 与目标 commit {commit[:12]} 不一致"
        return "worktree", None
    # 退路：git archive 展开（没有 worktree 元数据，但同样不改源工作区）
    archive = subprocess.run(["git", "archive", "--format=tar", commit], cwd=str(root),
                             capture_output=True, timeout=300)
    if archive.returncode != 0:
        return None, f"worktree 与 archive 都失败：{proc.stderr.strip() or archive.stderr.decode('utf-8', 'replace')}"
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


def build_snapshot(root: Path, remote="origin", branch="main", snapshot_dir=None,
                   offline=False, require_fresh=False, prune=False):
    """返回 (meta, exit_code)。供 CLI 与测试共用。"""
    root = Path(root).resolve()
    inbox = shared_inbox(root)
    snapshot_dir = Path(snapshot_dir).resolve() if snapshot_dir else (inbox / ".groom" / "snapshots")

    fetched, fetch_error = (False, "offline 模式：未尝试 fetch") if offline else _fetch(root, remote, branch)
    if not fetched and not offline:
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
    method, wt_error = _make_worktree(root, worktree, commit)
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
                    help="同步源远端名；只有一个远端时可省略，多个时必须先问用户")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--snapshot-dir", default=None,
                    help="快照根目录（默认：共享 inbox 的 .groom/snapshots）")
    ap.add_argument("--offline", action="store_true",
                    help="不 fetch，用本地已有引用；meta 标 fresh=false / authoritative=false")
    ap.add_argument("--require-fresh", action="store_true", help="fetch 失败即退出 2")
    ap.add_argument("--prune", action="store_true", help="建完后清理旧快照（只删快照目录下）")
    ap.add_argument("--json", action="store_true", help="stdout 输出完整 meta JSON")
    args = ap.parse_args()

    root = Path(args.repo).resolve() if args.repo else Path.cwd()
    root = repo_root(root)
    if args.list_remotes:
        remotes = list_remotes(root)
        if args.json:
            print(dump_json({"schema": "groom-sync-sources/v1", "repo": str(root),
                             "remotes": remotes}), end="")
        else:
            print("可用的同步源（把远端名给用户，由用户确认从哪个更新）：")
            for r in remotes:
                print(f"  {r['name']}")
            if not remotes:
                print("  （没有配置远端；由用户决定 git remote add <name> <url>）")
        return 0
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
    meta, rc = build_snapshot(
        root, remote=args.remote, branch=args.branch, snapshot_dir=args.snapshot_dir,
        offline=args.offline, require_fresh=args.require_fresh, prune=args.prune,
    )
    if args.json:
        print(dump_json(meta), end="")
    elif rc == 0:
        print_summary(meta)
    else:
        print(f"groom_snapshot: 同步失败 —— {meta.get('fetch_error')}", file=sys.stderr)
        if not args.offline:
            print("  确认网络/权限后重试；确实要离线评估就显式加 --offline（结果标记为非权威）。",
                  file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
