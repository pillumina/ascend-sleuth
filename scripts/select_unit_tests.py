#!/usr/bin/env python3
"""select_unit_tests.py —— 按改动文件挑要跑的单元测试（改哪里测哪里，不机械全量）。

为什么要有它：`unit-tests` 是 PR 上最长的 job，而改一个脚本只需要跑引用它的那几个测试。
全量跑 805 条测试约 4 分钟；改成按改动选测试后，多数脚本 PR 只跑 1–3 个模块（多数 <5 秒）。

映射怎么来（不维护手写映射表）：从源码现算，避免脚本/测试改名后表腐烂——
  1. 从 `tests/test_*.py` 的 AST 取两类引用：import 的脚本模块名；字符串字面量里的
     `scripts/<文件名>` 或脚本文件名（subprocess 调用脚本时通常这么写）。
  2. 从 `scripts/*.py` 的 AST 取脚本之间的 import 关系，按**反向依赖闭包**扩张改动的脚本
     （改 `_yaml.py` 会带出所有 import 它的脚本，进而带出引用这些脚本的测试）。
  3. 选中「引用到受影响脚本」的测试模块，加上本 PR 改过的测试模块。
  4. 没有任何引用的「孤儿测试」在 scripts/ 有改动时都会跑（它们可能动态遍历脚本目录，
     例如 test_subprocess_encoding 逐文件跑脚本，静态扫描看不到目标）。

回退全量（宁可全跑，不可漏跑；每条回退都在 stderr 打一行理由）：
  · `--all`：changes job 判基线不可比，或 CI 自身（.github/**）有改动时由 workflow 传这个；
  · 改动了 `.github/` 下文件；
  · 改动了 `tests/` 下非 `test_*.py` 文件（共享夹具与助手）；
  · 改动里出现删除/不存在的脚本（测试可能 import 它，静态扫描的模块表已不含它）；
  · 改动的脚本或任一 `tests/test_*.py` 解析失败（读不出 import 关系）。

覆盖边界（约定，不是硬保证）：测试通过 f-string 或变量拼出的脚本路径引用时静态扫描看不到，
可能漏选；出现这种情况时测试注释里写清，或把引用改成字符串字面量。与「全量跑」相比，
唯一不跑的是**没有任何测试引用、且不被任何脚本 import** 的脚本——全量跑也不会触达它。

用法（CI 由 `changes` job 提供改动文件列表）：
  git diff --name-only origin/main...HEAD | python3 scripts/select_unit_tests.py
  python3 scripts/select_unit_tests.py --all          # 强制全量，输出 `ALL`
  python3 scripts/select_unit_tests.py --all --shard 2/4   # 全量取第 2 片（共 4 片）
  echo 'scripts/build_index.py' | python3 scripts/select_unit_tests.py   # 本地手跑

输出（stdout）：`ALL`，或每行一个测试模块（`tests.test_xxx`）。带 `--shard I/N` 时始终
输出模块列表（全量会先展开成模块再切），供 CI 把长跑 job 拆成 N 个并行 job。
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

SCRIPT_DIR = "scripts"
TEST_DIR = "tests"
CI_PREFIX = ".github/"
TEST_FILE_RE = re.compile(r"^tests/(test_[A-Za-z0-9_]+)\.py$")
SCRIPT_REF_RE = re.compile(r"^scripts/([^/]+)$")
SHARD_RE = re.compile(r"^(\d+)/(\d+)$")
# 数据目录 → 消费它的脚本：数据文件不是脚本，静态扫描看不出归属。不登记的话，
# 只改数据的 PR 会选中空集（"没跑"与"跑了没命中"同形）。
DATA_CONSUMERS = {"source-catalog.d": {"src_fetch", "source_catalog"}}


class _Unparseable(Exception):
    """文件读不出/解析不了——选择结果不可信，调用方按全量处理。"""

    def __init__(self, path: Path, err: Exception) -> None:
        super().__init__(f"{path}: {err}")
        self.path = path
        self.err = err


def _parse(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as err:
        raise _Unparseable(path, err) from err


def _import_names(tree: ast.Module) -> set[str]:
    """顶层模块名。不展开别名与包路径——本仓的测试都是 `import <模块> as x` 的写法。"""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _string_constants(tree: ast.Module) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _script_files(root: Path) -> dict[str, Path]:
    """scripts/ 下的文件名 → 路径（含 .py / .js / .mjs / .sh）。"""
    out: dict[str, Path] = {}
    directory = root / SCRIPT_DIR
    if not directory.is_dir():
        return out
    for path in sorted(directory.iterdir()):
        if path.is_file():
            out[path.name] = path
    return out


def _reverse_deps(modules: dict[str, Path]) -> dict[str, set[str]]:
    """脚本模块 stem → 直接 import 它的脚本 stem 集合。"""
    reverse: dict[str, set[str]] = {stem: set() for stem in modules}
    for stem, path in modules.items():
        try:
            tree = _parse(path)
        except _Unparseable:
            # 未被改动的脚本解析失败不阻断选择：它没有反向依赖可算，测试引用仍按文件名匹配。
            continue
        for name in _import_names(tree) & set(modules):
            reverse.setdefault(name, set()).add(stem)
    return reverse


def _test_references(root: Path, script_files: dict[str, Path]) -> dict[str, set[str]]:
    """测试模块 → 它引用到的脚本 stem 集合（import 或脚本文件名字面量）。"""
    stems = {Path(name).stem for name in script_files}
    refs: dict[str, set[str]] = {}
    directory = root / TEST_DIR
    if not directory.is_dir():
        return refs
    for path in sorted(directory.glob("test_*.py")):
        tree = _parse(path)
        found: set[str] = set()
        for name in _import_names(tree):
            if name in stems:
                found.add(name)
        for text in _string_constants(tree):
            match = SCRIPT_REF_RE.match(text)
            name = match.group(1) if match else (text if text in script_files else None)
            if name is not None and name in script_files:
                found.add(Path(name).stem)
        refs[path.stem] = found
    return refs


def _dependents(stem: str, reverse: dict[str, set[str]]) -> set[str]:
    out = {stem}
    stack = [stem]
    while stack:
        cur = stack.pop()
        for dep in reverse.get(cur, ()):
            if dep not in out:
                out.add(dep)
                stack.append(dep)
    return out


def select(
    root: Path,
    changed: list[str],
    *,
    force_all: bool = False,
) -> tuple[list[str] | str, list[str]]:
    """改动文件 → (`ALL` 或测试模块列表, 说明行)。说明行原样进 CI 日志。"""
    changed = [line.strip() for line in changed if line.strip()]
    if force_all:
        return "ALL", ["强制全量（--all：基线不可比 / CI 自身有改动）"]
    if not changed:
        return [], ["没有改动文件——不跑测试"]
    if any(path.startswith(CI_PREFIX) for path in changed):
        return "ALL", ["CI 自身有改动（.github/）——全量"]

    tests_side = [path for path in changed if path.startswith(TEST_DIR + "/")]
    helper = [path for path in tests_side if not TEST_FILE_RE.match(path)]
    if helper:
        shown = "、".join(helper[:3])
        return "ALL", [f"tests/ 下有非 test_*.py 改动（共享夹具/助手）{shown}——全量"]

    scripts_changed = [path for path in changed if path.startswith(SCRIPT_DIR + "/")]
    data_stems = {
        stem
        for path in changed
        for prefix, stems in DATA_CONSUMERS.items()
        if path.startswith(prefix + "/")
        for stem in stems
    }
    missing = [path for path in scripts_changed if not (root / path).is_file()]
    if missing:
        shown = "、".join(missing[:3])
        return "ALL", [f"改动里含删除/不存在的脚本 {shown}——全量"]

    script_files = _script_files(root)
    modules = {path.stem: path for path in script_files.values() if path.suffix == ".py"}
    changed_stems = {Path(path).stem for path in scripts_changed} | data_stems

    for stem in sorted(changed_stems):
        path = modules.get(stem)
        if path is not None:
            try:
                _parse(path)
            except _Unparseable:
                return "ALL", [f"改动的脚本解析失败（{stem}）——全量"]
    try:
        refs = _test_references(root, script_files)
    except _Unparseable:
        return "ALL", ["测试源码解析失败（读不出 import 关系）——全量"]

    reverse = _reverse_deps(modules)
    affected: set[str] = set()
    for stem in changed_stems:
        affected |= _dependents(stem, reverse)

    changed_tests = {m.group(1) for path in tests_side if (m := TEST_FILE_RE.match(path))}
    selected = {name for name, found in refs.items() if found & affected}
    selected |= changed_tests & set(refs)
    if scripts_changed:
        selected |= {name for name, found in refs.items() if not found}

    notes: list[str] = []
    if not selected:
        notes.append(
            "没有单元测试引用这些改动（静态扫描的 import 与文件名字面量都没命中）——跳过；"
            "全量跑也不会触达这些文件"
        )
        return [], notes

    covered: set[str] = set()
    for name in selected:
        covered |= refs[name]
    uncovered = sorted(
        stem for stem in changed_stems
        if not (_dependents(stem, reverse) & covered)
    )
    if uncovered:
        notes.append(
            "以下改动的脚本没有单元测试覆盖（全量跑也不触达）：" + "、".join(uncovered)
        )
    notes.append(f"选中 {len(selected)} 个测试模块（共 {len(refs)} 个）")
    return sorted(f"tests.{name}" for name in selected), notes


def all_test_modules(root: Path) -> list[str]:
    """`tests/` 下全部测试模块（供 `--shard` 切全量）。"""
    directory = root / TEST_DIR
    if not directory.is_dir():
        raise _Unparseable(directory, FileNotFoundError("tests/ 不存在"))
    return sorted(f"tests.{path.stem}" for path in directory.glob("test_*.py") if path.is_file())


def shard(items: list[str], spec: str) -> list[str]:
    """把列表按 `I/N` 轮转切片（I 从 1 起）。切分只保证不重不漏，不按耗时均衡。"""
    match = SHARD_RE.match(spec)
    if match is None:
        raise ValueError(f"--shard 需要 I/N 形式（收到 {spec!r}）")
    index, count = int(match.group(1)), int(match.group(2))
    if count < 1 or not (1 <= index <= count):
        raise ValueError(f"--shard {spec} 越界：I 需在 1..N 之间")
    return [item for i, item in enumerate(items) if i % count == index - 1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按改动文件选单元测试（改哪里测哪里）")
    parser.add_argument(
        "--root", default=str(Path(__file__).resolve().parents[1]),
        help="仓库根（默认本脚本上一级）",
    )
    parser.add_argument(
        "--all", action="store_true", dest="force_all",
        help="强制全量（changes job 判基线不可比或 CI 自身有改动时用）",
    )
    parser.add_argument(
        "--shard", default=None, metavar="I/N",
        help="只输出第 I 片（1 起）测试模块，共 N 片；与 --all 连用时对全量切分",
    )
    parser.add_argument(
        "changed_from", nargs="?", default="-",
        help="改动文件列表（一行一个）；默认读 stdin，`-` 也是 stdin",
    )
    args = parser.parse_args(argv)

    if args.force_all:
        changed: list[str] = []
    elif args.changed_from == "-":
        changed = sys.stdin.read().splitlines()
    else:
        changed = Path(args.changed_from).read_text(encoding="utf-8").splitlines()

    result, notes = select(Path(args.root), changed, force_all=args.force_all)
    if args.shard:
        try:
            items = all_test_modules(Path(args.root)) if result == "ALL" else result
            items = shard(items, args.shard)
        except (ValueError, _Unparseable) as exc:
            print(f"select_unit_tests: {exc}", file=sys.stderr)
            return 2
        notes.append(f"分片 {args.shard}：{len(items)} 个测试模块")
        result = items
    # Windows 的 Python 文本 stdout 会把 \n 翻成 \r\n。CI 用 $(...) 取这份模块列表时每行会带
    # \r，unittest 报 `No module named 'tests.x\r'`（本仓 Windows job 实测）。这份输出是给机器
    # 消费的，钉成 LF；控制台/管道都按 LF 处理，不影响人读。
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(newline="\n")
        except (AttributeError, ValueError):
            pass
    for note in notes:
        print(f"select_unit_tests: {note}", file=sys.stderr)
    if result == "ALL":
        print("ALL")
    else:
        print("\n".join(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
