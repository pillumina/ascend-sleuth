#!/usr/bin/env python3
"""shared_dir.py —— "这份运行时记录该落在哪"的确定性入口（检出侧运行时件的路径解析）

为什么需要它：`traces/`、`postmortems/inbox/`、`proposals/{sessions,tasks,reviews,experiments}/`
都是 .gitignore 的运行时件，而它们的**写侧是 agent 按 prose 写相对路径**。于是同一个克隆里
"在哪个检出跑"决定了记录落在哪：
  - worktree 里写的记录 → **主检出（面板 / 周批指标 / 结算脚本读的那一份）看不到**；
  - 收工 `git worktree remove` → gitignore 件**不报错、也不需要 `--force`**，随 worktree **静默**消失
    （已跟踪且被修改的文件才会被 git 拦下——别把 ignore 件想成"会被拦住"）。
对 `traces/` 尤其致命：它是误诊归因的唯一依据。

所以跨 session 复用的运行时件一律**解析到主检出**（同一克隆共享；`--local` 可强制回检出内），
本脚本就是给 agent 的那一个入口——先取路径，再用该绝对路径读写，别写相对 `traces/`。

用法：
  python3 scripts/shared_dir.py --list           # 列出全部运行时件解析到哪（一眼看清"记录在哪"）
  python3 scripts/shared_dir.py traces           # 只解析一件；stdout 末行 = 绝对路径（并确保目录存在）
  python3 scripts/shared_dir.py inbox --local    # 强制用当前检出（调试 / 故意隔离时）

退出码：0 = 解析成功（末行是路径）；2 = 名字不认识（打印可选名字）。
"""
import argparse
import sys
from pathlib import Path

from _stdio import pin_utf8_stdio

from exec_log_path import (CHECKOUT_DIRS, describe_checkout_dir, resolve_checkout_dir)  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="运行时记录该落在哪（跨 worktree 共享的检出侧目录）")
    ap.add_argument("name", nargs="?", help="运行时件名（--list 看可选值）")
    ap.add_argument("--list", action="store_true", help="列出全部运行时件及其解析结果")
    ap.add_argument("--local", action="store_true", help="用当前检出（默认锚到主检出）")
    ap.add_argument("--root", default=None, help="仓库根目录（默认：本脚本上两级）")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent

    if args.list or not args.name:
        print("运行时件 → 解析结果（写侧一律用下面这个绝对路径，别写相对路径）：")
        for name in CHECKOUT_DIRS:
            path, where, rel = resolve_checkout_dir(name, root, local=args.local)
            print(f"  {name:<22} {describe_checkout_dir(path, rel, where)}")
        if not args.name:
            print(f"\n可选名字：{', '.join(CHECKOUT_DIRS)}", file=sys.stderr)
            return 0 if args.list else 2
        return 0

    path, where, rel = resolve_checkout_dir(args.name, root, local=args.local)
    if path is None:
        print(f"shared_dir: 不认识的运行时件「{args.name}」——可选：{', '.join(CHECKOUT_DIRS)}", file=sys.stderr)
        print(f"✗ 未解析（可用名字见上）", file=sys.stderr)
        return 2
    try:
        path.mkdir(parents=True, exist_ok=True)   # 幂等；不存在时下游写文件会失败，替调用方省一步
    except OSError as e:
        print(f"shared_dir: 无法创建 {path}：{e}", file=sys.stderr)
        print("✗ 未解析（目录不可创建）", file=sys.stderr)
        return 2
    print(describe_checkout_dir(path, rel, where))
    print(str(path))
    return 0


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
