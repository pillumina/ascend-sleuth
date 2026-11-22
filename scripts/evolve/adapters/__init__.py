"""现有脚本的薄包装（adapter 层）。

依赖方向：``adapters`` 可以反向 import 旧脚本（``s2_replay`` / ``eval_arena`` /
``verify_evidence`` / ``ev_proposal`` / ``evolution_health`` / ``metrics_health``），
核心模块不能 import 这里。包装只做参数整理与返回形状转换，判定、池与统计仍由
旧脚本或核心包实现，不在这里复制。

旧脚本位于 ``scripts/`` 下，不在包内。运行入口（``scripts/evolve.py``）会把
``scripts/`` 放进 ``sys.path``；直接 import 本包时若找不到旧脚本，抛
``AdapterError`` 并说明修法，不把 ImportError 变成一句无上下文的栈。
"""

import importlib
from typing import Any


class AdapterError(RuntimeError):
    """旧脚本不可用或外部输入格式不对；调用方应转成可照做的提示。"""


def load_legacy(module_name: str) -> Any:
    """按模块名加载 ``scripts/`` 下的旧脚本。

    ``scripts/evolve.py`` 默认把 ``scripts/`` 放进 ``sys.path``；测试与直接调用
    本包时也需要这一条。导入失败时把模块名、原始原因与修法一起抛出，避免只看到
    ``No module named ...`` 而不知道缺的是路径还是依赖。
    """
    name = str(module_name)
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise AdapterError(
            f"cannot import legacy script {name!r}: {exc}. "
            f"Run from the repository checkout or put scripts/ on sys.path "
            f"(scripts/evolve.py does this automatically)."
        ) from exc
