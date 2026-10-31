#!/usr/bin/env python3
# ref_gap_index.py —— 按 case 的 title 与 symptoms 里的可检索键，报出先验知识的缺口与回链缺口
#
# 为什么需要它：case 沉淀走的是「有人想起 → 手动点名 → 一次性产出」，没有任何机械清点。
#   周批（knowledge-groom）里唯一的相关信号是按 tag 聚类（scripts/tag_hygiene.py），它给的是
#   「同 tag ≥N 条」——一次给出 30 多个机制族组，排不出先做哪个；而且它把「被已退休词条引用过」
#   也算作已收录，那批 case 就再也不会被建议一次。
#
# 本脚本只做一件事：把缺口按可以 grep 的键聚起来，并给出动作。
#   键族取自诊断的检索入口（错误码 / 十六进制码 / 环境变量 / 算子名 / 异常类名），不取 tag——
#   tag 维度归 scripts/tag_hygiene.py，两个脚本各管一个维度，不互相复算。
#
# 键只从 title 与 symptoms 抽。diagnosis / quickly_check 里出现的码常是判别句（"报 507014 还是
# 507057？"）或排除项，把它算成这条 case 的实例会让建议指向错的词条。
#
# 三种动作（判据全部来自已有事实，不做推断）：
#   提炼 extract —— 键找不到对应词条，组内 case 也没有被任何词条（active 或非 active）反向引用。
#   回链 relink  —— 有对应词条，组内 case 的 ref_knowledge 没连上去。对应词条来自两处：键命中
#                   （错误码族表、缺行索引指向的词条、或词条正文提到该键），或组内 case 被 active
#                   词条反向引用过（那条词条就是该补的目标）。动作是补 ref_knowledge，不新建词条。
#   复审 recheck —— 键找不到对应词条，但组内 case 被非 active 词条（draft / pending-review /
#                   deprecated）通过 sources[].cases 反向引用过。动作是先核替代词条有没有覆盖，
#                   不覆盖再提炼。
#
# 「已连」认正向边（case 的 ref_knowledge），不认反向边（词条的 sources[].cases）：诊断按
# ref_knowledge 加载词条，反向边不把词条送进上下文。两条边不一致的情况本脚本分开报：
# 反向边只用来判复审与补目标，正向边用来判可处理。
#
# 没有可检索键的 case 不会被聚成组。输出保证每个没有正向关联的 case 至少落在表或清单的一处：
# 进组的按组给（id 用 --json 取），组规模不足的逐条点名，无键的按与被引用关系分三段点名
# （被 active 引用 / 只被非 active 引用 / 没被引用）。不这样做，它们会同时被组表阈值与
# tag_hygiene 的「已收录剔除」挡掉，两个维度都看不见。
#
# 用法：
#   python3 scripts/ref_gap_index.py                 # 默认只看可处理 ≥3 条的组，列前 10 组
#   python3 scripts/ref_gap_index.py --min 2 --top 20
#   python3 scripts/ref_gap_index.py --json          # 给 groom 摘要或面板读
#
# 退出码：0 = 正常（含"没有可报的组"）；2 = 仓库结构不对，或参数不合法。
#
# 依赖：PyYAML。

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("需要 PyYAML：pip install pyyaml")

from _stdio import pin_utf8_stdio

# 键族。顺序即强弱：错误码与十六进制码是官方码，环境变量与算子名是可 grep 的标识符，
# 异常类名是弱键（同名异常不一定是同一根因），排在最后。
CODE_SIX = re.compile(r"(?<![0-9A-Za-z])([1-7]\d{5})(?![0-9A-Za-z])")
CODE_ALPHA = re.compile(r"(?<![0-9A-Za-z])((?:EE|EH|EZ)\d{4})(?![0-9A-Za-z])")
CODE_HEX = re.compile(r"(?<![0-9A-Za-z])(0x[0-9A-Fa-f]{4,})(?![0-9A-Za-z])")
ENV_NAME = re.compile(
    r"(?<![0-9A-Za-z_])((?:HCCL|ASCEND|VLLM|TORCH|NPU|PYTORCH|MS|MINDSPEED|VERL|SGLANG|AICPU)_[A-Z0-9_]{2,})(?![0-9A-Za-z_])"
)
ACLNN_OP = re.compile(r"(?<![0-9A-Za-z_])(aclnn[A-Za-z0-9]+)(?![0-9A-Za-z_])")
TORCH_OP = re.compile(r"(?<![0-9A-Za-z_])(torch\.ops\.[A-Za-z0-9_]*[A-Za-z0-9_])(?![0-9A-Za-z_])")
EXC_NAME = re.compile(r"(?<![0-9A-Za-z_])([A-Z][A-Za-z0-9]*(?:Error|Exception))(?![0-9A-Za-z_])")

# 内置异常名不构成"同一根因"的信号，进索引只会制造噪声。含常见子类（FileNotFoundError 等）：
# 它们是标准库语义，不是昇腾侧的事实。
BUILTIN_EXCEPTIONS = frozenset(
    {
        "ArithmeticError", "AssertionError", "AttributeError", "BaseException",
        "BlockingIOError", "BrokenPipeError", "BufferError", "CancelledError",
        "ChildProcessError", "ConnectionAbortedError", "ConnectionError",
        "ConnectionRefusedError", "ConnectionResetError", "EOFError",
        "FileExistsError", "FileNotFoundError", "FloatingPointError",
        "GeneratorExit", "ImportError", "IndentationError", "IndexError",
        "InterruptedError", "IsADirectoryError", "KeyError", "KeyboardInterrupt",
        "LookupError", "MemoryError", "ModuleNotFoundError", "NameError",
        "NotADirectoryError", "NotImplementedError", "OSError", "OverflowError",
        "PermissionError", "ProcessLookupError", "RecursionError", "ReferenceError",
        "RuntimeError", "StopAsyncIteration", "StopIteration", "SyntaxError",
        "SystemExit", "TabError", "TimeoutError", "TypeError", "UnboundLocalError",
        "UnicodeDecodeError", "UnicodeEncodeError", "UnicodeError", "ValueError",
        "ZeroDivisionError",
    }
)

KIND_ORDER = {"code": 0, "hex": 0, "env": 1, "aclnn": 1, "torch-op": 1, "exc": 2}

ACTION_EXTRACT = "extract"
ACTION_RELINK = "relink"
ACTION_RECHECK = "recheck"

ACTION_ORDER = {ACTION_RELINK: 0, ACTION_EXTRACT: 1, ACTION_RECHECK: 2}

ACTION_LABEL = {
    ACTION_EXTRACT: "提炼",
    ACTION_RELINK: "回链",
    ACTION_RECHECK: "复审",
}

# 键只从这两个字段抽：症状里出现的码与标识符，才是这条 case 的实例。
KEY_FIELDS = ("title", "symptoms")


def _scalar_text(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [str(value)]
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_scalar_text(item))
        return out
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            if isinstance(key, str):
                out.append(key)
            out.extend(_scalar_text(item))
        return out
    return []


def case_text(case: dict) -> str:
    """case 里能当检索键的文本：只有 title 与 symptoms。"""
    parts = []
    for field in KEY_FIELDS:
        if field in case:
            parts.extend(_scalar_text(case[field]))
    return "\n".join(parts)


def keys_of(text: str) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for code in CODE_SIX.findall(text):
        keys.add(("code", code))
    for code in CODE_ALPHA.findall(text):
        keys.add(("code", code))
    for code in CODE_HEX.findall(text):
        keys.add(("hex", code))
    for name in ENV_NAME.findall(text):
        keys.add(("env", name))
    for name in ACLNN_OP.findall(text):
        keys.add(("aclnn", name))
    for name in TORCH_OP.findall(text):
        keys.add(("torch-op", name))
    for name in EXC_NAME.findall(text):
        if name not in BUILTIN_EXCEPTIONS:
            keys.add(("exc", name))
    return keys


def load_cases(root: Path) -> dict[str, dict]:
    cases: dict[str, dict] = {}
    for path in sorted((root / "knowledge").rglob("*.yaml")):
        rel = path.relative_to(root).as_posix()
        if "_index" in rel or "/_archive/" in "/" + rel:
            continue
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        for case in doc.get("cases") or []:
            if isinstance(case, dict) and case.get("id"):
                cases[str(case["id"])] = case
    return cases


def refs_of_case(case: dict) -> list[str]:
    """case 的 ref_knowledge 指向的词条 id（正向边，诊断阶段二.5 读它）。"""
    out = []
    for item in case.get("ref_knowledge") or []:
        if isinstance(item, dict) and item.get("ref"):
            out.append(str(item["ref"]))
        elif isinstance(item, str):
            out.append(item)
    return out


def case_ids_of_sources(sources) -> list[str]:
    out: list[str] = []
    for item in sources or []:
        if isinstance(item, dict):
            out.extend(str(x) for x in (item.get("cases") or []))
    return out


def case_ids_of_content(content) -> list[str]:
    """content 下任意层的 source_cases（表形态词条把证据挂在条目上）。"""
    out: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "source_cases" and isinstance(value, list):
                    out.extend(str(x) for x in value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(content)
    return out


def load_refs(root: Path) -> list[dict]:
    refs = []
    for path in sorted((root / "references").rglob("*.yaml")):
        rel = path.relative_to(root).as_posix()
        name = path.name
        if "_index" in rel or name.startswith("_"):
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            doc = yaml.safe_load(raw) or {}
        except Exception:
            continue
        if not isinstance(doc, dict) or not doc.get("id"):
            continue
        refs.append(
            {
                "id": str(doc["id"]),
                "status": str(doc.get("status") or ""),
                "path": rel,
                "raw": raw,
                "cases": case_ids_of_sources(doc.get("sources"))
                + case_ids_of_content(doc.get("content")),
            }
        )
    return refs


def code_tables(root: Path, active_path_to_id: dict[str, str]) -> dict[str, str]:
    """错误码 → 承载它的 active 词条 id。"""
    homes: dict[str, str] = {}
    errors_dir = root / "references" / "errors"
    for path in sorted(errors_dir.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        if str(doc.get("status") or "") != "active" or not doc.get("id"):
            continue
        for entry in (doc.get("content") or {}).get("errors") or []:
            if isinstance(entry, dict) and entry.get("code"):
                homes.setdefault(str(entry["code"]), str(doc["id"]))
    gap_file = errors_dir / "_code-gaps.yaml"
    if gap_file.exists():
        try:
            doc = yaml.safe_load(gap_file.read_text(encoding="utf-8")) or {}
        except Exception:
            doc = {}
        # 缺行索引自己不承载内容：它只记这个码能在哪个词条里看到（seen_in）。
        # seen_in 可能指向非 active 词条，那不是可用的对应词条，跳过。
        for entry in doc.get("code_gaps") or []:
            if not isinstance(entry, dict) or not entry.get("code"):
                continue
            for target in entry.get("seen_in") or []:
                if target in active_path_to_id:
                    homes.setdefault(str(entry["code"]), active_path_to_id[target])
                    break
    return homes


def token_in_text(token: str, text: str) -> bool:
    """键是否作为独立记号出现在词条正文里（507903 不命中 1507903，HCCL_DEBUG 不命中 HCCL_DEBUG_INFO）。"""
    return (
        re.search(r"(?<![0-9A-Za-z_])" + re.escape(token) + r"(?![0-9A-Za-z_])", text)
        is not None
    )


def build_index(root: Path) -> dict:
    cases = load_cases(root)
    refs = load_refs(root)
    active = [r for r in refs if r["status"] == "active"]
    inactive = [r for r in refs if r["status"] != "active"]
    active_ids = {r["id"] for r in active}
    active_path_to_id = {r["path"]: r["id"] for r in active}
    tables = code_tables(root, active_path_to_id)

    cited_active: dict[str, set[str]] = defaultdict(set)
    cited_inactive: dict[str, set[str]] = defaultdict(set)
    for ref in refs:
        bucket = cited_active if ref["status"] == "active" else cited_inactive
        for cid in ref["cases"]:
            bucket[cid].add(ref["id"])

    case_keys: dict[str, set[tuple[str, str]]] = {}
    for cid, case in cases.items():
        case_keys[cid] = keys_of(case_text(case))

    def forward_linked(cid: str, home: list[str]) -> bool:
        """case 的 ref_knowledge 里有没有指向 active 词条的关联（组指定 home 时只看该词条）。"""
        linked = {r for r in refs_of_case(cases[cid]) if r in active_ids}
        if not linked:
            return False
        if home:
            return bool(linked & set(home))
        return True

    groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    for cid, keys in case_keys.items():
        for key in keys:
            groups[key].add(cid)

    rows = []
    for (kind, token), members in groups.items():
        if kind == "code" and token in tables:
            key_home = [tables[token]]
        else:
            key_home = [r["id"] for r in active if token_in_text(token, r["raw"])]

        # 每个 case 单独算目标：键命中优先；键没有对应词条时，才用它自己被哪条 active 词条
        # 反向引用过。按整组套同一个目标，会把「没被该词条引用过」的同伴也挂上去。
        by_action: dict[str, dict[str, list[str]]] = {
            ACTION_RELINK: {},
            ACTION_EXTRACT: {},
            ACTION_RECHECK: {},
        }
        linked = []
        for cid in members:
            if key_home:
                target = key_home
            else:
                target = sorted(r for r in cited_active.get(cid, set()) if r in active_ids)
            if forward_linked(cid, target):
                linked.append(cid)
                continue
            if target:
                action = ACTION_RELINK
            elif cited_inactive.get(cid):
                action = ACTION_RECHECK
            else:
                action = ACTION_EXTRACT
            by_action[action][cid] = target

        for action in (ACTION_RELINK, ACTION_EXTRACT, ACTION_RECHECK):
            sub = by_action[action]
            if not sub:
                continue
            targets = sorted({t for ts in sub.values() for t in ts})
            rows.append(
                {
                    "key": f"{kind}:{token}",
                    "kind": kind,
                    "token": token,
                    "action": action,
                    "actionable": len(sub),
                    "size": len(members),
                    "linked": len(linked),
                    "home": targets,
                    "home_kind": "key" if key_home else ("cited" if targets else "none"),
                    "cited_by_inactive": sorted(
                        {
                            r
                            for cid in sub
                            for r in (cited_inactive.get(cid, set()) if action == ACTION_RECHECK else set())
                        }
                    ),
                    "cases": sorted(sub),
                }
            )

    no_link = sorted(cid for cid in cases if not forward_linked(cid, []))
    no_key = [cid for cid in no_link if not case_keys.get(cid)]
    keyed = [cid for cid in no_link if case_keys.get(cid)]
    no_key_active = [cid for cid in no_key if cited_active.get(cid)]
    no_key_inactive = [
        cid for cid in no_key if not cited_active.get(cid) and cited_inactive.get(cid)
    ]
    no_key_uncited = [
        cid for cid in no_key if not cited_active.get(cid) and not cited_inactive.get(cid)
    ]

    return {
        "cases": len(cases),
        "refs_active": len(active),
        "refs_inactive": len(inactive),
        "cases_without_active_link": len(no_link),
        "cases_only_inactive_cited": sum(
            1 for cid in no_link if not cited_active.get(cid) and cited_inactive.get(cid)
        ),
        "cases_without_any_key": len(no_key),
        "no_key_cases_cited_by_active": no_key_active,
        "no_key_cases_inactive_only": no_key_inactive,
        "no_key_cases_uncited": len(no_key_uncited),
        "no_key_uncited_ids": no_key_uncited,
        "unlinked_keyed_cases": keyed,
        "groups": rows,
    }


def render(index: dict, min_n: int, top: int) -> list[str]:
    rows = [r for r in index["groups"] if r["actionable"] >= min_n]
    rows.sort(key=lambda r: (KIND_ORDER.get(r["kind"], 9), -r["actionable"], r["key"], ACTION_ORDER[r["action"]]))

    lines = [
        f"case {index['cases']} 条，active 词条 {index['refs_active']} 条，"
        f"非 active 词条 {index['refs_inactive']} 条",
        f"没有正向关联的 case（ref_knowledge 未指向 active 词条）："
        f"{index['cases_without_active_link']} 条；其中只被非 active 词条反向引用过的："
        f"{index['cases_only_inactive_cited']} 条",
        f"按可检索键聚合，可处理 ≥{min_n} 条的行：{len(rows)} 行",
    ]
    shown = rows[:top]
    if shown:
        header = ("动作", "键", "可处理/组内", "对应词条")
        body = []
        for row in shown:
            if row.get("home_kind") == "cited" and row["home"]:
                home = "按引用它的词条"
            elif row["home"]:
                home = row["home"][0]
                if len(row["home"]) > 1:
                    home += f"（另 {len(row['home']) - 1} 条）"
            elif row["action"] == ACTION_RECHECK:
                home = "无（引用它的是非 active 词条）"
            else:
                home = "无"
            body.append(
                (
                    ACTION_LABEL[row["action"]],
                    row["key"],
                    f"{row['actionable']}/{row['size']}",
                    home,
                )
            )
        widths = [max(len(header[i]), *(len(r[i]) for r in body)) for i in range(4)]
        lines.append("")
        lines.append("  ".join(header[i].ljust(widths[i]) for i in range(3)) + "  " + header[3])
        for row in body:
            lines.append("  ".join(row[i].ljust(widths[i]) for i in range(3)) + "  " + row[3])
        if len(rows) > top:
            lines.append("")
            lines.append(f"另有 {len(rows) - top} 行未列出，用 --top 调整。")
    else:
        lines.append("")
        lines.append("没有可报的组：同键的 case 要么已连上 active 词条，要么不足阈值。")

    # 表只列达到阈值、且落在 --top 之内的行。没进表的未连 case 与无键 case 在这里点名，保证
    # 每个没有正向关联的 case 至少出现在一处——否则它们会同时被阈值与 tag_hygiene 的
    # 「已收录剔除」挡掉。
    listed = {cid for row in shown for cid in row["cases"]}
    missed = [cid for cid in index["unlinked_keyed_cases"] if cid not in listed]
    if missed:
        lines.append("")
        lines.append(
            f"未进表的未连 case：{len(missed)} 条"
            f"（可处理不足 {min_n} 条，或所在行被 --top 截断；按 id 逐条复核）"
        )
        lines.append("  " + "、".join(missed))

    by_active = index["no_key_cases_cited_by_active"]
    if by_active:
        lines.append("")
        lines.append(
            f"没有可检索键、但被 active 词条反向引用过的 case：{len(by_active)} 条"
            f"（按引用它的词条补 ref_knowledge）"
        )
        lines.append("  " + "、".join(by_active))

    inactive_only = index["no_key_cases_inactive_only"]
    if inactive_only:
        lines.append("")
        lines.append(
            f"没有可检索键、且只被非 active 词条反向引用过的 case：{len(inactive_only)} 条"
            f"（进不了组表，tag 维度把它们算作已收录；按 id 逐条复核）"
        )
        lines.append("  " + "、".join(inactive_only))

    uncited = index["no_key_uncited_ids"]
    if uncited:
        lines.append("")
        lines.append(
            f"没有可检索键、也没有任何词条引用过的 case：{len(uncited)} 条"
            f"（覆盖缺口；tag 维度可能覆盖其中一部分，逐条看 id）"
        )
        lines.append("  " + "、".join(uncited))
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="按 case 的 title 与 symptoms 里的可检索键，报出先验知识的缺口与回链缺口"
    )
    ap.add_argument("--root", default=".", help="仓库根目录（默认当前目录）")
    ap.add_argument("--min", type=int, default=3, help="只报可处理 case ≥N 条的行（默认 3）")
    ap.add_argument("--top", type=int, default=10, help="最多列 N 行（默认 10，须 ≥1）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not (root / "knowledge").is_dir() or not (root / "references").is_dir():
        print(f"{root} 下没有 knowledge/ 或 references/，不像仓库根目录", file=sys.stderr)
        return 2
    if args.top < 1:
        print(f"--top 须 ≥1（收到 {args.top}）", file=sys.stderr)
        return 2

    index = build_index(root)
    rows = [r for r in index["groups"] if r["actionable"] >= args.min]
    rows.sort(key=lambda r: (KIND_ORDER.get(r["kind"], 9), -r["actionable"], r["key"], ACTION_ORDER[r["action"]]))

    if args.json:
        payload = {k: v for k, v in index.items() if k != "groups"}
        payload["groups"] = rows[: args.top]
        payload["groups_total"] = len(rows)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    for line in render(index, args.min, args.top):
        print(line)
    return 0


if __name__ == "__main__":
    pin_utf8_stdio()
    raise SystemExit(main())
