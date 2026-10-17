#!/usr/bin/env python3
"""build_entry_activity.py —— 条目使用记录：源 → 生成物（`--check` 与源比对）。

源是 `metrics/entry-activity.d/<周>.yaml`（一周一个文件、一行一条记录、一次运行追加若干行），
生成物是 `metrics/entry-activity/<部署>.yaml`（一个部署一份、按 id 汇总）。

为什么要有生成物而不是让读端直接读源：读端只有一个入口，面板与知识整理不必知道源分了几个文件、
按什么顺序追加、某一行的键是不是缺了；源可以换形状而读端不改（这一次就把条目使用记录从期文件里的
一个段换成了独立的追加文件族）。这套写法仓库里已有先例：`metrics/timeline.d/*` 合成 `timeline.yaml`，
`knowledge/*.yaml` 合成 `_index.yaml`。

**一个部署一份、互不覆盖**：记录行带 `deployment`，汇总按它分组。两台部署的计数不会被加成一条排行
（跨部署合并没有意义：候选集与知识库版本都不同）。部署名由 `entry_activity.deployment()` 取，
同一克隆的所有 worktree 得到同一个值。

用法：
  python3 scripts/build_entry_activity.py                    # 重建（源里出现过的每个部署 + 仓里已有生成物）
  python3 scripts/build_entry_activity.py --check            # 只校验：生成物与源是否一致
  python3 scripts/build_entry_activity.py --deployment local-a2
  python3 scripts/build_entry_activity.py --root <检出>

退出码：0 = 一致（或重建成功）；1 = `--check` 发现不一致；2 = 数据不完整。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import entry_activity as ea  # noqa: E402
from _stdio import pin_utf8_stdio, write_text_lf  # noqa: E402


def deployments_to_build(root: Path, rows: list, only: str | None):
    """要产出的部署集合：显式指定 > 源里出现过的 + 仓里已有生成物的（并集）。

    并集而不是单取源：部署改名后旧生成物不会被静默删掉（按只接收处理，删不删由 owner 定），
    而新部署的第一份又要能建出来。
    """
    if only:
        return [only]
    deps = {str(r.get("deployment")) for r in rows if r.get("deployment")}
    d = ea.generated_dir(root)
    if d.is_dir():
        deps |= {f.stem for f in d.glob("*.yaml")}
    return sorted(deps)


def build_one(root: Path, dep: str, rows: list, library_cases: int, library_refs: list):
    mine = [r for r in rows if r.get("deployment") == dep]
    if not mine:
        return None
    return ea.render(ea.aggregate(rows, dep, library_cases, library_refs))


def main() -> int:
    ap = argparse.ArgumentParser(description="条目使用记录：源 → 生成物")
    ap.add_argument("--check", action="store_true", help="只校验生成物与源一致（CI 门）")
    ap.add_argument("--root", default=None, help="检出根（默认：脚本上两级）")
    ap.add_argument("--deployment", default=None, help="只产出/校验这一个部署")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    rows, problems = ea.read_source(root)
    if problems:
        print("源文件有问题（先修源再重建生成物）：")
        for p in problems:
            print(f"  - {p}")
        return 2
    library_cases, library_refs = ea.library_inventory(root)
    deps = deployments_to_build(root, rows, args.deployment)
    if not deps:
        print("源里没有任何记录行，仓里也没有生成物——没有要产出的东西。")
        return 0

    bad, written, stale_deps = [], [], []
    for dep in deps:
        text = build_one(root, dep, rows, library_cases, library_refs)
        f = ea.generated_file(root, dep)
        if text is None:
            if f.exists():
                stale_deps.append(dep)
            continue
        if args.check:
            if not f.exists():
                bad.append(f"{f.relative_to(root)}：缺少生成物（源里有 {dep} 的记录行）")
            elif f.read_text(encoding="utf-8") != text:
                bad.append(f"{f.relative_to(root)}：与源不一致（重跑 python3 scripts/build_entry_activity.py）")
        else:
            f.parent.mkdir(parents=True, exist_ok=True)
            write_text_lf(f, text, encoding="utf-8")
            written.append(f)

    if stale_deps:
        print("以下部署在源里已经没有记录行，仓里的旧生成物按只接收处理（不自动删，删由 owner 定）："
              + "、".join(stale_deps))
    if args.check:
        if bad:
            print(f"条目使用记录生成物过期：{len(bad)} 处")
            for b in bad:
                print(f"  - {b}")
            return 1
        print(f"条目使用记录生成物与源一致（{len(deps)} 个部署）。")
        return 0
    for f in written:
        print(f"已重建 {f}")
    if not written:
        print("没有需要重建的生成物。")
    return 0


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
