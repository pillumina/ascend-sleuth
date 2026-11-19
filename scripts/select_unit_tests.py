#!/usr/bin/env python3
"""select_unit_tests.py —— 按改动文件挑要跑的单元测试（改哪里测哪里，不机械全量）。

为什么要有它：`unit-tests` 是 PR 上最长的 job；改一个脚本通常只需要跑引用它的那几个
测试，全量跑要几分钟，Windows 上更久。

映射怎么来（不维护手写映射表）：从源码现算，避免脚本/测试改名后表腐烂——
  1. 从 `tests/` 下 `test_*.py` 的 AST 取两类引用：import 的模块名（子包按点分模块名，
     如 `evolve.runner`）；字符串字面量里的 `scripts/<路径>` 或脚本文件名。
  2. 从 `scripts/**/*.py` 的 AST 取脚本之间的 import 关系（含包内相对导入，
     如 `from .decision import x`），按**反向依赖闭包**扩张改动的脚本。
  3. 选中「引用到受影响模块」的测试模块，加上本 PR 改过的测试模块。
  4. 没有任何引用的「孤儿测试」在 scripts/ 有改动时都会跑（它们可能动态遍历脚本目录，
     例如 test_subprocess_encoding 逐文件跑脚本，静态扫描看不到目标）。
  5. 静态扫描看不出归属的子目录单独登记消费方（`DIR_CONSUMERS`）：importlib 按路径
     加载的文件、被面板脚本当资源读的文件。

包内模块的连带：改包 `__init__.py` 会让包内每个模块都受影响（import 子模块会先执行
`__init__`）；改包内某个模块只带出 import 它的模块。

回退全量（宁可全跑，不可漏跑；每条回退都在 stderr 打一行理由）：
  · `--all`：changes job 判基线不可比，或 CI 自身（.github/**）有改动时由 workflow 传这个；
  · 改动了 `.github/` 下文件；
  · 改动了 `tests/` 下非 `test_*.py` 文件（共享夹具与助手）；
  · 改动里出现删除/不存在的脚本（测试可能 import 它，静态扫描的模块表已不含它）；
  · 改动里删除了测试文件（没有可跑的模块，不判全量就等于删测试即放行）；
  · 改动的脚本或任一 `tests/test_*.py` 解析失败（读不出 import 关系）；
  · 子目录下的文件既不在 Python 包里、也没有登记消费方（静态扫描看不出谁用它）。

覆盖边界（约定，不是硬保证）：测试通过 f-string 或变量拼出的脚本路径引用时静态扫描
看不到，可能漏选。子包内的相对导入、包 `__init__` 的连带、登记过的动态目录都已覆盖；
出现新的动态目录时先在 `DIR_CONSUMERS` 登记，否则该目录的改动回退全量（多跑，不漏跑）。

用法（CI 由 `changes` job 提供改动文件列表）：
  git diff --name-only origin/main...HEAD | python3 scripts/select_unit_tests.py
  python3 scripts/select_unit_tests.py --all          # 强制全量，输出 `ALL`
  python3 scripts/select_unit_tests.py --all --shard 2/4   # 全量取第 2 片（共 4 片）
  echo 'scripts/build_index.py' | python3 scripts/select_unit_tests.py   # 本地手跑

输出（stdout）：`ALL`，或每行一个测试模块（`tests.test_xxx`）。带 `--shard I/N` 时始终
输出模块列表（全量会先展开成模块再切），供 CI 把长跑 job 拆成 N 个并行 job。切片按列表
轮转，只保证不重不漏。
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
TEST_FILE_RE = re.compile(r"^tests/(?:.+?/)?(test[A-Za-z0-9_]*\.py)$")
SHARD_RE = re.compile(r"^(\d+)/(\d+)$")
# 数据目录 → 消费它的脚本：数据文件不是脚本，静态扫描看不出归属。不登记的话，
# 只改数据的 PR 会选中空集（"没跑"与"跑了没命中"同形）。
DATA_CONSUMERS = {"source-catalog.d": {"src_fetch", "source_catalog"}}
# 动态目录 → 消费它的脚本。这些目录里的文件不被任何模块 import：`platforms/` 由
# pr_status 用 importlib 按路径加载，`kb-explorer/` 由 build_kb_explorer 拼装，
# `fixtures/` 与 `lib/` 被面板脚本当资源读。空集合＝没有 Python 单元测试读它：
# `fixtures/` 与 `lib/` 的落在 panel-checks，`kb-explorer/` 目前没有任何门覆盖。
DIR_CONSUMERS: dict[str, set[str]] = {
    "scripts/platforms": {"pr_status", "doctor"},
    "scripts/kb-explorer": {"build_kb_explorer"},
    "scripts/fixtures": set(),
    "scripts/lib": set(),
}


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


def _module_alias(rel: Path) -> str:
    """`scripts/` 下的相对路径 → 点分模块名（包 `__init__.py` 用包名）。"""
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _script_modules(root: Path) -> list[tuple[str, Path]]:
    """`scripts/**/*.py` 的点分模块名与路径。同名（`evolve.py` 与 `evolve/`）两条都留：
    运行期包会遮住同名模块，但静态选择宁可把两边的影响都带上。"""
    out: list[tuple[str, Path]] = []
    directory = root / SCRIPT_DIR
    if not directory.is_dir():
        return out
    for path in sorted(directory.rglob("*.py")):
        alias = _module_alias(path.relative_to(directory))
        if alias:
            out.append((alias, path))
    return out


def _script_files(root: Path) -> dict[str, Path]:
    """`scripts/` 顶层的文件名 → 路径（含 .py / .js / .mjs / .sh），供字符串字面量匹配。"""
    out: dict[str, Path] = {}
    directory = root / SCRIPT_DIR
    if not directory.is_dir():
        return out
    for path in sorted(directory.iterdir()):
        if path.is_file():
            out[path.name] = path
    return out


def _resolved_base(node: ast.ImportFrom, package: tuple[str, ...]) -> str:
    """`from ...` 的点分基准：绝对导入原样，相对导入按当前包层级回退。"""
    if node.level == 0:
        return node.module or ""
    keep = len(package) - (node.level - 1)
    if keep < 0:
        return ""
    parts = list(package[:keep])
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _import_names(tree: ast.Module, package: tuple[str, ...]) -> set[str]:
    """本文件 import 到的点分模块名（只给候选，是否存在由调用方对模块表）。

    不展开各级前缀：`import evolve.runner` 只记 `evolve.runner`。包 `__init__` 的连带
    在 `select` 里按「被改的是 `__init__.py`」展开——否则每个 import 子模块的文件都会被
    当成 import 了包名，改包内任一模块都会把整个包带进来。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _resolved_base(node, package)
            if not base:
                continue
            names.add(base)
            for alias in node.names:
                if alias.name != "*":
                    # `from pkg.mod import name`：name 也可能是一个子模块
                    names.add(f"{base}.{alias.name}")
    return names


def _string_constants(tree: ast.Module) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _package_of(alias: str, path: Path) -> tuple[str, ...]:
    """相对导入的基准包。`__init__.py` 的包是它自己（`evolve.sources`），不是父包。"""
    parts = tuple(alias.split("."))
    return parts if path.name == "__init__.py" else parts[:-1]


def _reverse_deps(entries: list[tuple[str, Path]]) -> dict[str, set[str]]:
    """模块 → 直接 import 它的模块。"""
    aliases = {alias for alias, _ in entries}
    reverse: dict[str, set[str]] = {alias: set() for alias in aliases}
    for alias, path in entries:
        try:
            tree = _parse(path)
        except _Unparseable:
            # 未被改动的脚本解析失败不阻断选择：它没有反向依赖可算，测试引用仍按名字匹配。
            continue
        package = _package_of(alias, path)
        for name in _import_names(tree, package) & aliases:
            reverse.setdefault(name, set()).add(alias)
    return reverse


def _reference_from_string(
    text: str,
    aliases: set[str],
    script_files: dict[str, Path],
) -> str | None:
    """字符串字面量 → 它引用的脚本别名；认不出返回 None。"""
    if text.startswith(SCRIPT_DIR + "/"):
        rel = text[len(SCRIPT_DIR) + 1:]
        if rel.endswith(".py"):
            alias = _module_alias(Path(rel))
            return alias if alias in aliases else None
        base = rel.rsplit("/", 1)[-1]
        return Path(base).stem if base in script_files else None
    if text in script_files:
        return Path(text).stem
    return None


def _test_references(
    root: Path,
    aliases: set[str],
    script_files: dict[str, Path],
) -> dict[str, set[str]]:
    """测试模块 → 它引用到的脚本别名集合（import 或脚本路径字面量）。"""
    refs: dict[str, set[str]] = {}
    directory = root / TEST_DIR
    if not directory.is_dir():
        return refs
    for path in sorted(directory.rglob("test*.py")):
        tree = _parse(path)
        module = ".".join(path.relative_to(root).with_suffix("").parts)
        package = tuple(module.split(".")[:-1])
        found: set[str] = set()
        for name in _import_names(tree, package):
            if name in aliases:
                found.add(name)
        for text in _string_constants(tree):
            name = _reference_from_string(text, aliases, script_files)
            if name is not None:
                found.add(name)
        refs[module] = found
    return refs


def _dependents(seed: str, reverse: dict[str, set[str]]) -> set[str]:
    """从模块名出发，算改动会波及的模块（被谁 import，逐层向上）。"""
    out = {seed}
    stack = [seed]
    while stack:
        cur = stack.pop()
        for dep in reverse.get(cur, ()):
            if dep not in out:
                out.add(dep)
                stack.append(dep)
    return out


def _dir_consumers(path: str) -> set[str] | None:
    """改动文件所在的动态目录 → 消费它的脚本别名；未登记返回 None。"""
    for prefix, consumers in DIR_CONSUMERS.items():
        if path.startswith(prefix + "/"):
            return consumers
    return None


def _unresolved(root: Path, path: str) -> bool:
    """子目录下的文件能否按静态引用判定归属。顶层文件与包内文件都能，返回 False。

    Python 文件要求它所在的每一层目录都是包（有 `__init__.py`），点分名才对得上；
    只有最浅一层是包、里层不是包的目录，点分名找不到它，按全量处理。
    """
    parts = path.split("/")
    if len(parts) <= 2:
        return False
    if _dir_consumers(path) is not None:
        return False
    if not path.endswith(".py"):
        return True
    current = root / SCRIPT_DIR
    for part in parts[1:-1]:
        current = current / part
        if not (current / "__init__.py").is_file():
            return True
    return False


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

    deleted_tests = [
        path for path in tests_side
        if TEST_FILE_RE.match(path) and not (root / path).is_file()
    ]
    if deleted_tests:
        shown = "、".join(deleted_tests[:3])
        return "ALL", [f"改动里删除了测试文件（{shown}）——全量"]

    scripts_changed = [path for path in changed if path.startswith(SCRIPT_DIR + "/")]
    missing = [path for path in scripts_changed if not (root / path).is_file()]
    if missing:
        shown = "、".join(missing[:3])
        return "ALL", [f"改动里含删除/不存在的脚本 {shown}——全量"]

    unresolved = [path for path in scripts_changed if _unresolved(root, path)]
    if unresolved:
        shown = "、".join(unresolved[:3])
        return "ALL", [
            f"子目录下的文件没有登记消费方、也不在 Python 包里（{shown}）——"
            "静态扫描看不出谁用它，按全量"
        ]

    data_stems = {
        stem
        for path in changed
        for prefix, stems in DATA_CONSUMERS.items()
        if path.startswith(prefix + "/")
        for stem in stems
    }
    entries = _script_modules(root)
    aliases = {alias for alias, _ in entries}
    script_files = _script_files(root)

    # 每个改动文件 → 它直接影响的模块名（.py 用点分名，其余用文件名主干；动态目录
    # 再并上登记过的消费方）。分开记是为了后面按文件报"没有测试覆盖"。
    file_roots: dict[str, set[str]] = {path: set() for path in scripts_changed}
    parse_targets: list[tuple[str, Path]] = []
    for path in scripts_changed:
        if path.endswith(".py"):
            alias = _module_alias(Path(path).relative_to(SCRIPT_DIR))
            file_roots[path].add(alias)
            parse_targets.append((alias, root / path))
        else:
            file_roots[path].add(Path(path).stem)
        consumers = _dir_consumers(path)
        if consumers:
            file_roots[path] |= consumers

    for alias, path in parse_targets:
        try:
            _parse(path)
        except _Unparseable:
            return "ALL", [f"改动的脚本解析失败（{alias}）——全量"]

    try:
        refs = _test_references(root, aliases, script_files)
    except _Unparseable:
        return "ALL", ["测试源码解析失败（读不出 import 关系）——全量"]

    reverse = _reverse_deps(entries)
    # 改包 `__init__.py` 时包内每个模块都受影响（import 子模块会先执行 `__init__`）：
    # 把成员一并当起点。只在"被改的是 `__init__.py`"时展开——不能按"这个名字有成员"
    # 判断：`scripts/evolve.py` 与包 `evolve/` 同名，按名字判断会把入口文件当成包。
    seeds: set[str] = set(data_stems)
    for path, roots in file_roots.items():
        seeds |= roots
        if path.endswith("/__init__.py"):
            for alias in roots:
                seeds |= {name for name in aliases if name.startswith(alias + ".")}
    affected: set[str] = set()
    for seed in seeds:
        affected |= _dependents(seed, reverse)

    changed_tests = {
        ".".join(Path(path).with_suffix("").parts)
        for path in tests_side if TEST_FILE_RE.match(path)
    }
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
    uncovered: list[str] = []
    for path, roots in file_roots.items():
        reach: set[str] = set()
        for alias in roots:
            reach |= _dependents(alias, reverse)
        if not reach & covered:
            uncovered.append(path)
    uncovered.extend(sorted(stem for stem in data_stems if not covered & {stem}))
    if uncovered:
        notes.append(
            "以下改动的脚本没有单元测试覆盖（全量跑也不触达）：" + "、".join(sorted(uncovered))
        )
    notes.append(f"选中 {len(selected)} 个测试模块（共 {len(refs)} 个）")
    return sorted(selected), notes


def all_test_modules(root: Path) -> list[str]:
    """`tests/` 下的测试模块（供 `--shard` 切全量）。

    取法与 `unittest discover` 的默认 pattern 一致（`test*.py`），子目录里的测试也
    算进去——`--shard` 是 Windows 那四个 job 的唯一输入，漏一个就是静默不跑。
    """
    directory = root / TEST_DIR
    if not directory.is_dir():
        raise _Unparseable(directory, FileNotFoundError("tests/ 不存在"))
    return sorted(
        ".".join(path.relative_to(root).with_suffix("").parts)
        for path in directory.rglob("test*.py")
        if path.is_file()
    )


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

    root = Path(args.root)
    if args.force_all:
        changed: list[str] = []
    elif args.changed_from == "-":
        changed = sys.stdin.read().splitlines()
    else:
        changed = Path(args.changed_from).read_text(encoding="utf-8").splitlines()

    result, notes = select(root, changed, force_all=args.force_all)
    if args.shard is not None:
        try:
            items = all_test_modules(root) if result == "ALL" else result
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
