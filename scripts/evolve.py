#!/usr/bin/env python3
"""evolve.py —— 自演进模块的薄 CLI 包装。

保持 ``python3 scripts/evolve.py ...`` 入口；实现与规则在 ``scripts/evolve/``。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _stdio import pin_utf8_stdio  # noqa: E402
from evolve.cli import main  # noqa: E402


if __name__ == "__main__":
    pin_utf8_stdio()
    raise SystemExit(main())
