# -*- coding: utf-8 -*-
"""共享工具函数：数值转换与文件读取。

来源：原 9 个脚本中逐字重复的工具函数（to_f x5、read_json x6 默认值不一致、
read_csv_rows x4、iter_csv x2、us_to_ms/us_ms 同逻辑异名 x2）收敛于此。

行为约定：所有读取函数对缺失/损坏输入静默降级（返回 default），不抛异常——
对应流水线纪律「数据缺失不算失败」。
"""

import csv
import json
import os
import math


def to_f(v, default=0.0):
    """字符串/数值转 float，失败返回 default。"""
    try:
        number = float(str(v).strip())
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def read_json(path, default=None):
    """读取 JSON；文件缺失或解析失败返回 default。

    注意：原各脚本默认值不一致（多数为 None，compare_fallback 为 {}），
    接入时请显式传 default 以保持原行为。
    """
    if not os.path.isfile(path):
        return default
    try:
        with open(path, encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return default


def read_csv_rows(path):
    """读取 CSV 为 list[dict]；文件缺失返回 []。"""
    if not os.path.isfile(path):
        return []
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        return list(csv.DictReader(f))


def iter_csv(path):
    """流式迭代 CSV 行（大文件友好）；文件缺失时不产出任何行。"""
    if not os.path.isfile(path):
        return
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        for row in csv.DictReader(f):
            yield row


def us_to_ms(v_us):
    """μs → ms，保留 3 位小数（报告层单位纪律）。"""
    return round(v_us / 1000.0, 3)


# 兼容旧命名（swimlane_analyzer 原名 us_ms）
us_ms = us_to_ms


def is_junk(name):
    """macOS 解压残留过滤（._* 与 __MACOSX）。"""
    return name.startswith('._') or name == '__MACOSX'
