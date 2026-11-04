"""不变量：`scripts/` 与 `tests/` 下走**文本模式**的 subprocess 调用必须自己钉 `encoding="utf-8"`。

为什么写进结构而不是靠记性（原则二「不变量写进结构」）：`subprocess.run(..., text=True)` 不钉
encoding 时按**本机 locale** 解码子进程输出，中文 Windows 上是 GBK；子进程只要打印 UTF-8 中文，
读取线程就抛 `UnicodeDecodeError`、`stdout` 退化成 `None`，调用点随后崩成一句与本意无关的
`AttributeError`。实测代价：`scripts/check_handoff.py` 的本地自检在 Windows 上整条跑不完，
报错里看不出真因（同仓 `exec_log_path` / `log_skill_exec` / `src_fetch` / `rehearse_evolve_loop`
早已是"钉 utf-8 + errors=replace"的写法，纯靠各自记得）。

2026-11 增补扫描面：这条不变量原来只扫 `scripts/`。Windows 检查套件的 ERROR 多数落在
`tests/` 自己的 `subprocess(..., text=True)`——父进程按 GBK 解码子进程的 UTF-8 输出。只扫
`scripts/` 时，测试侧这一半漏钉不报错：新测试照抄旧写法，Linux CI 全绿，Windows 上才失败。

判的是**源码结构**，不是行为：AST 找 `subprocess.<run|check_output|call|check_call|Popen>` 里
`text=True`（或 `universal_newlines=True`）而没有 `encoding=` 的调用点。这样新加的脚本与测试
自动被覆盖，不必往测试里补名字。
"""
import ast
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
TESTS = REPO / "tests"
SCANNED = (("scripts", SCRIPTS), ("tests", TESTS))
CALLS = {"run", "check_output", "call", "check_call", "Popen"}
TEXT_KEYS = ("text", "universal_newlines")


def _is_subprocess_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    return (isinstance(fn, ast.Attribute)
            and isinstance(fn.value, ast.Name)
            and fn.value.id == "subprocess"
            and fn.attr in CALLS)


def _kwarg(node: ast.Call, key: str):
    for k in node.keywords:
        if k.arg == key:
            return k.value
    return None


def _is_true(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def text_mode_calls_without_encoding(root: pathlib.Path):
    """返回文本模式却没钉 encoding 的调用点（`文件:行` 列表）。"""
    offenders = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not _is_subprocess_call(node):
                continue
            if not any(_is_true(_kwarg(node, key)) for key in TEXT_KEYS):
                continue
            if _kwarg(node, "encoding") is not None:
                continue
            offenders.append(f"{path.name}:{node.lineno}")
    return offenders


class SubprocessEncodingTest(unittest.TestCase):
    def test_roots_are_scanned_at_all(self):
        # 前提自检：扫不到文件时这条不变量会假绿（目录改名或挪位就会这样）。
        for label, root in SCANNED:
            py = list(root.glob("*.py"))
            self.assertGreater(len(py), 20, f"{label}/ 下只找到 {len(py)} 个文件，路径可能变了")

    def test_text_mode_calls_pin_utf8(self):
        offenders = []
        for label, root in SCANNED:
            offenders += [f"{label}/{x}" for x in text_mode_calls_without_encoding(root)]
        self.assertEqual(
            [], offenders,
            "这些 subprocess 调用开了文本模式却没钉 encoding=\"utf-8\"（中文 Windows 上会按 GBK 解码、"
            "子进程输出非 GBK 时读取线程崩溃）：" + "、".join(offenders))

    def test_detector_catches_the_known_shape(self):
        # 反向对照：把检测器自己喂一个"漏钉"的形状，确认它真会报（否则这条不变量只是一句空话）。
        src = (
            "import subprocess\n"
            "subprocess.run(['git', 'status'], capture_output=True, text=True)\n"
        )
        tree = ast.parse(src)
        bad = [n for n in ast.walk(tree) if _is_subprocess_call(n)
               and any(_is_true(_kwarg(n, key)) for key in TEXT_KEYS)
               and _kwarg(n, "encoding") is None]
        self.assertEqual(1, len(bad))
        good_src = (
            "import subprocess\n"
            "subprocess.run(['git', 'status'], capture_output=True, text=True,"
            " encoding='utf-8', errors='replace')\n"
        )
        good = [n for n in ast.walk(ast.parse(good_src)) if _is_subprocess_call(n)
                and any(_is_true(_kwarg(n, key)) for key in TEXT_KEYS)
                and _kwarg(n, "encoding") is None]
        self.assertEqual([], good)


if __name__ == "__main__":
    unittest.main()
