#!/usr/bin/env python3
"""PR 守卫：生成物只能由主干 job 写，提交者不应手改。

判据是机械的：`git diff <base>...HEAD` 里出现生成物路径即红。
红线之外给可执行修法：把那些文件还原到基线，只提交源文件。

为什么不合入后自动覆盖：手改生成物会让评审面与主干内容分叉，而生成器下次重建会
静默覆盖掉手改。先挡住，让改动落到源文件上，比事后猜"这行为什么没了"便宜。
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from _cli import main_entry
from generated_plane import is_generated


def main() -> int:
    ap = argparse.ArgumentParser(description="PR 不得修改生成物")
    ap.add_argument("--base", required=True, help="基线 ref（CI 传 origin/<base>，本地传 main）")
    ap.add_argument("--root", default=None, help="仓库根（默认脚本上两级）")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    cmd = [
        "git",
        "-C",
        str(root),
        "diff",
        "--name-only",
        f"{args.base}...HEAD",
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        print(f"取不到与基线 {args.base} 的差异：", p.stderr.strip(), sep="\n")
        print("如果是浅克隆，先 git fetch origin <base>；三点 diff 需要 merge-base。")
        return 2

    changed = [line for line in p.stdout.splitlines() if line.strip()]
    bad = [path for path in changed if is_generated(path)]

    if not bad:
        print(f"生成物未改动（本次变更 {len(changed)} 个文件）")
        return 0

    print("PR 改了生成物。这些文件由脚本生成，合入后由主干 job 重建：")
    for path in bad:
        print(f"  {path}")
    print()
    print("修法：把生成物还原到基线，只提交源文件。")
    print(f"  git checkout {args.base} -- {' '.join(bad)}")
    print("然后重新提交；不要跑生成器后把结果一起提交。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main_entry(main))
