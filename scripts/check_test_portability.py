#!/usr/bin/env python3
"""PR 守卫：`tests/` 下的跨平台可移植性陷阱。

为什么有这一道：Unit 测试在 CI 只跑 ubuntu-latest。依赖本机编码、路径分隔符、字节换行或平台
专有 API 的用例在 Linux 上通过，合入后才在 Windows 上红。这类失败与业务回归在输出上不可区分，
排查成本会记到错误的对象上。这里把能机械判定的形态在 PR 期拦下。

规则编号 R1–R6（对应 docs/spec/test-portability.md 的 R1–R6）：
  R1 文本模式的 open() / io.open() / Path.read_text() / Path.write_text() 没有 encoding。
  R2 subprocess 开了 text=True（或 universal_newlines=True）却没有 encoding。
  R3 子进程命令里写死解释器字面量 "python" / "python3" / "py"，应改用 sys.executable。
  R4 startswith() / endswith() 的字符串字面量以 "/" 开头（Windows 的分隔符是 "\\"）。
  R5 read_bytes() 链上直接 replace(b"\\n", b"\\r\\n")，没有先归一换行。
  R6 导入平台专有模块（fcntl / pwd / grp / termios / posix / msvcrt / winreg），
     或调用 os.fork / os.symlink / os.chmod，且没有被 skip 装饰器、平台分支或豁免覆盖。

豁免：违规行写 `# portability-check: allow <具体理由>`。理由为空不算豁免。
豁免只对违规所在行（输出里的行号那一行）生效。

判法：只读 AST，不读字符串内容，所以夹具字符串里的 `open(`、`subprocess.run(` 一类文本不会误报。
直接写进字符串的 `"python3 scripts/x.py"` 命令也不报。

覆盖边界：
  R1、R2 只判有没有 encoding，不判值是不是 utf-8；`encoding=None` 按没有处理。
  R1 的 mode 不是字面量时不判（变量 mode 可能是二进制，判不了）。
  R1 不判 `Path.open()` 这类非模块级 open 调用；也不认识用位置参数传的 encoding
      （`open(path, "w", -1, "utf-8")` 会按缺 encoding 报，属误报；本仓统一用关键字传）。
  R2 的 text 参数不是字面量 True 时不判。
  R3 只认字面量，且只认命令位置：argv 列表首项、subprocess 的首参、或带 `*args` 转发的调用参数。
     经变量拼接的解释器名不报；`subprocess.run("python3 x", shell=True)` 这类整串命令不报。
  R4 只认单个字面量参数；`startswith(("/", "\\\\"))` 这种两种分隔符都列的元组不报。
  R5 只在 read_bytes() 所在的同一个表达式里判；先归一或另起变量再转换不报。
  R6 认 skipIf / skipUnless / skip / skipif 装饰器与 `os.name` / `sys.platform` / `platform.system`
      分支；try/except ImportError 的降级写法与 monkeypatch 掉模块的写法认不出，需用豁免注释。
  R6 的分支判定只看形态：if 条件里出现平台名就当作已分平台，不核逻辑是否正确。
  R6 只看装饰器名，skip 条件方向写反（`@skipIf(os.name == "posix")`）也会被当作已跳过。
  R6 只认列出的模块与 os.fork / os.symlink / os.chmod；os.geteuid() 等其它平台专有调用不报。
  扫描范围：`<root>/tests/` 下所有 `*.py`（含 `groom_fixtures.py` 这类共享夹具）。

误报边界：
  R1 把任意对象的 read_text() / write_text() 都当文本 IO 调用，不核对象是不是 Path。
  R3 的 argv 列表规则对首项是解释器名的普通数据列表同样会报；`print("python3", *names)`
      这类带星号参数的普通调用也会报。确属数据的加豁免注释。
  R4 会把 `git show` 输出这类恒用 "/" 的字符串也报出，URL 形态（`endswith("/v1/")`）同样会报；
      判定为平台无关时加豁免注释。
  R5 会把只用于断言、不写盘的 `read_bytes().replace(b"\\n", b"\\r\\n")` 也报出；确无 Windows
      写盘风险时加豁免注释。
  豁免只认输出行号那一行；写在多行语句的其它行不生效，需挪到报告行号那一行。

用法：
  python3 scripts/check_test_portability.py                  # 扫本仓库
  python3 scripts/check_test_portability.py --root <仓库根>
退出码：0 = 无违规；1 = 有违规；2 = 扫描失败（目录缺失、文件语法错误、非 UTF-8）。
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

from _stdio import pin_utf8_stdio

SUBPROCESS_CALLS = {"run", "check_output", "call", "check_call", "Popen"}
TEXT_KEYS = ("text", "universal_newlines")
PYTHON_NAMES = {
    "python", "python2", "python3", "py",
    "python.exe", "python2.exe", "python3.exe", "py.exe",
}
PLATFORM_MODULES = {"fcntl", "pwd", "grp", "termios", "posix", "msvcrt", "winreg"}
WINDOWS_ONLY = {"msvcrt", "winreg"}
PLATFORM_CALLS = {"fork", "symlink", "chmod"}
PLATFORM_CONSTANTS = {"nt", "posix", "win32", "linux", "darwin", "cygwin"}
ALLOW_RE = re.compile(r"#\s*portability-check:\s*allow\b(?P<reason>.*)$")


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    code: str
    message: str
    fix: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: [{self.code}] {self.message}；修法：{self.fix}"


class ScanError(Exception):
    """扫描失败：目录缺失、文件读不出、语法错误。CLI 把它翻成退出码 2。"""


# --------------------------------------------------------------------------- 豁免


def exempt_lines(source: str) -> set:
    """返回带有效豁免注释的行号。空理由不算；字符串里的同形文本不算。"""
    lines = set()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            match = ALLOW_RE.search(token.string)
            if match and match.group("reason").strip():
                lines.add(token.start[0])
    except (tokenize.TokenError, IndentationError):
        return lines
    return lines


# --------------------------------------------------------------------------- AST 辅助


def parent_map(tree: ast.AST) -> dict:
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def has_kwarg(call: ast.Call, name: str) -> bool:
    return any(kw.arg == name for kw in call.keywords)


def kwarg(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def encoding_pinned(call: ast.Call) -> bool:
    if not has_kwarg(call, "encoding"):
        return False
    value = kwarg(call, "encoding")
    return not (isinstance(value, ast.Constant) and value.value is None)


def is_subprocess_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
        and func.attr in SUBPROCESS_CALLS
    )


def is_python_literal(node) -> bool:
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return False
    base = node.value.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    return base in PYTHON_NAMES


def _callee_name(func) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def is_skip_decorator(decorator) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return _callee_name(target).lower().startswith("skip")


def is_platform_test(test) -> bool:
    for node in ast.walk(test):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            owner, attr = node.value.id, node.attr
            if owner == "os" and attr == "name":
                return True
            if owner == "sys" and attr == "platform":
                return True
            if owner == "platform" and attr == "system":
                return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.lower() in PLATFORM_CONSTANTS:
                return True
    return False


def platform_guarded(node, parents) -> bool:
    """被 skip 装饰器覆盖，或落在平台分支里的节点视为已显式分平台。"""
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if any(is_skip_decorator(dec) for dec in current.decorator_list):
                return True
        elif isinstance(current, ast.If) and is_platform_test(current.test):
            return True
    return False


def is_normalizing_replace(call) -> bool:
    """`replace(b"\\r\\n", b"\\n")` 这种先把 CRLF 归一成 LF 的调用。"""
    if not isinstance(call, ast.Call):
        return False
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "replace"):
        return False
    if len(call.args) < 2:
        return False
    first, second = call.args[0], call.args[1]
    return (
        isinstance(first, ast.Constant) and first.value == b"\r\n"
        and isinstance(second, ast.Constant) and second.value == b"\n"
    )


def _walk_contains_read_bytes(node) -> bool:
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "read_bytes"
        ):
            return True
    return False


# --------------------------------------------------------------------------- 各条规则


def check_r1(node: ast.Call):
    """文本 IO 缺 encoding。返回 (message, fix) 或 None。"""
    func = node.func
    path_method = None
    if isinstance(func, ast.Attribute) and func.attr in {"read_text", "write_text"}:
        path_method = func.attr
        label = f"Path.{path_method}()"
    elif isinstance(func, ast.Name) and func.id == "open":
        label = "open()"
    elif (
        isinstance(func, ast.Attribute)
        and func.attr == "open"
        and isinstance(func.value, ast.Name)
        and func.value.id in {"io", "builtins"}
    ):
        label = f"{func.value.id}.open()"
    else:
        return None
    if encoding_pinned(node):
        return None
    if path_method:
        fix = f'加 encoding="utf-8"：path.{path_method}(encoding="utf-8")'
    else:
        mode_node = node.args[1] if len(node.args) >= 2 else kwarg(node, "mode")
        if mode_node is not None:
            if not (isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str)):
                return None
            if "b" in mode_node.value:
                return None
        fix = '加 encoding="utf-8"：open(path, mode, encoding="utf-8")'
    message = f"{label} 的文本模式没有指定 encoding；Windows 中文环境按 cp936 解码"
    return message, fix


def check_r2(node: ast.Call):
    if not is_subprocess_call(node):
        return None
    if encoding_pinned(node):
        return None
    text_mode = False
    for key in TEXT_KEYS:
        if not has_kwarg(node, key):
            continue
        value = kwarg(node, key)
        if isinstance(value, ast.Constant) and value.value is True:
            text_mode = True
    if not text_mode:
        return None
    message = "subprocess 开了文本模式但没有指定 encoding；父进程按本机 locale 解码子进程输出"
    fix = '在调用里加 encoding="utf-8"，读外部输出时再加 errors="replace"'
    return message, fix


def check_r3(node: ast.Call):
    """发现写死的解释器字面量。返回 [(literal_node, message, fix)]。"""
    hits = []
    if is_subprocess_call(node) and node.args:
        command = node.args[0]
        if is_python_literal(command):
            hits.append(command)
        elif isinstance(command, (ast.List, ast.Tuple)) and command.elts:
            if is_python_literal(command.elts[0]):
                hits.append(command.elts[0])
    if any(isinstance(arg, ast.Starred) for arg in node.args):
        for arg in node.args:
            if is_python_literal(arg):
                hits.append(arg)
    message = "子进程命令写死了解释器字面量，Windows 上可能没有这个可执行文件"
    fix = "改用 sys.executable：[sys.executable, script, *args]"
    return [(hit, message, fix) for hit in hits]


def check_r3_argv_list(node):
    """argv 列表首项写死解释器（命令先存进变量再传给 subprocess 的写法）。"""
    if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
        return None
    if not is_python_literal(node.elts[0]):
        return None
    message = "argv 列表首项写死了解释器字面量，Windows 上可能没有这个可执行文件"
    fix = "改用 sys.executable：[sys.executable, script, *args]"
    return node.elts[0], message, fix


def check_r4(node: ast.Call):
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr in {"startswith", "endswith"}):
        return None
    if not node.args:
        return None
    literal = node.args[0]
    if not (
        isinstance(literal, ast.Constant)
        and isinstance(literal.value, str)
        and literal.value.startswith("/")
    ):
        return None
    message = (
        f"{func.attr}({literal.value!r}) 的参数以 \"/\" 开头；"
        "Windows 的路径分隔符是 \"\\\\\"，这类断言恒假"
    )
    fix = (
        '先归一成 POSIX 形态再比较（str(p).replace(os.sep, "/")、Path(p).as_posix()），'
        "或用 Path(p).name / Path(p) == 期望 判断"
    )
    return literal, message, fix


def check_r5(node: ast.Call):
    if not (isinstance(node.func, ast.Attribute) and node.func.attr == "replace"):
        return None
    if len(node.args) < 2:
        return None
    first, second = node.args[0], node.args[1]
    if not (
        isinstance(first, ast.Constant) and first.value == b"\n"
        and isinstance(second, ast.Constant) and second.value == b"\r\n"
    ):
        return None
    receiver = node.func.value
    if not _walk_contains_read_bytes(receiver):
        return None
    for child in ast.walk(receiver):
        if is_normalizing_replace(child):
            return None
    message = (
        'read_bytes() 的结果直接 replace(b"\\n", b"\\r\\n")；'
        "Windows 上 write_text 已按 CRLF 写盘，替换后得到 \\r\\r\\n"
    )
    fix = (
        '先归一换行再转 CRLF：raw.replace(b"\\r\\n", b"\\n").replace(b"\\n", b"\\r\\n")，'
        "或直接用 write_bytes 写出确定的字节"
    )
    return message, fix


def check_r6_import(node, parents):
    if isinstance(node, ast.Import):
        names = [alias.name.split(".")[0] for alias in node.names]
    elif isinstance(node, ast.ImportFrom):
        names = [(node.module or "").split(".")[0]]
    else:
        return None
    names = [name for name in names if name in PLATFORM_MODULES]
    if not names:
        return None
    if platform_guarded(node, parents):
        return None
    module = names[0]
    if module in WINDOWS_ONLY:
        message = f'导入了平台专有模块 "{module}"；非 Windows 上 import 直接失败'
        fix = (
            '在用例里 import 并加 @unittest.skipUnless(os.name == "nt", "<理由>")，'
            "或改用跨平台等价物"
        )
    else:
        message = f'导入了平台专有模块 "{module}"；Windows 上 import 直接失败'
        fix = (
            '在用例里 import 并加 @unittest.skipUnless(os.name == "posix", "<理由>")，'
            "或改用跨平台等价物"
        )
    return message, fix


def check_r6_call(node: ast.Call, parents):
    func = node.func
    if not (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
        and func.attr in PLATFORM_CALLS
    ):
        return None
    if platform_guarded(node, parents):
        return None
    name = f"os.{func.attr}()"
    if func.attr == "fork":
        message = f"调用了 {name}；Windows 上没有这个函数"
        fix = (
            "改用 subprocess 或 multiprocessing 启动子进程，"
            '或给用例加 @unittest.skipUnless(os.name == "posix", "<理由>")'
        )
    elif func.attr == "symlink":
        message = f"调用了 {name}；Windows 上创建符号链接需要开发者模式或管理员权限"
        fix = (
            "改用不依赖符号链接的夹具，"
            '或给用例加 @unittest.skipUnless(os.name == "posix", "<理由>")'
        )
    else:
        message = f"调用了 {name}；Windows 上只实现只读位，与 POSIX 权限语义不同"
        fix = (
            "改断言只读位（stat 的只读属性），"
            '或给用例加 @unittest.skipUnless(os.name == "posix", "<理由>")'
        )
    return message, fix


# --------------------------------------------------------------------------- 扫描入口


def scan_source(rel_path: str, source: str):
    """扫一段测试源码，返回按行号与规则号排序的违规列表。"""
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError as exc:
        raise ScanError(f"{rel_path}:{exc.lineno}: 语法错误：{exc.msg}") from exc
    parents = parent_map(tree)
    exempt = exempt_lines(source)
    found = {}

    def add(node, code, message, fix):
        line = getattr(node, "lineno", 0)
        if line in exempt:
            return
        key = (line, code)
        if key not in found:
            found[key] = Violation(rel_path, line, code, message, fix)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            hit = check_r1(node)
            if hit:
                add(node, "R1", *hit)
            hit = check_r2(node)
            if hit:
                add(node, "R2", *hit)
            for literal, message, fix in check_r3(node):
                add(literal, "R3", message, fix)
            hit = check_r4(node)
            if hit:
                add(hit[0], "R4", hit[1], hit[2])
            hit = check_r5(node)
            if hit:
                add(node, "R5", *hit)
            hit = check_r6_call(node, parents)
            if hit:
                add(node, "R6", *hit)
        elif isinstance(node, (ast.List, ast.Tuple)):
            hit = check_r3_argv_list(node)
            if hit:
                add(hit[0], "R3", hit[1], hit[2])
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            hit = check_r6_import(node, parents)
            if hit:
                add(node, "R6", *hit)

    return sorted(found.values(), key=lambda v: (v.line, v.code))


def scan_tree(root) -> list:
    """扫 `<root>/tests/**/*.py`，路径按相对 root 的 POSIX 形态输出。"""
    root = Path(root)
    tests_dir = root / "tests"
    if not tests_dir.is_dir():
        raise ScanError(f"{tests_dir} 不是目录")
    try:
        files = sorted(
            (path for path in tests_dir.rglob("*.py") if path.is_file()),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    except OSError as exc:
        raise ScanError(f"{tests_dir} 列目录失败：{exc}") from exc
    if not files:
        raise ScanError(f"{tests_dir} 下没有 .py 文件")
    violations = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ScanError(f"{rel} 读不出 UTF-8 文本：{exc}") from exc
        violations.extend(scan_source(rel, source))
    return sorted(violations, key=lambda v: (v.path, v.line, v.code))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="扫描 tests/ 下的跨平台可移植性陷阱")
    parser.add_argument(
        "--root",
        default=None,
        help="仓库根（默认取脚本上两级）",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    try:
        violations = scan_tree(root)
    except ScanError as exc:
        print(f"扫描失败：{exc}", file=sys.stderr)
        return 2
    if not violations:
        print("tests/ 下未发现可移植性违规")
        return 0
    for violation in violations:
        print(violation.format())
    print(f"共 {len(violations)} 处违规。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
