#!/usr/bin/env python3
"""kb_rev.py —— 知识库版本（这一单诊断跑在哪一版 knowledge/ 上）的确定性入口。

为什么需要它：trace 里记的是 case id，**没有记当时那份知识库是什么版本**。跨机交接时这条缺口
会咬人——接手方若知识库版本不同，同一个 `excluded_cases` 里的 id 可能根本不存在、同一条 case 的
`confidence.score` 排序不同、甚至那条 case 当时还没沉淀出来。于是接手方复现出一套**不同的候选集，
而它自己不知道**（误诊归因也同理：事后要看"当时为什么没命中"，得知道当时库里有什么）。

所以会话开单时把 `kb_rev` 写进 trace 顶层（一次写定、不随步骤变），由本脚本给出取值，
别让 agent 手搓 `git rev-parse`（型号、短长、脏标记各不相同，写进 trace 就成了不可比的字段）。

用法：
  python3 scripts/kb_rev.py              # 人读一行 + 机器可读末行（末行 = 版本 token）
  python3 scripts/kb_rev.py --json       # 只吐 JSON（脚本/面板用）
  python3 scripts/kb_rev.py --root <检出>

取值口径：主检出的 HEAD 短 sha。**拿不到就如实给 `unknown`**（无 git 环境、非检出、git 不在
PATH），不编一个假值，也不阻塞诊断——`kb_rev: unknown` 交接时只会退化成"版本无法比对"的提示。

退出码：0 = 有取值（含 unknown）；2 = --root 不存在。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from _stdio import pin_utf8_stdio

UNKNOWN = "unknown"


def git(root: Path, *args: str):
    """跑一条 git 命令；拿不到（无 git / 非检出 / 超时）返回 None，不抛。"""
    try:
        r = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return (r.stdout or "").strip()


def kb_rev(root: Path):
    """→ (token, dirty, source)。token 取不到时是 `unknown`。"""
    if not root.is_dir():
        return UNKNOWN, None, "missing-root"
    rev = git(root, "rev-parse", "--short", "HEAD")
    if not rev:
        return UNKNOWN, None, "no-git"
    # 脏标记只算已跟踪文件的改动（`-uno`）：traces/、src-code/ 这些 gitignore 的运行时件
    # 天天在变，算进去等于永远 dirty，字段就失去意义了。
    status = git(root, "status", "--porcelain", "-uno")
    dirty = bool(status) if status is not None else None
    return rev, dirty, "git"


def main() -> int:
    ap = argparse.ArgumentParser(description="知识库版本（写入 trace 的 kb_rev 字段）")
    ap.add_argument("--root", default=None, help="检出根目录（默认：本脚本上两级）")
    ap.add_argument("--json", action="store_true", help="只吐 JSON")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    if not root.is_dir():
        print(f"kb_rev: 目录不存在 {root}", file=sys.stderr)
        return 2
    rev, dirty, source = kb_rev(root)
    if args.json:
        print(json.dumps(
            {"kb_rev": rev, "dirty": dirty, "source": source, "root": str(root)},
            ensure_ascii=False,
        ))
        return 0
    if rev == UNKNOWN:
        print(f"知识库版本：unknown（{source}——非 git 检出或 git 不可用；"
              f"trace 里照写 unknown，交接时会退化成「版本无法比对」）")
        print(UNKNOWN)
        return 0
    print(f"知识库版本（{root} 的 HEAD）：{rev}" + ("（有未提交的已跟踪改动）" if dirty else ""))
    print(rev)
    return 0


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
