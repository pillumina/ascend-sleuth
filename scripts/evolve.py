#!/usr/bin/env python3
"""evolve.py —— 自演进模块的薄 CLI 包装。

保持 ``python3 scripts/evolve.py ...`` 入口；实现与规则在 ``scripts/evolve/``。
退出码、stdio 与 Ctrl-C / BrokenPipe 的归一走 ``scripts/_cli.py``，与其余脚本入口一致。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cli import main_entry  # noqa: E402
from evolve.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main_entry(main))
