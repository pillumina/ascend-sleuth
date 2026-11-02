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


def changed_cases(root: Path, rev: str) -> list[dict]:
    """知识库在 `rev..HEAD` 与工作区的改动 → [{id, path, how}]，按 id/path 去重。"""
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def add(text: str, path: str, how: str):
        for cid in case_ids_in_text(text):
            key = (cid, path, how)
            if key not in seen:
                seen.add(key)
                out.append({"id": cid, "path": path, "how": how})

    diff = git(root, "diff", "--name-status", f"{rev}..HEAD", "--", "knowledge/")
    for line in (diff or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith(("R", "C")) and len(parts) >= 3:
            add(text_at(root, rev, parts[1]), parts[1], "committed")
            add(text_at(root, "HEAD", parts[2]), parts[2], "committed")
        elif status == "D":
            add(text_at(root, rev, parts[1]), parts[1], "committed")
        elif status == "A":
            add(text_at(root, "HEAD", parts[1]), parts[1], "committed")
        else:
            # 修改：旧 content 也要看——case id 可能被原地改名，只读新内容会漏掉旧 id。
            add(text_at(root, rev, parts[1]), parts[1], "committed")
            add(text_at(root, "HEAD", parts[1]), parts[1], "committed")

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


def scan(root: Path, traces: Path, only: str | None) -> dict:
    terminal = terminal_statuses(root)
    changed_cache: dict[str, list[dict]] = {}
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
        if rev not in changed_cache:
            if git(root, "rev-parse", "--verify", f"{rev}^{{commit}}") is None:
                bad_revs.add(rev)
                uncomparable += 1
                continue
            changed_cache[rev] = changed_cases(root, rev)
        touched = touched_cases(doc)
        hits = [c for c in changed_cache[rev] if c["id"] in touched]
        if hits:
            sessions.append({
                "sessionId": row["sessionId"],
                "status": status,
                "kbRev": rev,
                "dirty": doc.get("kb_rev_dirty") in (True, "true"),
                "cases": hits,
            })
    return {"sessions": sessions, "uncomparable": uncomparable, "terminalSkipped": skipped}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="诊断续接时的知识库漂移检查（只读）")
    ap.add_argument("--root", default=None, help="仓库根（默认脚本上一级）")
    ap.add_argument("--traces", default=None, help="traces 目录（默认由主检出解析）")
    ap.add_argument("--session", default=None, help="只看一单")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="有漂移退 1")
    args = ap.parse_args(argv)

    script_root = Path(__file__).resolve().parents[1]
    traces = Path(args.traces) if args.traces else resolve_traces(script_root)
    # 默认拿 traces 所在检出当 root：trace 的 kb_rev 是建单那台机器的 HEAD，不是脚本所在 worktree 的。
    root = Path(args.root).resolve() if args.root else traces.parent
    if not traces.is_dir():
        print(f"traces 目录不存在：{traces}", file=sys.stderr)
        return 3
    result = scan(root, traces, args.session)
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
        if result["uncomparable"]:
            print(f"  不可比 {result['uncomparable']} 单（没有 kb_rev 或版本不在本检出）。")
    if args.check and result["sessions"]:
        return 1
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
