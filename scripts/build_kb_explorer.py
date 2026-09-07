#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_kb_explorer.py —— 生成「昇腾知识浏览器」自包含 HTML demo（人面消费层 v1）。

数据源：references/**/*.yaml（先验知识层，public 方法论）+ triage-tree.yaml（入口路由）。
产出：docs/kb-explorer/index.html —— 单文件、离线可开（file:// 直接打开），
      references/ 变更后重跑本脚本即可刷新（demo 阶段不接 CI）。

刻意排除 knowledge/（case 含客户数据，private）——v1 只做 references 层；
case↔reference 反链视图等 ref_knowledge 数据累积后再加（见讨论记录）。

用法：
    python3 scripts/build_kb_explorer.py [输出路径]
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "docs" / "kb-explorer" / "index.html"
TEMPLATE = REPO / "scripts" / "kb-explorer" / "template.html"

# type 展示顺序 / 目录 / 中文标签 / kind / 一句话说明（首页与侧栏文案）
TYPE_META: dict[str, dict] = {
    "methodology":       {"dir": "methodologies",      "label": "方法论 · 定位流程", "kind": "flow",  "hint": "一类问题的多步定位流程：现象分流 → 采集 → 逐条命令验证"},
    "error-code":        {"dir": "errors",             "label": "错误码表",           "kind": "table", "hint": "错误码 / 异常代码含义，按组件分族（ge / hccl / rts / cann-runtime …）"},
    "fault-pattern":     {"dir": "fault-patterns",     "label": "故障模式",           "kind": "table", "hint": "现象 → 根因 → 处理 对照表（按主题域分族）"},
    "env-var-table":     {"dir": "env-vars",           "label": "环境变量",           "kind": "table", "hint": "HCCL / 日志 / 图编译等模块的环境变量参考"},
    "compat-matrix":     {"dir": "compat-matrices",    "label": "版本兼容矩阵",       "kind": "table", "hint": "CANN↔HDK / torch-npu↔CANN / 框架适配 三层配套矩阵"},
    "tool":              {"dir": "tools",              "label": "工具用法",           "kind": "fact",  "hint": "工具 / 命令的使用方法与输出解读"},
    "platform-fact":     {"dir": "platform-facts",     "label": "平台事实",           "kind": "fact",  "hint": "平台硬事实：芯片规格 / 存储层级 / 互联 / 精度格式"},
    "software-fact":     {"dir": "software-facts",     "label": "软件事实",           "kind": "fact",  "hint": "软件栈硬事实：日志分类与路径、机制、进程行为"},
    "command-side-effect": {"dir": "command-side-effects", "label": "命令副作用",     "kind": "fact",  "hint": "命令 / 环境变量的副作用与回滚方式"},
}
TYPE_ORDER = list(TYPE_META)

SRC_TYPE_LABEL = {
    "official-doc": "官方文档",
    "case-derived": "案例提炼",
    "engineer-input": "工程师输入",
}


def load_all() -> dict:
    entries: list[dict] = []
    seen = set()
    for f in sorted((REPO / "references").rglob("*.yaml")):
        if f.name == "_types.yaml":
            continue
        with f.open(encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        if not isinstance(doc, dict) or not doc.get("id"):
            print(f"skip (no id): {f}", file=sys.stderr)
            continue
        typ = doc.get("type")
        if typ not in TYPE_META:
            print(f"unregistered type {typ!r} in {f}", file=sys.stderr)
            typ = "software-fact"  # 兜底展示，不应发生
        if doc["id"] in seen:
            print(f"dup id: {doc['id']} ({f})", file=sys.stderr)
        seen.add(doc["id"])
        entries.append(
            {
                "id": doc["id"],
                "type": typ,
                "dir": TYPE_META[typ]["dir"],
                "file": str(f.relative_to(REPO)),
                "title": doc.get("title", doc["id"]),
                "summary": doc.get("summary", ""),
                "doc": doc,
            }
        )
    entries.sort(key=lambda e: (TYPE_ORDER.index(e["type"]), e["title"]))

    triage = yaml.safe_load((REPO / "triage-tree.yaml").read_text(encoding="utf-8"))
    return {"entries": entries, "triage": triage}


def build() -> dict:
    data = load_all()
    counts = {t: 0 for t in TYPE_ORDER}
    for e in data["entries"]:
        counts[e["type"]] += 1
    types = [
        {**TYPE_META[t], "type": t, "count": counts[t], "src_label": SRC_TYPE_LABEL}
        for t in TYPE_ORDER
    ]
    payload = {
        "generated_at": datetime.date.today().isoformat(),
        "type_order": TYPE_ORDER,
        "types": types,
        "entries": data["entries"],
        "triage": data["triage"],
        "note": "数据层仅含 references/（先验知识，public）；knowledge/ case 内容为私有，未纳入本 demo。",
    }
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    payload = build()
    json_text = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        default=lambda o: o.isoformat()
        if isinstance(o, (datetime.date, datetime.datetime))
        else json.JSONEncoder().default(o),
    )
    json_text = json_text.replace("</", "<\\/")  # 防 </script 截断

    template = TEMPLATE.read_text(encoding="utf-8")
    marker = "__KB_JSON__"
    if marker not in template:
        print(f"template marker {marker!r} missing in {TEMPLATE}", file=sys.stderr)
        return 1
    html = template.replace(marker, json_text, 1)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"ok: {out}  ({len(payload['entries'])} entries, {len(html)/1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
