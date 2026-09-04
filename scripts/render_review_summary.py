#!/usr/bin/env python3
# render_review_summary.py —— 审读面渲染：把"含代号的人读文本"渲染成"首次出现即解码"。
#
# 目的（docs/git-workflow.md「人读性与代号约定」）：
#   源文件（YAML 机器字段、docs、SKILL.md）保持词法不变；人审时读**解码视图**而非
#   裸文本——审读面与存储面分离（原则三的延伸：底座词法、人读视图承担解码）。
#
# 用法：
#   python3 scripts/render_review_summary.py --card EV-2026-009 [--root <repo>]
#       把一张 EV 卡的 prose 字段渲染成解码审读稿（机器枚举字段原样列出）
#   python3 scripts/render_review_summary.py --diff <base>..<head> [--root <repo>]
#       把一段 git diff 中出现的代号按文件列成"代号×次数×解码"表 + 未登记告警
#   python3 scripts/render_review_summary.py --scan <path>... [--root <repo>]
#       扫描文件的人读文本，列出未登记代号（渲染告警，非 CI 硬门——可读性是
#       判断性规范，见 docs/git-workflow.md；告警用于"先登记再使用"的自我约束）
#
# 词表唯一数据源：docs/glossary.yaml（新增代号先登记，再在 evolution.md 速查表补行）。
# 注意：markdown 反引号内的内容不解码（命令/字段名保持原样）。

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

GLOSSARY_REL = "docs/glossary.yaml"
IDEAS_REL = "proposals/ideas"

# 未登记告警用的家族 pattern（与 glossary.families 兜底一致；词表漏登时仍能发现）
FAMILY_PATTERNS = [
    (re.compile(r"\bL[1-3]\b"), "演进对象层"),
    (re.compile(r"\bS[1-3]\b"), "评分源"),
    (re.compile(r"\b[AEMOP][0-9]\b"), "roadmap 事项/落地阶段"),
    (re.compile(r"\bG[1-8]\b"), "治理缺口"),
    (re.compile(r"\bT[0-9]+\b"), "触发信号"),
    (re.compile(r"\bEV-\d{4}-\d{3}\b"), "EV 卡"),
    (re.compile(r"\bPhase [A-E]\b"), "落地阶段"),
]


class Glossary:
    def __init__(self, root: Path):
        self.root = root
        doc = yaml.safe_load((root / GLOSSARY_REL).read_text(encoding="utf-8")) or {}
        self.entries = {}
        for e in doc.get("entries", []):
            tok = e.get("token")
            if tok:
                self.entries[tok] = e
        toks = sorted(self.entries, key=len, reverse=True)
        parts = []
        for t in toks:
            if not t:
                continue
            if t[0].isalnum() and t[-1].isalnum():
                parts.append(r"\b" + re.escape(t) + r"\b")
            else:
                parts.append(re.escape(t))
        self.regex = re.compile("|".join(parts)) if parts else None

    def meaning(self, token):
        e = self.entries.get(token)
        if not e:
            return None
        m = e.get("meaning", "")
        see = e.get("see")
        return f"{m}（定义：{see}）" if see else m

    def annotate(self, token):
        e = self.entries.get(token)
        if not e:
            return token
        # 内联注释用短义（保持句子可读）；无 short 时回退完整含义
        gloss = e.get("short") or e.get("meaning", "")
        return f"{token}〔{gloss}〕"


def split_code_spans(text):
    """切成 (is_code, chunk) 段：``` 围栏与行内反引号内视为代码，不解码。"""
    segs = []
    for p in re.split(r"(```.*?```)", text, flags=re.S):
        if p.startswith("```"):
            segs.append((True, p))
            continue
        for s in re.split(r"(`[^`\n]*`)", p):
            if s.startswith("`") and s.endswith("`") and len(s) > 1:
                segs.append((True, s))
            elif s:
                segs.append((False, s))
    return segs


def walk_text(obj):
    """产出 obj 内全部字符串（用于未知代号扫描）。"""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk_text(v)
    elif isinstance(obj, list):
        for it in obj:
            yield from walk_text(it)
    elif isinstance(obj, str):
        yield obj


def decode_text(text, seen, gl):
    """已登记代号首次出现 → 加解码注；seen 跨调用记住已解码的 token。"""
    if not text or gl.regex is None:
        return text, seen
    out = []
    for is_code, chunk in split_code_spans(text):
        if is_code:
            out.append(chunk)
            continue

        def repl(m, _seen=seen):
            tok = m.group(0)
            if tok in _seen or tok not in gl.entries:
                return tok
            _seen.add(tok)
            return gl.annotate(tok)

        out.append(gl.regex.sub(repl, chunk))
    return "".join(out), seen


EV_INSTANCE = re.compile(r"\bEV-\d{4}-\d{3}\b")


def unknown_tokens(text, gl):
    """人读文本中家族 pattern 命中但词表无条目的代号。
    EV 卡实例号（EV-YYYY-NNN）家族自解释，无需逐张登记，豁免。"""
    found = set()
    for is_code, chunk in split_code_spans(text):
        if is_code:
            continue
        for pat, fam in FAMILY_PATTERNS:
            for m in pat.finditer(chunk):
                tok = m.group(0)
                if EV_INSTANCE.match(tok):
                    continue
                if tok not in gl.entries:
                    found.add((tok, fam))
    return found


def emit(label, value, lines, seen, gl):
    d, seen = decode_text(str(value), seen, gl)
    lines.append(f"\n**{label}**：{d}")
    return seen


def cmd_card(card_id, root):
    p = root / IDEAS_REL / f"{card_id}.yaml"
    if not p.exists():
        print(f"找不到卡: {p}", file=sys.stderr)
        return 1
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    gl = Glossary(root)
    lines = [f"# {card_id} 解码审读稿（渲染自 `{IDEAS_REL}/{card_id}.yaml`）", ""]

    machine = {k: doc.get(k) for k in
               ["id", "layer", "status", "authorization", "dimension",
                "supersedes", "superseded_by", "created_at", "risk",
                "principle_refs", "actual_cost"] if k in doc}
    lines.append("**机器字段**（保持词法——枚举含义查词表/速查表）：")
    lines.append("```yaml")
    lines.append(yaml.safe_dump(machine, allow_unicode=True, sort_keys=False).rstrip())
    lines.append("```")

    seen = set()
    if doc.get("title"):
        seen = emit("标题", doc["title"], lines, seen, gl)
    if doc.get("hypothesis"):
        seen = emit("假设", doc["hypothesis"], lines, seen, gl)
    if isinstance(doc.get("predicted_effect"), dict):
        pe = doc["predicted_effect"]
        seen = emit("预期效果", f"{pe.get('metric')}：{pe.get('from')} → {pe.get('to')}",
                    lines, seen, gl)
    if isinstance(doc.get("source_signals"), list):
        for i, s in enumerate(doc["source_signals"]):
            seen = emit(f"触发信号 {i + 1}", f"{s.get('signal', '')} — {s.get('evidence', '')}",
                        lines, seen, gl)
    if isinstance(doc.get("validation"), dict):
        v = doc["validation"]
        for lab, key in [("验证方法", "method"), ("验证基线", "baseline"),
                         ("成功标准", "success_criteria"), ("回滚", "rollback")]:
            if v.get(key):
                seen = emit(lab, v[key], lines, seen, gl)
    if isinstance(doc.get("gate"), dict) and doc["gate"].get("condition"):
        seen = emit("闸门条件", doc["gate"]["condition"], lines, seen, gl)
    if isinstance(doc.get("decisions"), list):
        for i, d in enumerate(doc["decisions"]):
            lines.append(f"\n**决策 {i + 1}**（{d.get('who')} · {d.get('when')} · {d.get('type')}）：")
            c, seen = decode_text(str(d.get("conclusion", "")), seen, gl)
            lines.append(c)

    unknown = set()
    for t in walk_text(doc):
        unknown |= unknown_tokens(t, gl)
    if unknown:
        lines.append("\n> ⚠ 未登记代号（建议先登记 docs/glossary.yaml）：" +
                     "、".join(sorted(f"`{t}`（{f}）" for t, f in unknown)))
    print("\n".join(lines))
    return 0


def cmd_diff(rev_range, root):
    gl = Glossary(root)
    try:
        diff = subprocess.run(
            ["git", "-C", str(root), "diff", "-U0"] + rev_range.split(".."),
            capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as e:
        print("git diff 失败:", e.stderr, file=sys.stderr)
        return 1
    per_file = {}   # file -> {token: count}
    unknowns = {}   # file -> set((token, fam))
    cur_file = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            cur_file = line[6:]
            per_file.setdefault(cur_file, {})
            unknowns.setdefault(cur_file, set())
            continue
        if cur_file is None:
            continue
        if not (line.startswith("+") or line.startswith("-")):
            continue
        if line.startswith(("+++", "---")):
            continue
        text = line[1:]
        if gl.regex is not None:
            for is_code, chunk in split_code_spans(text):
                if is_code:
                    continue
                for m in gl.regex.finditer(chunk):
                    tok = m.group(0)
                    per_file[cur_file][tok] = per_file[cur_file].get(tok, 0) + 1
        for tok, fam in unknown_tokens(text, gl):
            unknowns[cur_file].add((tok, fam))

    lines = ["# 解码 diff（人读视图）", "",
             f"> 范围 `{rev_range}`。源文件未改动；本表把 diff 里出现的代号按文件解码，"
             f"供人审对照，避免裸读满屏代号。未登记代号见各文件告警。", ""]
    any_out = False
    for fname in sorted(per_file):
        codes = per_file[fname]
        if not codes and not unknowns.get(fname):
            continue
        any_out = True
        lines.append(f"## `{fname}`")
        if codes:
            lines.append("| 代号 | 出现次数 | 解码 |")
            lines.append("|---|---|---|")
            for tok in sorted(codes, key=lambda t: (-codes[t], t)):
                lines.append(f"| `{tok}` | {codes[tok]} | {gl.meaning(tok) or '（词表缺含义）'} |")
        if unknowns.get(fname):
            u = sorted(unknowns[fname])
            lines.append("\n> ⚠ 未登记代号（建议先登记 docs/glossary.yaml 再使用）：" +
                         "、".join(f"`{t}`（{f}）" for t, f in u))
        lines.append("")
    if not any_out:
        lines.append("（diff 中无已登记/疑似代号）")
    print("\n".join(lines))
    return 0


def cmd_scan(paths, root):
    gl = Glossary(root)
    bad = False
    for rel in paths:
        p = root / rel
        if not p.exists():
            print(f"找不到: {rel}", file=sys.stderr)
            bad = True
            continue
        text = p.read_text(encoding="utf-8")
        unk = unknown_tokens(text, gl)
        if unk:
            print(f"{rel}:")
            for tok, fam in sorted(unk):
                print(f"  ⚠ 未登记代号 `{tok}`（{fam}）——先登记 docs/glossary.yaml")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(
        description="审读面渲染：代号首次出现即解码（词表 docs/glossary.yaml）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--card", metavar="EV-YYYY-NNN", help="渲染一张 EV 卡的解码审读稿")
    g.add_argument("--diff", metavar="BASE..HEAD", help="渲染 git diff 的代号解码表")
    g.add_argument("--scan", nargs="+", metavar="PATH", help="扫描文件中的未登记代号")
    ap.add_argument("--root", default=".", help="仓库根目录（默认当前目录）")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if args.card:
        return cmd_card(args.card, root)
    if args.diff:
        return cmd_diff(args.diff, root)
    return cmd_scan(args.scan, root)


if __name__ == "__main__":
    sys.exit(main())
