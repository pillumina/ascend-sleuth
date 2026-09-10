#!/usr/bin/env python3
# build_docs_index.py —— 由 docs/_manifest.yaml 生成 README 的名单区块，并校验完整性
#
# 为什么需要它（原则二：不变量写进结构；原则八：可观测先于改进）：README 的文档目录与
# skill 名单原先手写，于是**同一事实被镜像到多处就会漂移**——术语表曾写"共九个 skill"
# 而实际十个；README 写"八个 skill"（本意是用户面子集）却无从判断是总数还是某一面；
# 文档目录是 17 条平铺，读者看不出"我现在该读哪篇"。这类数字没有理由手写。
#
# 分工（分层先例同 metrics/timeline.yaml vs docs/metrics.md）：
#   docs/_manifest.yaml  = 数据（人工维护的唯一处：分层 + 一句话用途 + skill 归属）
#   README.md 标记区块    = 生成物（本脚本写；不要手改）
#
# 用法：
#   python3 scripts/build_docs_index.py            # 重新生成 README 区块
#   python3 scripts/build_docs_index.py --check    # CI：生成物与清单不一致即红
#
# --check 同时校验**完整性**——`docs/` 下出现清单未登记的 .md 即红。这是防漂移的关键：
# 新增一篇文档却忘了登记，比数字写错更难被发现（数字至少显眼）。
#
# 退出码：0 = 一致；1 = 需要重新生成 / 有未登记文档。

import argparse
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
MANIFEST = "docs/_manifest.yaml"
BEGIN = "<!-- BEGIN generated: docs-index (scripts/build_docs_index.py；由 docs/_manifest.yaml 生成，勿手改) -->"
END = "<!-- END generated: docs-index -->"
BEGIN_SKILLS = "<!-- BEGIN generated: skill-roster (scripts/build_docs_index.py；由 docs/_manifest.yaml 生成，勿手改) -->"
END_SKILLS = "<!-- END generated: skill-roster -->"


def load(root: Path):
    p = root / MANIFEST
    if not p.exists():
        raise SystemExit(f"缺少 {MANIFEST}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def render_skills(doc) -> str:
    skills = doc.get("skills") or []
    order = doc.get("scope_order") or []
    by_scope = {}
    for s in skills:
        by_scope.setdefault(s.get("scope") or "其它", []).append(s)

    total = len(skills)
    parts = [f"本仓共 **{total} 个 skill**，按**你用不用得上**分三组："]
    for scope in order + [k for k in by_scope if k not in order]:
        items = by_scope.get(scope) or []
        if not items:
            continue
        names = []
        for s in items:
            n = s.get("note")
            names.append(f"`{s['name']}`" if not n else f"`{s['name']}`（{n}）")
        parts.append(f"- **{scope}**（{len(items)}）：" + " · ".join(names))
    return "\n".join(parts)


def render_docs(root: Path, doc) -> str:
    layers = doc.get("layers") or []
    entries = doc.get("docs") or []
    by_layer = {}
    for e in entries:
        by_layer.setdefault(e.get("layer"), []).append(e)

    out = []
    for layer in layers:
        lid = layer.get("id")
        items = by_layer.get(lid) or []
        if not items:
            continue
        out.append(f"**{layer.get('title', lid)}**")
        if layer.get("when"):
            out.append(f"*{layer['when']}*")
        out.append("")
        for e in items:
            path = e["path"]
            if path.endswith("/"):
                files = sorted((root / path).glob("*.md"))
                links = "、".join(f"[{f.stem[:4]}]({path}{f.name})" for f in files)
                out.append(f"- `{path}` — {e.get('purpose', '')}")
                out.append(f"  - {links}")
            else:
                out.append(f"- [{Path(path).name}]({path}) — {e.get('purpose', '')}")
        out.append("")
    return "\n".join(out).rstrip()


def missing_docs(root: Path, doc) -> list:
    """docs/ 下未登记进清单的 .md（含 ADR：ADR 以目录条目 `docs/adr/` 整体登记）。"""
    listed = {e["path"] for e in (doc.get("docs") or [])}
    missing = []
    for f in sorted((root / "docs").glob("*.md")):
        rel = f"docs/{f.name}"
        if rel not in listed:
            missing.append(rel)
    if "docs/adr/" not in listed:
        for f in sorted((root / "docs" / "adr").glob("*.md")):
            missing.append(f"docs/adr/{f.name}")
    return missing


def replace_block(text: str, begin: str, end: str, body: str) -> str:
    if begin not in text or end not in text:
        raise SystemExit(f"README 缺少标记区块：{begin}")
    head = text.index(begin) + len(begin)
    tail = text.index(end)
    return text[:head] + "\n" + body + "\n" + text[tail:]


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 README 的名单区块（数据源 docs/_manifest.yaml）")
    ap.add_argument("--check", action="store_true", help="CI：不一致即红")
    ap.add_argument("--root", type=Path, default=REPO)
    args = ap.parse_args()

    root = args.root.resolve()
    doc = load(root)
    readme_path = root / "README.md"
    readme = readme_path.read_text(encoding="utf-8")

    missing = missing_docs(root, doc)
    want = replace_block(readme, BEGIN, END, render_docs(root, doc))
    want = replace_block(want, BEGIN_SKILLS, END_SKILLS, render_skills(doc))

    if args.check:
        problems = []
        if missing:
            problems.append(f"docs/ 下有 {len(missing)} 篇文档未登记进 {MANIFEST}：\n  - "
                            + "\n  - ".join(missing))
        if want != readme:
            problems.append("README 的生成区块与清单不一致——跑 "
                            "`python3 scripts/build_docs_index.py` 重新生成后提交")
        if problems:
            print("build_docs_index --check: 不一致")
            for p in problems:
                print(f"  - {p}")
            return 1
        n = len(doc.get("docs") or [])
        print(f"build_docs_index --check: OK（{n} 条文档登记、{len(doc.get('skills') or [])} 个 skill，README 区块一致）")
        return 0

    readme_path.write_text(want, encoding="utf-8")
    print(f"build_docs_index: 已写回 README.md（{len(doc.get('docs') or [])} 条文档登记、"
          f"{len(doc.get('skills') or [])} 个 skill）")
    if missing:
        print(f"  提示：docs/ 下仍有 {len(missing)} 篇未登记（--check 会因此红）：")
        for m in missing:
            print(f"    - {m}")
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
