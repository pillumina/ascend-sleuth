#!/usr/bin/env python3
"""verify_entry_activity.py —— 条目使用记录的门（源结构 + 生成物一致 + 引用完整性）。

为什么单独一个校验脚本：`build_entry_activity.py --check` 只保证**生成物与源一致**——源自己写错
（重复的三元组、run 落在别的周、id 在知识库里查不到）它照原样搬进生成物，一致得很。这一层是
「源本身的判据」，与索引那边 `build_index.py`（能解析）对 `verify_case_draft.py`（字段合法）同构。

四条判据（都可机械判、后果确定、且都是这份文件族特有的失效形态）：

  ① 文件名与 run 归周     `run` 是写入机器的本地时间戳，文件名是它所在的周。两者不一致时
                          「按文件名归周」（文档 4 节的边界表），但必须报出来——不报的话，
                          跨周界那一次运行写进哪一周就成了无声的事实，趋势线会静默错位。
  ② (run, kind, id) 唯一  这是行的唯一键。重复 = 同一件事被写了两次，聚合会把它加成两倍。
                          同一行被 union 重复保留（字节相同）不算重复，先按字节去重。
  ③ id 存在               案例 / 先验 id 必须能在知识库里查到（含 `_archive/`）。查不到的行
                          不计入排行、列入清理清单——不报的话，退休或改 id 之后旧记录会永远
                          挂在生成物里，面板上显示成一条不存在的条目。
  ④ 生成物与部署名         生成物文件名必须等于文件内 `covered.deployment`。不一致会让面板按
                          本部署取数时读到另一份，而两份的形状完全一样，读错不会报错。

用法：
  python3 scripts/verify_entry_activity.py            # 人读判定
  python3 scripts/verify_entry_activity.py --json     # 机器读
  python3 scripts/verify_entry_activity.py --root <检出>

退出码：0 = 全部通过；1 = 有判据不通过；2 = 数据不完整（源目录都读不到）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import entry_activity as ea  # noqa: E402
from _stdio import pin_utf8_stdio  # noqa: E402


def known_ids(root: Path):
    """知识库里所有条目 id（含 `_archive/` 与 retired 的），按 kind 分开。

    含归档：一条已经退休的 case 的**历史记录行仍然合法**——记录是 append-only 的，
    退休不回写历史（文档 4 节：「能报出来的就报出来，不改写历史数据」）。
    """
    cases, refs = set(), set()
    kdir = Path(root) / "knowledge"
    if kdir.is_dir():
        for f in kdir.rglob("*.yaml"):
            if f.name.startswith("_"):
                continue
            try:
                d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            for c in (d.get("cases") or []):
                if c.get("id"):
                    cases.add(str(c["id"]))
    rdir = Path(root) / "references"
    if rdir.is_dir():
        for f in rdir.rglob("*.yaml"):
            if f.name.startswith("_"):
                continue
            try:
                d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if isinstance(d, dict) and d.get("id"):
                refs.add(str(d["id"]))
    return cases, refs


def verify(root: Path):
    problems, notes = [], []
    rows, read_problems = ea.read_source(root)
    problems += read_problems

    seen, dupes, orphans, week_mismatch = {}, [], [], []
    for r in rows:
        where = f"{r['_file']}:{r['_line']}"
        for b in ea.check_row_shape(r):
            problems.append(f"{where}: {b}")
        key = (str(r.get("run")), r.get("kind"), str(r.get("id")))
        sig = ea.format_row({k: v for k, v in r.items() if not k.startswith("_")})
        if key in seen:
            if seen[key] != sig:
                dupes.append(f"{where}: (run, kind, id) 重复且内容不同：{key}")
            else:
                notes.append(f"{where}: 与上一行逐字节相同（union 重复保留），只算一次")
        else:
            seen[key] = sig
        w = ea.week_of_run(str(r.get("run") or ""))
        if w and w != r.get("_week"):
            week_mismatch.append(f"{where}: run {r['run']} 落在 {w}，写在 {r['_file']}（按文件名归周）")

    cases, refs = known_ids(root)
    for r in rows:
        rid, kind = str(r.get("id")), r.get("kind")
        if kind == "case" and rid not in cases:
            orphans.append(f"{r['_file']}:{r['_line']}: 案例 id {rid} 在知识库里查不到")
        elif kind == "ref" and rid not in refs:
            orphans.append(f"{r['_file']}:{r['_line']}: 先验 id {rid} 在知识库里查不到")

    gen_problems = []
    gdir = ea.generated_dir(root)
    deps_in_source = {str(r.get("deployment")) for r in rows if r.get("deployment")}
    if gdir.is_dir():
        for f in sorted(gdir.glob("*.yaml")):
            try:
                doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as e:
                gen_problems.append(f"{f.name}: 生成物解析失败（{e}）")
                continue
            dep = ((doc.get("covered") or {}).get("deployment"))
            if dep != f.stem:
                gen_problems.append(f"{f.name}: 文件名与 covered.deployment（{dep}）不一致")
            if f.stem not in deps_in_source:
                notes.append(f"{f.name}: 源里已无该部署的记录行（按只接收处理，删由 owner 定）")

    src_dir = ea.source_dir(root)
    if not src_dir.is_dir() and not (gdir.is_dir() and list(gdir.glob("*.yaml"))):
        print(f"数据不完整：{src_dir} 不存在，且没有生成物——无从校验", file=sys.stderr)
        return 2, {"problems": problems}

    for label, items in (("行结构 / 引用 / 归周", problems + week_mismatch + orphans + dupes),
                         ("生成物", gen_problems)):
        if items:
            print(f"✗ {label}：{len(items)} 处")
            for x in items:
                print(f"  - {x}")
    for n in notes:
        print(f"  · {n}")
    ok = not (problems or week_mismatch or orphans or dupes or gen_problems)
    return (0 if ok else 1), {
        "problems": problems, "week_mismatch": week_mismatch, "orphans": orphans,
        "duplicates": dupes, "generated": gen_problems, "notes": notes,
        "rows": len(rows), "deployments": sorted(deps_in_source),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="条目使用记录的门")
    ap.add_argument("--root", default=None, help="检出根（默认：脚本上两级）")
    ap.add_argument("--json", action="store_true", help="机器读输出")
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    code, report = verify(root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    elif code == 0:
        print(f"✓ 条目使用记录通过：{report['rows']} 行、{len(report['deployments'])} 个部署；"
              f"(run, kind, id) 唯一、id 都能在知识库里查到、生成物与部署名一致。")
    return code


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
