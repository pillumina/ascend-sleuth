#!/usr/bin/env python3
"""ref_origin.py —— 词条的产出处：从 git 取「哪次提交、哪次合并（PR）把它带进来的」

**为什么需要**：reference 词条是随 PR 合入的，但词条本身没有「产出处」字段（也不该有——
PR 号在产出时还不知道，手写一份只会长期为空或写错）。git 已经记着这件事：文件是在哪次
提交里出现的、第一次出现在哪次合并里。把这个查询固化成一条命令，比在 YAML 里加一个没人
回填的字段可靠；换台机器、换个人，只要还有提交历史就能查。

**它回答什么**：
- 文件级：这条词条第一次出现的提交，以及把它带进当前分支的第一次合并（消息里通常带 PR 号）；
- 表内条目（error-code / fault-pattern 这类一族一个文件的）：按 id 在补丁里第一次出现定位
  到「加这一行」的提交；文件首次提交里就有的，退回文件级。

**它不做什么**：不判断词条内容对不对、不改任何文件、不联网。词条没有提交历史（复制进来
未提交、浅克隆截断）时如实报「查不到」，不拿文件修改时间或作者猜。

用法：

  python3 scripts/ref_origin.py <ref-id>
  python3 scripts/ref_origin.py references/tools/msprobe-compare.yaml --json
  python3 scripts/ref_origin.py <ref-id> --root <检出>

退出码：0 成功；2 参数不对或查不到；3 git 不可用。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _yaml import load_file  # noqa: E402
from verify_references import is_entry_file  # noqa: E402

PR_RE = re.compile(r"(?:pull request|merge request)\s+[#!](\d+)|(?:^|\s)[#!](\d+)\b", re.I)


class OriginError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def git(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except OSError as exc:
        raise OriginError("E_GIT", "跑不了 git：" + str(exc))
    if proc.returncode != 0:
        raise OriginError("E_GIT", (proc.stderr or proc.stdout or "git 失败").strip())
    return proc.stdout


def entries(refs_dir: Path) -> dict[str, Path]:
    """id → 词条文件。`is_entry_file` 与 `verify_references.py` 同口径（跳过生成物）。"""
    out = {}
    for path in sorted(refs_dir.rglob("*.yaml")):
        if not is_entry_file(path):
            continue
        doc = load_file(path)
        rid = doc.get("id") if isinstance(doc, dict) else None
        if rid:
            out[str(rid)] = path
    return out


def _row_hit(doc, target: str) -> bool:
    """表内条目：任一层的 `code` / `pattern` / `name` / `id` 等于目标。"""
    if isinstance(doc, dict):
        for key in ("code", "pattern", "name", "id"):
            if key in doc and str(doc[key]) == target:
                return True
        return any(_row_hit(v, target) for v in doc.values())
    if isinstance(doc, list):
        return any(_row_hit(v, target) for v in doc)
    return False


def resolve(refs_dir: Path, target: str) -> tuple[str, Path]:
    """`<ref-id>`、表内条目 code / pattern、或词条文件路径 → (id, path)。"""
    p = Path(target)
    if p.suffix in (".yaml", ".yml"):
        p = p.resolve()
        if not p.exists():
            raise OriginError("E_NOT_FOUND", f"文件不存在：{p}")
        doc = load_file(p)
        rid = str(doc.get("id") or "") if isinstance(doc, dict) else ""
        if not rid:
            raise OriginError("E_NOT_FOUND", f"{target} 不是词条文件（没有 id）")
        return rid, p
    found = entries(refs_dir)
    if target in found:
        return target, found[target]
    # 顶层 id 查不到 → 按表内条目找（error-code 的 code、fault-pattern 的 pattern 等）。
    hits = [path for path in found.values() if _row_hit(load_file(path), target)]
    if len(hits) == 1:
        return target, hits[0]
    if len(hits) > 1:
        raise OriginError(
            "E_NOT_FOUND",
            f"'{target}' 同时出现在多个词条文件里：" + "、".join(str(h.relative_to(refs_dir.parent)) for h in hits)
            + "。传词条 id 或文件路径来消歧。",
        )
    raise OriginError(
        "E_NOT_FOUND",
        f"references/ 里没有 id 为 {target} 的词条，也没有哪张表里有这个 code / pattern"
        f"（{len(found)} 条里没有）。",
    )


def parse_pr(subject: str) -> str | None:
    m = PR_RE.search(subject or "")
    if not m:
        return None
    return "#" + (m.group(1) or m.group(2))


def _log_or_empty(root: Path, *args: str) -> str:
    """git log 在路径未被跟踪时会以 pathspec 报错；对「查不到」按空历史处理。"""
    try:
        return git(root, *args)
    except OriginError as exc:
        if any(x in exc.message for x in ("pathspec", "does not exist", "unknown revision",
                                         "does not have any commits", "ambiguous argument")):
            return ""
        raise


def _ere_escape(text: str) -> str:
    """转义 ERE 元字符；连字符在括号外是字面量，不转义（`\\-` 在部分 grep 实现里不认）。"""
    return re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", text)


def _row_search_regex(key: str, ref_id: str) -> str:
    # 只认「键: 值」形态（块写法 `- code: '2'` 与 flow 写法 `{code: '2', ...}`），
    # 不按出现次数搜（`-S <id>`）：短 code 会命中日期、版本号等无关行，把文件首次加入误报成加行。
    return (r"(^|[[:space:]{,])" + key + r":[[:space:]]*[\"']?"
            + _ere_escape(ref_id) + r"[\"']?([[:space:],}]|$)")


def _shallow_boundaries(root: Path) -> set[str]:
    """浅克隆的截断点。落在截断点上的「首次加入」不可信：父提交不在本地。"""
    try:
        out = git(root, "rev-parse", "--git-path", "shallow").strip()
    except OriginError:
        return set()
    if not out:
        return set()
    p = Path(out)
    if not p.is_absolute():
        p = root / p
    try:
        return {line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()}
    except OSError:
        return set()


def commit_at(root: Path, path: Path, ref_id: str, row_level: bool) -> dict:
    root = root.resolve()
    path = path.resolve()
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        raise OriginError("E_NOT_FOUND", f"{path} 不在检出 {root} 里——传检出内的词条路径")
    # 文件第一次出现：`--diff-filter=A` 只认新增；`--reverse` 让最早的一条在最前。
    out = _log_or_empty(root, "log", "--reverse", "--diff-filter=A", "--date=short",
                        "--format=%H%x09%ad%x09%s", "--", rel)
    added = [line.split("\t", 2) for line in out.splitlines() if line.strip()]
    meta = None
    if added:
        sha, date, subject = added[0]
        meta = {"sha": sha, "short": sha[:8], "date": date, "subject": subject, "level": "file"}
    shallow = _shallow_boundaries(root)
    if meta and meta["sha"] in shallow:
        raise OriginError(
            "E_NOT_FOUND",
            f"{rel} 的首次加入落在浅克隆截断点（{meta['short']}）；父提交不在本地，查不到真正的加入提交。换完整克隆再查",
        )
    if row_level:
        # 表内条目：按条目键找「这一行第一次出现」的提交；取不到就退回文件级。
        rows = []
        for key in ("code", "pattern", "name", "id"):
            out = _log_or_empty(root, "log", "--reverse", "-G", _row_search_regex(key, ref_id),
                                "--date=short", "--format=%H%x09%ad%x09%s", "--", rel)
            rows = [line.split("\t", 2) for line in out.splitlines() if line.strip()]
            if rows:
                break
        if not rows:
            raise OriginError(
                "E_NOT_FOUND",
                f"{rel} 的已提交历史里没有找到 {ref_id} 这一行（未提交的表内新行，或这一行不在 code/pattern/name/id 键下）",
            )
        if rows[0][0] in shallow:
            raise OriginError(
                "E_NOT_FOUND",
                f"{rel} 里 {ref_id} 这一行的加入落在浅克隆截断点（{rows[0][0][:8]}）；换完整克隆再查",
            )
        # 行与文件同一次提交加入时仍按文件级报：`-G` 从空文件看到这一行，
        # 会把「文件首次加入」标成「表内首次出现」，读起来像两次动作。
        if meta is None or rows[0][0] != meta["sha"]:
            sha, date, subject = rows[0]
            meta = {"sha": sha, "short": sha[:8], "date": date, "subject": subject, "level": "row"}
    if meta is None:
        raise OriginError("E_NOT_FOUND", f"{rel} 在 git 历史里没有新增提交（未提交 / 浅克隆截断 / 文件被复制进来）")
    return meta


def merge_of(root: Path, sha: str) -> dict | None:
    """把提交带进当前分支的第一次合并。不在当前分支历史里（未合入）时返回 None。"""
    try:
        out = git(root, "log", "--merges", "--reverse", "--ancestry-path",
                  f"{sha}..HEAD", "--format=%H%x09%s")
    except OriginError:
        return None
    rows = [line.split("\t", 1) for line in out.splitlines() if line.strip()]
    if not rows:
        return None
    msha, subject = rows[0]
    return {"sha": msha, "short": msha[:8], "subject": subject, "pr": parse_pr(subject)}


def lookup(root: Path, target: str) -> dict:
    root = root.resolve()
    refs_dir = root / "references"
    if not refs_dir.is_dir():
        raise OriginError("E_NOT_FOUND", f"检出里没有 references/：{refs_dir}")
    ref_id, path = resolve(refs_dir, target)
    doc = load_file(path)
    top_id = str(doc.get("id") or "") if isinstance(doc, dict) else ""
    # 表内条目：顶层 id 与请求的 id 不同（如请求 507903、文件 id 是 cann-runtime-error-codes）。
    row_level = bool(top_id and top_id != ref_id)
    meta = commit_at(root, path, ref_id, row_level)
    merged = merge_of(root, meta["sha"])
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        raise OriginError("E_NOT_FOUND", f"{path} 不在检出 {root} 里——传检出内的词条路径")
    return {
        "ok": True,
        "id": ref_id,
        "path": rel,
        "added": meta,
        "merge": merged,
        "pr": (merged or {}).get("pr"),
    }


def print_human(row: dict) -> None:
    print(f"{row['id']}  ({row['path']})")
    added = row["added"]
    place = "表内条目首次出现" if added["level"] == "row" else "文件首次加入"
    print(f"  加入  {added['short']}  {added['date']}  {added['subject']}  [{place}]")
    merged = row["merge"]
    if merged:
        print(f"  合入  {merged['short']}  {merged['subject']}")
        print(f"  PR    {merged['pr'] or '（合并消息里没有 PR 号）'}")
    else:
        print("  合入  （当前分支历史里没有合并提交：未合入，或直接提交到主干）")
        print("  PR    （未知）")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="词条的产出处：从 git 取加入提交与合并 PR")
    ap.add_argument("target", help="词条 id，或词条文件路径")
    ap.add_argument("--root", default=None, help="仓库根（默认脚本上一级）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    try:
        row = lookup(root, args.target)
    except OriginError as exc:
        if args.json:
            print(json.dumps({"ok": False, "code": exc.code, "message": exc.message}, ensure_ascii=False))
        else:
            print(exc.message, file=sys.stderr)
        return 3 if exc.code == "E_GIT" else 2
    if args.json:
        print(json.dumps(row, ensure_ascii=False, indent=2))
    else:
        print_human(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
