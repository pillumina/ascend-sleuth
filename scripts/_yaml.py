#!/usr/bin/env python3
# _yaml.py —— YAML 解析的统一入口（快路径：libyaml 绑定的 CSafeLoader）
#
# 为什么需要（面板「闭环判决」首屏实测）：PyYAML 的 SafeLoader 是纯 Python 实现，
# 解析本仓库 351 个词条/case 文件实测 2.2 秒，占 references 校验整脚本 3.5 秒的绝大部分。
# 而面板指标 tab 的判决卡会跑这条链路（metrics_health.py → verify_references.py 子进程），
# 于是首屏要等 3.8 秒才出内容——同一次插件运行里缓存命中后只要 3 毫秒。
# CSafeLoader 是同一套 resolver/constructor 的 libyaml 绑定（PyYAML 自带，不是新依赖），
# 同一批文件实测 0.24 秒，解析结果与报错语义同源，只换解析后端。
#
# 兜底：PyYAML 由源码安装、没编出 C 扩展时没有 CSafeLoader，退回 SafeLoader——
# 行为不变，只是慢。不做"没有快路径就报错"。
#
# 用法：脚本内已有的 load_yaml 漏斗改成调这里，不要在别处再写一份 safe_load：
#     from _yaml import load_file, load_text
# 需要显式比对两种后端的等价性时，改模块级 `Loader` 即可（各脚本在调用时读它）。

from pathlib import Path

import yaml

# libyaml 后端优先；缺席（源码安装未编出扩展）时用纯 Python 后端，行为等价。
Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def load_text(text):
    """解析 YAML 文本。不做 `or {}` 之类的值归一——各调用点的空文档语义不同，
    归一是调用方的判断（有的要记进 errors，有的要退回空 dict）。"""
    return yaml.load(text, Loader=Loader)


def load_file(path):
    """读文件并解析（UTF-8）。路径不存在、编码错、语法错都照常抛出，
    由调用方按各自的错误口径处理（记 errors / 返回占位 doc / 跳过）。"""
    return yaml.load(Path(path).read_text(encoding="utf-8"), Loader=Loader)
