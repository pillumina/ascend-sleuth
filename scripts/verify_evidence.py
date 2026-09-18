#!/usr/bin/env python3
# verify_evidence.py —— 引文回验：把"引用原文是否与原件逐字一致"变成脚本可判
#
# 为什么存在：报告契约要求"每个结论都指回一条证据"，但"指回去了"与"引文与原件一致"
# 是两件事——后者此前只是人审项（report_lint.py 只查结构：必需节、字段配对、路径存在）。
# 引文被顺手改写、行号在长文件里漂移，两类错都不会报错，只会让下一个人拿着错的原文去找。
# 本脚本只做一件事：把 trace 里**带了原件**的引文（`user` 事件 evidence.quotes）
# 重读原件逐行比对。
#
# 判据（刻意收紧）：
#   · 逐字相等，只做空白归一化（连续空白折成一个空格、去首尾空白）；
#   · 长行截断必须显式标 `...`：按 `...` 切段，要求各段**按顺序**出现在该行内。
#     不设"子串命中即算过"的档位——那样的档位下，引文里混进原件没有的内容也能过。
#   不做大小写 / 全半角 / 标点规整：规整越多，"核过"越接近"看起来像"。
#
# 判定：
#   PASS        与原件一致（含显式截断的分段按序命中）
#   MISMATCH    读得到但对不上 → 该结论不能用这条引文支撑
#   NOFILE      文件不在（路径写错，或原件没随单交过来）
#   NOLINE      行号缺失 / 非法 / 越界
#   READ-ERROR  文件读不出（utf-8 与 gbk 都解不开）——编码问题不该被报成"引文错"
#   NO-ORIGIN   没有原件（粘贴件）→ 不计入判定，也不表示有问题
#
# 退出码：0 = 判定项全过（NO-ORIGIN 不算失败）；1 = 至少一条不能用；2 = 用法或解析错误
#
# 用法：
#   python3 scripts/verify_evidence.py traces/<session>.yaml --root <原件根目录>
#   python3 scripts/verify_evidence.py traces/*.yaml --json
#
# 依赖：PyYAML

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("需要 PyYAML：pip install pyyaml")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _yaml import load_file   # noqa: E402  （解析后端单一事实源）

VERDICTS_FAIL = {"MISMATCH", "NOFILE", "NOLINE", "READ-ERROR"}
DEFAULT_MAX_CHARS = 160


def norm(text):
    """空白归一化：连续空白折成一个空格、去首尾空白。除此之外不改任何字符。"""
    return " ".join(str(text).split())


def norm_segments(quote):
    """按显式截断标记 `...` 切段（去空段）。只有一段时表示未截断。"""
    return [s for s in (norm(p) for p in str(quote).split("...")) if s]


def compare(actual, quote):
    """返回 (verdict, 说明)。判据见文件头：逐字相等，或显式截断后分段按序命中。"""
    a = norm(actual)
    segs = norm_segments(quote)
    if not segs:
        return "NOLINE", "引文为空"
    if len(segs) == 1:
        return ("PASS", None) if segs[0] == a else ("MISMATCH", "与原件该行不一致")
    pos = 0
    for seg in segs:
        i = a.find(seg, pos)
        if i < 0:
            return "MISMATCH", f"截断分段 '{seg[:40]}' 未按序出现在该行内"
        pos = i + len(seg)
    return "PASS", None


def read_line(path, n):
    """流式读第 n 行（不把大文件读进内存）。返回 (文本, 错误码, 说明)。"""
    if not path.exists():
        return None, "NOFILE", "文件不存在"
    if path.is_dir():
        return None, "NOFILE", "路径是目录"
    if n is None or n <= 0:
        return None, "NOLINE", "行号缺失或非法"
    for enc in ("utf-8", "gbk"):
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                for i, line in enumerate(f, 1):
                    if i == n:
                        return line.rstrip("\r\n"), None, None
            return None, "NOLINE", f"行号 {n} 超出文件行数"
        except UnicodeDecodeError:
            continue
        except OSError as e:
            return None, "NOFILE", str(e)
    return None, "READ-ERROR", "utf-8 与 gbk 都解不开（编码不支持，非引文问题）"


def collect_items(trace_path):
    """抽出 trace 里的引文条目。返回 (items, error)。"""
    try:
        doc = load_file(trace_path)
    except yaml.YAMLError as e:
        return None, f"{trace_path}: YAML 解析失败：{e}"
    if not isinstance(doc, dict) or not isinstance(doc.get("trace"), list):
        return None, f"{trace_path}: 顶层没有 trace 列表（不是诊断 trace 文件？）"
    items = []
    for idx, event in enumerate(doc["trace"], 1):
        if not isinstance(event, dict):
            continue
        evidence = event.get("evidence")
        if not isinstance(evidence, dict):
            continue
        quotes = evidence.get("quotes")
        if not isinstance(quotes, list):
            continue
        for q in quotes:
            items.append({"trace": str(trace_path), "event": idx, "quote_entry": q})
    return items, None


def verify_item(entry, root, max_chars):
    q = entry.get("quote_entry")
    rec = {"trace": entry["trace"], "event": entry["event"],
           "id": None, "file": None, "line": None, "quote": None}
    if not isinstance(q, dict):
        rec.update(verdict="NO-ORIGIN", note="quotes 条目不是 mapping")
        return rec
    rec["id"] = q.get("id")
    rec["file"] = q.get("file")
    rec["line"] = q.get("line")
    rec["quote"] = q.get("quote")
    if not rec["file"] or rec["line"] is None or not rec["quote"]:
        rec.update(verdict="NO-ORIGIN", note="缺 file / line / quote，按无原件处理")
        return rec
    raw = Path(str(rec["file"]))
    path = raw if raw.is_absolute() else (root / raw)
    try:
        n = int(rec["line"])
    except (TypeError, ValueError):
        rec.update(verdict="NOLINE", note=f"行号不是整数：{rec['line']!r}")
        return rec
    actual, err, note = read_line(path, n)
    if err:
        rec.update(verdict=err, note=note, actual=None)
        return rec
    verdict, why = compare(actual, rec["quote"])
    rec.update(verdict=verdict, note=why, actual=actual[:max_chars])
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description="trace 引文回验（重读原件逐字比对）")
    ap.add_argument("traces", nargs="+", help="诊断 trace YAML（可多个）")
    ap.add_argument("--root", default=".", help="原件根目录（quotes.file 相对它解析，默认当前目录）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="回显原文的截断长度")
    args = ap.parse_args(argv)

    root = Path(args.root)
    records = []
    for t in args.traces:
        path = Path(t)
        if not path.exists():
            sys.stderr.write(f"verify_evidence: 找不到 trace 文件 {t}\n")
            return 2
        items, err = collect_items(path)
        if err:
            sys.stderr.write(f"verify_evidence: {err}\n")
            return 2
        for it in items:
            records.append(verify_item(it, root, args.max_chars))

    counts = {}
    for r in records:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    failed = [r for r in records if r["verdict"] in VERDICTS_FAIL]

    if args.json:
        print(json.dumps({"root": str(root), "counts": counts, "items": records},
                         ensure_ascii=False, indent=2))
        return 1 if failed else 0

    judged = [r for r in records if r["verdict"] != "NO-ORIGIN"]
    print(f"verify_evidence: 引文 {len(judged)} 条可核 / {counts.get('NO-ORIGIN', 0)} 条无原件（不计入判定）")
    for r in records:
        loc = f"{r['file']}:{r['line']}" if r["file"] else "(无原件)"
        head = f"  {r['verdict']:<10} {r['trace']}[事件 {r['event']}] {loc}"
        if r.get("id"):
            head += f" [{r['id']}]"
        print(head)
        if r["verdict"] == "MISMATCH":
            if r.get("quote"):
                print(f"      引文: {norm(r['quote'])[:args.max_chars]}")
            if r.get("actual") is not None:
                print(f"      原件: {r['actual']}")
        elif r["note"]:
            print(f"      {r['note']}")
    if judged:
        summary = " / ".join(f"{k} {counts[k]}" for k in
                             ("PASS", "MISMATCH", "NOFILE", "NOLINE", "READ-ERROR") if k in counts)
        print(f"小结: {summary or '无判定项'}")
    if failed:
        print(f"结论: {len(failed)} 条引文不能用——对应结论降级为推测，或回步骤 4 重新取证")
        return 1
    print("结论: 可核引文全部与原件一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
