#!/usr/bin/env python3
"""kb_drift.py —— 续接一单时，查它用过的 case 在知识库里变了没有（只读）。

为什么需要：诊断可能被会议、上下文压缩或换机打断，隔几天再续。这期间 `knowledge/` 下
合入了新 case、改了旧 case，续接方却仍按 trace 记的旧现场往下走。trace 顶层有 `kb_rev`
（这一单跑在哪一版知识库上），但此前只有跨机导入一个读端；本机续接不比对。

做法：对每份**非终态** trace，拿 `kb_rev` 与本机 HEAD 比：
  - `git diff <kb_rev>..HEAD -- knowledge/` 取已合入的改动；
  - `git status --porcelain -- knowledge/` 取工作区未提交的改动；
  - 把改动文件里的 case id 与本单触达过的 case（`active_case` / `excluded_cases` /
    `hit.case` / `considered_candidates`）求交。
有交集就打印「这单用过的 case 变了」，不写 trace、不改状态、不判断原结论是否还成立。

用法：
  python3 scripts/kb_drift.py                 # 扫全部在途 trace
  python3 scripts/kb_drift.py --session <id>  # 只看一单（resume 第一屏用）
  python3 scripts/kb_drift.py --json          # 机器可读
  python3 scripts/kb_drift.py --check         # 有漂移退 1（供脚本判）

退出码：0 = 正常（无漂移或有漂移但未给 --check）；1 = --check 且有漂移；2 = 参数不合法；
        3 = traces 目录读不到。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kb_sync  # noqa: E402  （默认先 fetch；失败降级，不阻塞续接）
from _trace_state import case_kind, load_traces, load_vocab  # noqa: E402
from _yaml import load_text  # noqa: E402
from exec_log_path import resolve_traces  # noqa: E402


def git(root: Path, *args: str):
    """跑一条 git 命令；拿不到（无 git / 超时 / 非零）返回 None，不抛。"""
    try:
        r = subprocess.run(["git", "-C", str(root), *args],
                           capture_output=True, text=True, timeout=30,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout or ""


def text_at(root: Path, rev: str, path: str):
    """读某个版本的 `path` 内容；读不到返回空串。"""
    return git(root, "show", f"{rev}:{path}") or ""


def case_ids_in_text(text: str) -> list[str]:
    """case 文件里的 id（顶层 `cases:` 列表）。解析不了按空处理，不猜。"""
    try:
        doc = load_text(text) or {}
    except Exception:
        return []
    if not isinstance(doc, dict):
        return []
    return [str(c["id"]) for c in (doc.get("cases") or [])
            if isinstance(c, dict) and c.get("id")]


def changed_cases(root: Path, rev: str, to_rev: str = "HEAD") -> list[dict]:
    """知识库在 `rev..to_rev` 与工作区的改动 → [{id, path, how}]，按 id/path 去重。

    `to_rev` 默认 HEAD（旧 trace 的比对目标）；带 `kb_remote_rev` 的新 trace 传本机远端
    分支 ref，比的是远端已合入的内容，而不是当前检出。
    """
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def add(text: str, path: str, how: str):
        for cid in case_ids_in_text(text):
            key = (cid, path, how)
            if key not in seen:
                seen.add(key)
                out.append({"id": cid, "path": path, "how": how})

    diff = git(root, "diff", "--name-status", f"{rev}..{to_rev}", "--", "knowledge/")
    for line in (diff or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith(("R", "C")) and len(parts) >= 3:
            add(text_at(root, rev, parts[1]), parts[1], "committed")
            add(text_at(root, to_rev, parts[2]), parts[2], "committed")
        elif status == "D":
            add(text_at(root, rev, parts[1]), parts[1], "committed")
        elif status == "A":
            add(text_at(root, to_rev, parts[1]), parts[1], "committed")
        else:
            # 修改：旧 content 也要看——case id 可能被原地改名，只读新内容会漏掉旧 id。
            add(text_at(root, rev, parts[1]), parts[1], "committed")
            add(text_at(root, to_rev, parts[1]), parts[1], "committed")

    # 工作区：未提交的修改与新增文件（git diff 只看已提交区间）。
    for line in (git(root, "status", "--porcelain", "--", "knowledge/") or "").splitlines():
        if len(line) < 4:
            continue
        raw = line[3:].strip()
        if not raw:
            continue
        if " -> " in raw:
            old, new_path = raw.split(" -> ", 1)
            add(text_at(root, "HEAD", old), old, "working-tree")
            file = root / new_path
            if file.is_file():
                try:
                    add(file.read_text(encoding="utf-8"), new_path, "working-tree")
                except OSError:
                    pass
            continue
        if line[0] == "D" or line[1] == "D":
            add(text_at(root, "HEAD", raw), raw, "working-tree")
        else:
            add(text_at(root, "HEAD", raw), raw, "working-tree")
            file = root / raw
            if file.is_file():
                try:
                    add(file.read_text(encoding="utf-8"), raw, "working-tree")
                except OSError:
                    pass
    return out


def touched_cases(doc: dict) -> set[str]:
    """本单触达过的 case id（只认真 case，占位串与空值不计）。"""
    ids: set[str] = set()
    for value in (doc.get("active_case"),):
        if case_kind(value) == "case":
            ids.add(str(value))
    for value in doc.get("excluded_cases") or []:
        if case_kind(value) == "case":
            ids.add(str(value))
    sed = doc.get("sedimented")
    if isinstance(sed, dict) and case_kind(sed.get("case_id")) == "case":
        ids.add(str(sed["case_id"]))
    for ev in doc.get("trace") or []:
        if not isinstance(ev, dict):
            continue
        if case_kind(ev.get("case")) == "case":
            ids.add(str(ev["case"]))
        for value in ev.get("considered_candidates") or []:
            if case_kind(value) == "case":
                ids.add(str(value))
    return ids


def terminal_statuses(root: Path) -> set[str]:
    """终态状态值（数据在 `trace-status.yaml`，不写死）。"""
    vocab = load_vocab(root)
    return {s["value"] for s in vocab["statuses"] if s.get("terminal")}


def remote_target(root: Path, doc: dict, default_remote: str, default_branch: str):
    """trace 的比对目标 ref：远端分支优先，其次 trace 记的远端短 sha；都没有返回 None。"""
    raw = str(doc.get("kb_remote") or "").strip()
    if "/" in raw:
        remote, branch = raw.split("/", 1)
    else:
        remote = raw or default_remote
        branch = default_branch
    ref = f"{remote}/{branch}" if remote and branch else ""
    if ref and git(root, "rev-parse", "--verify", f"{ref}^{{commit}}") is not None:
        return ref
    recorded = str(doc.get("kb_remote_rev") or "").strip()
    if recorded and recorded not in ("unknown", "null") \
            and git(root, "rev-parse", "--verify", f"{recorded}^{{commit}}") is not None:
        return recorded
    return None


def scan(root: Path, traces: Path, only: str | None, *, fetch: bool = True) -> dict:
    settings, _config, _problem = kb_sync.load_settings(root)
    default_remote = str(settings["sync"]["remote"])
    default_branch = str(settings["sync"]["branch"])
    remote_ref = f"{default_remote}/{default_branch}"
    fetch_info = {"ok": False, "reason": "no-fetch", "remote": default_remote,
                  "branch": default_branch, "remote_ref": remote_ref, "offline": False}
    if fetch:
        result = kb_sync.sync(root, do_merge=False)
        behind = result.get("behind")
        fetch_info = {
            "ok": bool(result.get("ok")),
            "reason": str(result.get("reason") or ""),
            "remote": str(result.get("remote") or default_remote),
            "branch": str(result.get("branch") or default_branch),
            "remote_ref": remote_ref,
            "offline": bool(result.get("offline")),
            "behind": behind if isinstance(behind, int) else None,
        }
    terminal = terminal_statuses(root)
    changed_cache: dict[tuple[str, str], list[dict]] = {}
    bad_revs: set[str] = set()
    sessions, uncomparable, skipped = [], 0, 0
    for row in load_traces(traces):
        doc = row.get("doc") or {}
        status = str(doc.get("status") or "unknown")
        if status in terminal:
            skipped += 1
            continue
        if only and row["sessionId"] != only:
            continue
        rev = str(doc.get("kb_rev") or "").strip()
        if not rev or rev == "unknown":
            uncomparable += 1
            continue
        if rev in bad_revs:
            uncomparable += 1
            continue
        recorded_remote = str(doc.get("kb_remote_rev") or "").strip()
        target_ref = "HEAD"
        if recorded_remote and recorded_remote not in ("unknown", "null"):
            target_ref = remote_target(root, doc, default_remote, default_branch)
            if target_ref is None:
                uncomparable += 1
                continue
        key = (rev, target_ref)
        if key not in changed_cache:
            if git(root, "rev-parse", "--verify", f"{rev}^{{commit}}") is None:
                bad_revs.add(rev)
                uncomparable += 1
                continue
            changed_cache[key] = changed_cases(root, rev, target_ref)
        touched = touched_cases(doc)
        hits = [c for c in changed_cache[key] if c["id"] in touched]
        if hits:
            sessions.append({
                "sessionId": row["sessionId"],
                "status": status,
                "kbRev": rev,
                "targetRev": target_ref,
                "dirty": doc.get("kb_rev_dirty") in (True, "true"),
                "cases": hits,
            })
    return {"sessions": sessions, "uncomparable": uncomparable, "terminalSkipped": skipped,
            "fetch": fetch_info}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="诊断续接时的知识库漂移检查（只读）")
    ap.add_argument("--root", default=None, help="仓库根（默认脚本上一级）")
    ap.add_argument("--traces", default=None, help="traces 目录（默认由主检出解析）")
    ap.add_argument("--session", default=None, help="只看一单")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="有漂移退 1")
    ap.add_argument("--no-fetch", action="store_true", help="不 fetch，用本机已有的远端 ref")
    args = ap.parse_args(argv)

    script_root = Path(__file__).resolve().parents[1]
    traces = Path(args.traces) if args.traces else resolve_traces(script_root)
    # 默认拿 traces 所在检出当 root：trace 的 kb_rev 是建单那台机器的 HEAD，不是脚本所在 worktree 的。
    root = Path(args.root).resolve() if args.root else traces.parent
    if not traces.is_dir():
        print(f"traces 目录不存在：{traces}", file=sys.stderr)
        return 3
    result = scan(root, traces, args.session, fetch=not args.no_fetch)
    if args.json:
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    else:
        if result["sessions"]:
            print(f"知识库漂移：{len(result['sessions'])} 单在途诊断用过的 case 变了")
            for row in result["sessions"]:
                print(f"  {row['sessionId']}（kb_rev {row['kbRev']}）")
                for case in row["cases"]:
                    where = "已合入" if case["how"] == "committed" else "工作区未提交"
                    print(f"    {case['id']}  {case['path']}（{where}）")
                if row.get("dirty"):
                    print("    注意：这单建单时工作区有未提交改动，版本比对只能到提交；未提交部分不可回溯。")
            print("  提示：只说明这条 case 变了；原结论是否还成立要按新内容重验，不自动改状态。")
        elif args.session:
            print(f"{args.session} 没有可比的在途漂移（已收尾、无 kb_rev 或不在 traces/）。")
        else:
            print("知识库漂移：没有在途诊断的 case 发生变化。")
        fetch = result.get("fetch") or {}
        if not args.no_fetch and not fetch.get("ok"):
            print(f"  知识库远端：本次 fetch 未完成（{kb_sync.fetch_reason_text(fetch.get('reason'))}），"
                  f"按本机已有的 ref 比对。")
        behind = fetch.get("behind")
        if not args.no_fetch and fetch.get("ok") and isinstance(behind, int) and behind > 0:
            print(f"  本机知识库落后 {behind} 个提交（未同步）；远端合入的 case 变化要同步后才会出现在上面。")
            print("  同步：python3 scripts/kb_sync.py --merge")
        if result["uncomparable"]:
            print(f"  不可比 {result['uncomparable']} 单（没有 kb_rev、版本不在本检出，"
                  f"或有 kb_remote_rev 但本机没有对应 ref）。")
    if args.check and result["sessions"]:
        return 1
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
