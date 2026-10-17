#!/usr/bin/env python3
"""migrate_confidence_baseline.py —— 把案例 `confidence` 块里的历史累计值搬成 `kind: baseline` 记录行，
并把该块从案例文件里删掉（迁移的**一次性**动作，不是每次 groom 都跑）。

为什么要搬成一种单独的行：`confidence.hits` / `misdiagnoses` / `self_resolved` 是**生命周期累计值**，
而记录是「一次运行一行」。两者量纲不同，直接当成一次运行的增量写进去，会把历史累计算进本期增量，
排行与「长期零选中」的判断都会被这份人造基线污染。所以搬运行：

  - `run` 写 `baseline-<日期>`（日期取搬运当天，因此归周与其它行同规则）；
  - 计数名与其它行相同（`resolved` / `misdiagnosed` / `self_resolved`），另带 `last_hit`
    （原先的日期写法归一成 ISO 周）与来源说明；
  - 聚合把它算进 `totals`，但**不计入 `by_week`、本期增量，也不算作「有活动」**。

`last_hit` 是例外项：平时不单独存（由记录里最近一次 resolved / misdiagnosed 运行的周推出），
但搬运行自带一个——历史累计值没有对应的运行周，推不出来。

**删掉 `confidence` 块**是这次迁移的另一半：计数与分数都不再住在案例文件里（计数进记录、
分数由记录与冷启动先验算出来、只落在索引生成物里）。分数（`confidence.score`）直接丢弃——
它本来就是「由 agent 判断重算」的派生值，目标态由 `scripts/score_entries.py` 从记录与
`verification` × `investigation_quality` 的冷启动先验算出。

用法：
  python3 scripts/migrate_confidence_baseline.py            # dry-run：列出将写的行与将删的块
  python3 scripts/migrate_confidence_baseline.py --apply    # 写记录行 + 删 confidence 块
  python3 scripts/migrate_confidence_baseline.py --date 2026-10-18

退出码：0 = 成功（含「没有要搬的」）；2 = 参数或环境不可用。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import entry_activity as ea  # noqa: E402
from _stdio import pin_utf8_stdio, write_text_lf  # noqa: E402

CONF_RE = None


def find_conf_block(lines):
    """定位 **case 级** `confidence:` 块 → (start, end, inline)；找不到返回 (None, None, False)。

    三条判据（每条都对应一种会误删邻字段的输入）：
      ① 只认 case 级字段的缩进——案例里可能有嵌套的 `notes: {confidence: 0.9}` 之类，
         不按缩进认就会删掉嵌套那一行、留下真正的块；
      ② 块 = 键那一行 + 其后所有「空行、注释、或缩进更深」的行——`confidence:` 与它的子键
         之间夹一行同缩进的注释是常见写法，按「缩进更深才算块内」会只删键、留下孤儿子键
         （结果 YAML 解析失败）；
      ③ 夹在中间的空白/注释**只有在后面还有更深缩进的行时**才并入块，否则它属于下一个字段。

    inline 表示写成 `confidence: {...}` 的单行形式（那种只需删这一行）。
    """
    item_indent = None
    for ln in lines:
        if ln.lstrip().startswith("- "):
            item_indent = len(ln) - len(ln.lstrip())
            break
    field_indent = (item_indent or 0) + 2
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("#") or not s.startswith("confidence:"):
            continue
        indent = len(ln) - len(ln.lstrip())
        if indent != field_indent:          # ① 嵌套的 confidence 不认
            continue
        tail = s[len("confidence:"):].strip()
        if tail and not tail.startswith("#"):
            return i, i + 1, True
        j = i + 1
        while j < len(lines):
            t = lines[j]
            st = t.strip()
            if not st or st.startswith("#"):      # ② 注释/空行先看后面
                k = j
                while k < len(lines) and (not lines[k].strip() or lines[k].strip().startswith("#")):
                    k += 1
                if k < len(lines) and (len(lines[k]) - len(lines[k].lstrip())) > indent:
                    j = k
                    continue
                break
            if (len(t) - len(t.lstrip())) > indent:
                j += 1
                continue
            break
        return i, j, False
    return None, None, False


def scan(root: Path):
    """全库案例 → 待搬运清单 [(路径, 文件文本, case 数据, conf 块)]。"""
    out = []
    kdir = Path(root) / "knowledge"
    if not kdir.is_dir():
        return out
    for f in sorted(kdir.rglob("*.yaml")):
        if f.name.startswith("_"):
            continue
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            print(f"[skip] {f}: 解析失败（{e}）")
            continue
        conf = None
        for c in (doc.get("cases") or []):
            if isinstance(c, dict) and c.get("confidence") is not None:
                conf = c
                break
        if conf is None:
            continue
        text = f.read_text(encoding="utf-8")
        lines = text.split("\n")
        start, end, inline = find_conf_block(lines)
        out.append({"path": f, "text": text, "lines": lines, "start": start, "end": end,
                    "inline": inline, "case": conf, "conf": conf.get("confidence") or {}})
    return out


def baseline_row(item: dict, run: str, dep: str):
    """案例的 confidence → 一行搬运行；没有任何计数时返回 None（没什么可搬）。"""
    conf = item["conf"]
    sr = conf.get("self_resolved") or {}
    try:
        self_n = int(sr.get("count", 0) or 0)
    except (TypeError, ValueError):
        self_n = 0
    resolved = int(conf.get("hits", 0) or 0)
    mis = int(conf.get("misdiagnoses", 0) or 0)
    last_hit = ea.week_of_value(conf.get("last_hit"))
    if not (resolved or mis or self_n or last_hit):
        return None
    row = {"run": run, "deployment": dep, "kind": "baseline", "id": item["case"].get("id"),
           "resolved": resolved, "misdiagnosed": mis, "self_resolved": self_n}
    if last_hit:
        row["last_hit"] = last_hit
    row["note"] = f"搬自 confidence 块，{run[len('baseline-'):]}"
    return row


def strip_block(item: dict):
    """删掉 confidence 块 → 新的文件文本。块找不到（已删过）时原样返回。"""
    lines, start, end = item["lines"], item["start"], item["end"]
    if start is None:
        return item["text"]
    new = lines[:start] + lines[end:]
    return "\n".join(new)


def main() -> int:
    ap = argparse.ArgumentParser(description="把案例 confidence 块搬成 baseline 记录行并删除该块")
    ap.add_argument("--apply", action="store_true", help="真的写（默认 dry-run）")
    ap.add_argument("--root", default=None, help="检出根（默认：脚本上两级）")
    ap.add_argument("--date", default=None, help="搬运日期（默认今天；写进 run 与 note）")
    ap.add_argument("--deployment", default=None, help="部署名（默认取环境变量或主检出目录名）")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    day = args.date or date.today().isoformat()
    run = f"baseline-{day}"
    dep = args.deployment or ea.deployment(root)
    week = ea.week_of_run(run)
    if week is None:
        print(f"搬运日期 {day!r} 归不了周——拒绝执行", file=sys.stderr)
        return 2

    items = scan(root)
    if not items:
        print("全库没有带 confidence 块的案例（迁移已完成或本库从未写过该块）。")
        return 0

    rows, comments, stripped, no_row = [], [], [], []
    existing = {str(r.get("id")) for r in ea.read_source(root)[0] if r.get("kind") == "baseline"}
    for it in items:
        row = baseline_row(it, run, dep)
        if it["start"] is None:
            print(f"[skip] {it['path'].relative_to(root)}: 有 confidence 数据但找不到块边界——"
                  f"不删（人工确认后再处理）")
            continue
        if row is None:
            no_row.append(it)
        elif row["id"] in existing:
            print(f"[skip] {it['path'].relative_to(root)}: {row['id']} 已有搬运行——不重复搬")
        else:
            rows.append(row)
        for ln in it["lines"]:
            if ln.strip().startswith("#") and "confidence" in ln:
                comments.append(f"{it['path'].relative_to(root)}: {ln.strip()[:100]}")
        stripped.append(it)

    print(f"待搬运案例 {len(items)} 条：写 {len(rows)} 行搬运行、删 {len(stripped)} 个 confidence 块"
          f"（其中 {len(no_row)} 条计数全为 0，只删块不写行）。")
    for r in rows:
        print("  " + ea.format_row(r))
    if comments:
        print(f"\n以下注释提到 confidence，删除该块后指向已不存在的字段（请在本轮 groom 里改）：")
        for c in comments:
            print(f"  - {c}")
    if not args.apply:
        print("\n--dry-run（默认）：未写任何文件。确认后加 --apply。")
        return 0

    f = ea.append_rows(root, week, rows) if rows else None
    broken = []
    for it in stripped:
        new_text = strip_block(it)
        # 写完不回读是这类文本手术的典型失效形态：删错了照样落盘，下一次读才炸。
        try:
            doc = yaml.safe_load(new_text) or {}
        except yaml.YAMLError as e:
            broken.append(f"{it['path'].relative_to(root)}: 删块后解析失败（{e}）——未写入")
            continue
        cases = doc.get("cases") or []
        if cases and isinstance(cases[0], dict) and cases[0].get("confidence") is not None:
            broken.append(f"{it['path'].relative_to(root)}: 删块后仍能看到 confidence——未写入")
            continue
        write_text_lf(it["path"], new_text, encoding="utf-8")
    if f:
        print(f"\n已写 {len(rows)} 行搬运行 → {f}")
    print(f"已删 {len(stripped) - len(broken)} 个 confidence 块。")
    if broken:
        print(f"\n以下 {len(broken)} 个文件未改（删块后自检不通过，交人处理）：")
        for b in broken:
            print(f"  - {b}")
    print("接着跑：python3 scripts/build_entry_activity.py && python3 scripts/build_index.py")
    return 0


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
