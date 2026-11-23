#!/usr/bin/env python3
"""知识条目的唯一读取入口：枚举、解析、路径→命名空间。

为什么单独一个模块：``knowledge/`` 的「哪些文件算条目」「文件路径怎么折成命名空间」
此前在 build_index、tag_hygiene、route_check 各写一份。三份的边界已经不同——
build_index 排除了 ``platforms`` 段，另两份没有。目录规则改一次漏一处不会报错，
只会让索引、标签检查与路由检查对同一条 case 给出不同答案。

本模块只管**读**：不投影成索引行、不校验 case 字段、不写文件。索引的投影与排版
仍归 build_index，字段校验仍归 verify_case_draft。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Tuple

import yaml

from _yaml import load_file

KNOWLEDGE_DIR = "knowledge"
WORKLOAD_DIRS = ("inference", "training")

# 归档与生成物目录不是条目来源；总表也是生成物。
SKIP_TOP_DIRS = ("_archive", "_index")


def iter_case_files(root: Path, *, include_archive: bool = False) -> Iterator[Tuple[Path, Path]]:
    """→ (绝对路径, 相对 knowledge/ 的路径)。默认跳过归档目录与生成的索引文件。

    ``include_archive=True`` 只跳过 ``_index``，用于 id 唯一性这类「归档条目也算数」的检查。
    """
    kdir = Path(root) / KNOWLEDGE_DIR
    for path in sorted(kdir.rglob("*.yaml")):
        rel = path.relative_to(kdir)
        if not rel.parts or path.name == "_index.yaml":
            continue
        if include_archive:
            skip = "_index" in rel.parts
        else:
            skip = rel.parts[0] in SKIP_TOP_DIRS
        if skip:
            continue
        yield path, rel


def iter_case_docs(root: Path, skip_bad: bool = False,
                   include_archive: bool = False) -> Iterator[Tuple[Path, Path, dict]]:
    """→ (路径, 相对路径, 解析后的文档)。

    ``skip_bad=True`` 时跳过 YAML 语法坏掉的文件（与 tag_hygiene 原行为一致）；
    默认让错误抛出，调用方按自己的错误方式处理。
    """
    for path, rel in iter_case_files(root, include_archive=include_archive):
        try:
            doc = load_file(path) or {}
        except yaml.YAMLError:
            if skip_bad:
                continue
            raise
        yield path, rel, doc


def namespace_of(rel: Path) -> str:
    """相对 knowledge/ 的路径 → 命名空间。

    规则（与 build_index 的原实现逐字一致）：
    - ``<负载类型>/<框架>/<类别>/<case>.yaml`` → ``<负载类型>/<框架>``；
    - ``<负载类型>/<框架>/platforms/...`` 不折，整段留作 ns（平台分支不是类别层）；
    - ``common/<类别>/<case>.yaml`` → ``common``；
    - 其余按去掉文件名的目录串。
    """
    parts = Path(rel).parts
    if len(parts) >= 3 and parts[0] in WORKLOAD_DIRS and parts[2] != "platforms":
        return "/".join(parts[:2])
    if len(parts) >= 2 and parts[0] == "common":
        return "common"
    return "/".join(parts[:-1])


def framework_of(rel: Path) -> str:
    """相对 knowledge/ 的路径 → 目录叶子名（tag_hygiene 自动删除用的那个名字）。

    与 :func:`namespace_of` 是两个问题：namespace 是检索面（``training/verl``），
    叶子名是 tag 去重面（``verl`` / ``common``）。旧 tag_hygiene 一直用后者，
    这里保留它，避免"统一命名空间"顺手改掉 tag 归一行为。
    """
    parts = Path(rel).parts
    if len(parts) >= 3 and parts[0] in WORKLOAD_DIRS:
        return parts[1]
    if len(parts) >= 2 and parts[0] == "common":
        return "common"
    return parts[0] if parts else ""


def category_dir_of(rel: Path, categories) -> str:
    """相对 knowledge/ 的路径里表达性质的那一层；没有则返回空串。

    ``common/<性质>/`` 与 ``<负载类型>/<框架>/<性质>/`` 两种；``platforms`` 支不判。
    """
    parts = Path(rel).parts
    if len(parts) >= 3 and parts[0] == "common" and parts[1] in categories:
        return parts[1]
    if len(parts) >= 4 and parts[0] in WORKLOAD_DIRS and parts[2] in categories:
        return parts[2]
    return ""


def workload_and_nature(root: Path, path: Path) -> Tuple[str, str]:
    """route_check 的视角：case 属于哪种负载类型、哪一性质。

    ``common/`` 下的共性 case 框架无关，两项都返回空串（本条不判）。
    """
    try:
        rel = Path(path).resolve().relative_to((Path(root) / KNOWLEDGE_DIR).resolve())
    except ValueError:
        return "", ""
    parts = rel.parts
    if len(parts) >= 3 and parts[0] in WORKLOAD_DIRS:
        return parts[0], parts[2]
    return "", ""
