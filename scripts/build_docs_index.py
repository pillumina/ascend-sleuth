#!/usr/bin/env python3
# build_docs_index.py —— 由 docs/_manifest.yaml 生成名单区块，并校验完整性
#
# 为什么需要它（原则二：不变量写进结构；原则八：可观测先于改进）：README 的文档目录与
# skill 名单原先手写，于是**同一事实被镜像到多处就会漂移**——术语表曾写"共九个 skill"
# 而实际十个；README 写"八个 skill"（本意是用户面子集）却无从判断是总数还是某一面；
# 文档目录是 17 条平铺，读者看不出"我现在该读哪篇"。这类数字没有理由手写。
#
# 分工（分层先例同 metrics/timeline.yaml vs docs/guide/metrics.md）：
#   docs/_manifest.yaml  = 数据（人工维护的唯一处：分层 + 一句话用途 + skill 归属 + 各区块落点）
#   README.md / docs/README.md 的标记区块 = 生成物（本脚本写；不要手改）
#
# 落点为什么也是数据：两个区块服务不同的读者。skill 名单回答"有哪几个 skill"，属落地页要
# 回答的问题，留在 README.md；文档目录是全部文档的清单，服务"我要改机制"的读者，放
# docs/README.md，落地页只留一个指向它的链接。落点写死在脚本里时，24 条文档清单只能落在
# 落地页上，而落地页的读者要的是下一个动作。落点写在清单的 blocks: 段。
#
# 用法：
#   python3 scripts/build_docs_index.py            # 重新生成各区块
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

from _stdio import write_text_lf

REPO = Path(__file__).resolve().parent.parent
MANIFEST = "docs/_manifest.yaml"
BEGIN = "<!-- BEGIN generated: docs-index (scripts/build_docs_index.py；由 docs/_manifest.yaml 生成，勿手改) -->"
END = "<!-- END generated: docs-index -->"
BEGIN_SKILLS = "<!-- BEGIN generated: skill-roster (scripts/build_docs_index.py；由 docs/_manifest.yaml 生成，勿手改) -->"
END_SKILLS = "<!-- END generated: skill-roster -->"
DEFAULT_TARGET = "README.md"


def load(root: Path):
    p = root / MANIFEST
    if not p.exists():
        raise SystemExit(f"缺少 {MANIFEST}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def roster_skills(doc):
    """名单里的面向使用者的 skill。

    `internal: true` 的条目是项目自用的 skill（写规范、维护流程这类），不面向使用者：
    它们既不进名单，也不进计数——否则本清单会把"给使用者的 skill 有几个"说错，
    而这句话正是本清单存在的理由（先例：README 曾写"八个"、术语表曾写"共九个"）。
    """
    return [s for s in (doc.get("skills") or []) if not s.get("internal")]


def render_skills(root: Path, doc, target: str) -> str:
    # root / target 未使用：与 render_docs 统一签名，便于按 BLOCKS 表分发。
    skills = roster_skills(doc)
    order = doc.get("scope_order") or []
    by_scope = {}
    for s in skills:
        by_scope.setdefault(s.get("scope") or "其它", []).append(s)

    total = len(skills)
    groups = [sc for sc in order + [k for k in by_scope if k not in order] if by_scope.get(sc)]
    # 组数是现算的：写死"三组"会在增删一个分组时静默说错。
    parts = [f"本仓共 **{total} 个面向使用者的 skill**，按使用场景分 {len(groups)} 组："]
    for scope in groups:
        items = by_scope[scope]
        names = []
        for s in items:
            n = s.get("note")
            names.append(f"`{s['name']}`" if not n else f"`{s['name']}`（{n}）")
        parts.append(f"- **{scope}**（{len(items)}）：" + " · ".join(names))
    return "\n".join(parts)


def link_prefix(target: str) -> str:
    """从落点文件所在目录回到仓根的相对前缀。

    清单里的 path 一律写成仓根相对（`docs/guide/eval.md`），而区块的落点可能在子目录里。
    落点变成数据之后，同一个区块会落在不同深度的文件里，链接必须按落点重算：
    README.md → 空串，docs/README.md → `../`。不重算就会渲染出 `docs/docs/...`。
    """
    return "../" * target.count("/")


def render_docs(root: Path, doc, target: str) -> str:
    prefix = link_prefix(target)
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
                links = "、".join(f"[{f.stem[:4]}]({prefix}{path}{f.name})" for f in files)
                out.append(f"- `{path}` — {e.get('purpose', '')}")
                out.append(f"  - {links}")
            else:
                if path == target:
                    # 区块落在 docs/README.md 时，这一条就是它自己，不给自己做链接。
                    # 判据是 path 而不是拼好的链接：prefix 由 target 算出，链接解析回来恒等于 path。
                    out.append(f"- `{path}` — {e.get('purpose', '')}")
                else:
                    out.append(f"- [{Path(path).name}]({prefix}{path}) — {e.get('purpose', '')}")
        out.append("")
    return "\n".join(out).rstrip()


# 素材与应用目录：自带 README，不是阅读顺序里的文档，不参与"未登记即红"。
ASSET_DIRS = {"assets", "diagrams", "demo-assets", "kb-explorer"}


def missing_docs(root: Path, doc) -> list:
    """docs/ 下未登记进清单的 .md。

    递归扫 `docs/**`，不再逐个目录列举。为什么改：原实现只扫 `docs/*.md`、
    `docs/adr/*.md`、`docs/mechanism/*.md` 三处，于是文档一旦下沉到别的子目录
    （spec/、guide/、plan/），**"未登记即红"这条检查会静默漏掉它们** —— 检查还在跑、
    却已经不看新增的那一层，比没有检查更难发现（实测：本仓文档按层分目录时才发现）。
    目录条目（如 `docs/adr/`）整体覆盖其下文件；素材与应用目录自带 README，不是阅读顺序
    里的文档，按 ASSET_DIRS 排除。
    """
    listed = {e["path"] for e in (doc.get("docs") or [])}
    dir_entries = {p for p in listed if p.endswith("/")}
    missing = []
    for f in sorted((root / "docs").rglob("*.md")):
        rel = f.relative_to(root).as_posix()
        if rel in listed:
            continue
        if any(rel.startswith(d) for d in dir_entries):
            continue
        if rel.split("/")[1] in ASSET_DIRS:
            continue
        missing.append(rel)
    return missing


def replace_block(text: str, begin: str, end: str, body: str, where: str) -> str:
    if begin not in text or end not in text:
        raise SystemExit(f"{where} 缺少标记区块：{begin}")
    head = text.index(begin) + len(begin)
    tail = text.index(end)
    return text[:head] + "\n" + body + "\n" + text[tail:]


def block_targets(doc) -> dict:
    """区块 id → 落点（相对仓根）。未在清单里配置的区块用 DEFAULT_TARGET。"""
    targets = {bid: DEFAULT_TARGET for bid, _, _, _ in BLOCKS}
    configured = doc.get("blocks") or {}
    unknown = sorted(set(configured) - set(targets))
    if unknown:
        raise SystemExit(f"{MANIFEST} 的 blocks: 里有未定义的区块 id：{', '.join(unknown)}")
    for bid, cfg in configured.items():
        target = (cfg or {}).get("target")
        if target:
            targets[bid] = target
    return targets


# 区块表：(id, 起始标记, 结束标记, 渲染函数)。id 是清单 blocks: 段的键。
BLOCKS = (
    ("skill-roster", BEGIN_SKILLS, END_SKILLS, render_skills),
    ("docs-index", BEGIN, END, render_docs),
)


def stray_blocks(root: Path, targets: dict) -> list:
    """落点之外的文件里出现的生成标记。

    落点变成数据之后多出来的一类脏：某个区块换了落点，旧文件里的副本不再被任何一次生成
    覆盖，也不会与清单不一致——`--check` 只看落点文件，于是那份过期的清单会一直留在那里
    被当成正文读。判据是标记本身：一个区块只允许出现在它声明的落点里。

    扫描面是根人读文档与 docs/ 下的 .md（生成区块只可能落在这两处）。
    """
    strays = []
    candidates = [root / "README.md"] + sorted((root / "docs").rglob("*.md"))
    for path in candidates:
        if not path.exists():
            continue
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        for bid, begin, _, _ in BLOCKS:
            if begin in text and targets[bid] != rel:
                strays.append(f"{rel} 里有 {bid} 的生成标记，但落点是 {targets[bid]}"
                              "——换成落点后旧文件里的副本要删掉")
    return strays


def main() -> int:
    ap = argparse.ArgumentParser(
        description="生成名单区块（数据源 docs/_manifest.yaml，落点由它的 blocks: 段决定）")
    ap.add_argument("--check", action="store_true", help="CI：不一致即红")
    ap.add_argument("--root", type=Path, default=REPO)
    args = ap.parse_args()

    root = args.root.resolve()
    doc = load(root)
    targets = block_targets(doc)

    originals = {}
    results = {}
    for bid, begin, end, render in BLOCKS:
        rel = targets[bid]
        if rel not in originals:
            path = root / rel
            if not path.exists():
                raise SystemExit(f"{MANIFEST} 的 blocks.{bid}.target = {rel}，但该文件不存在")
            originals[rel] = path.read_text(encoding="utf-8")
            results[rel] = originals[rel]
        results[rel] = replace_block(results[rel], begin, end, render(root, doc, rel), rel)

    missing = missing_docs(root, doc)
    places = "、".join(sorted(results))

    if args.check:
        problems = []
        if missing:
            problems.append(f"docs/ 下有 {len(missing)} 篇文档未登记进 {MANIFEST}：\n  - "
                            + "\n  - ".join(missing))
        stale = sorted(rel for rel, want in results.items() if want != originals[rel])
        if stale:
            problems.append("生成区块与清单不一致（" + "、".join(stale) + "）——跑 "
                            "`python3 scripts/build_docs_index.py` 重新生成后提交")
        strays = stray_blocks(root, targets)
        if strays:
            problems.append("生成标记出现在非落点文件：\n  - " + "\n  - ".join(strays))
        if problems:
            print("build_docs_index --check: 不一致")
            for p in problems:
                print(f"  - {p}")
            return 1
        n = len(doc.get("docs") or [])
        print(f"build_docs_index --check: OK（{n} 条文档登记、{len(roster_skills(doc))} 个 skill，"
              f"{len(results)} 个落点一致：{places}）")
        return 0

    for rel, want in results.items():
        write_text_lf(root / rel, want, encoding="utf-8")
    print(f"build_docs_index: 已写回 {places}（{len(doc.get('docs') or [])} 条文档登记、"
          f"{len(roster_skills(doc))} 个 skill）")
    if missing:
        print(f"  提示：docs/ 下仍有 {len(missing)} 篇未登记（--check 会因此红）：")
        for m in missing:
            print(f"    - {m}")
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
