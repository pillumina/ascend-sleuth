"""scripts/ 顶层模块的 import 图不能有环。

平铺命名空间里，两个脚本互相 import 会让"改一个"牵动另一个，也让独立测试变难。
`ev_proposal` 与 `ev_board_data` 曾互相依赖；共享判定下沉到 `_ev_cards` 后断开。
"""

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _graph():
    modules = {p.stem for p in SCRIPTS.glob("*.py")}
    graph = {}
    for name in modules:
        tree = ast.parse((SCRIPTS / f"{name}.py").read_text(encoding="utf-8"))
        edges = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                edges.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                edges.add(node.module.split(".")[0])
        graph[name] = {edge for edge in edges if edge in modules and edge != name}
    return graph


def _cycles(graph):
    found = []
    state = {}

    def visit(node, stack):
        state[node] = 1
        for nxt in graph.get(node, ()):
            if state.get(nxt) == 1:
                found.append(tuple(stack[stack.index(nxt):] + [nxt]))
            elif state.get(nxt, 0) == 0:
                visit(nxt, stack + [nxt])
        state[node] = 2

    for node in graph:
        if state.get(node, 0) == 0:
            visit(node, [node])
    return found


class ImportCycleTest(unittest.TestCase):
    def test_top_level_scripts_have_no_import_cycles(self):
        self.assertEqual(_cycles(_graph()), [])


if __name__ == "__main__":
    unittest.main()
