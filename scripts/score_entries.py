#!/usr/bin/env python3
"""score_entries.py —— 条目排序分数：由**使用记录的计数**与**冷启动先验**算出来（知识整理第 4 步）。

它替换的是「由 agent 按时间衰减重算」那一步。替换的理由不是省事，是**可核对**：agent 每周看图
重算，同一份输入两次可以算出不同的分数，而分数是候选排序的输入——排序变了却说不出为什么。
这个脚本给出一条公式，任何人（或 CI）拿同一份输入都能复算出同一个数。

公式（Beta 后验，与 groom 里「verification × investigation_quality」那张冷启动先验表同源）：

    α = p0·K + resolved + ρ·self_resolved
    β = (1 − p0)·K + misdiagnosed
    score = α / (α + β)

  - `p0` 是冷启动先验：来源验证强度（`verification.source`）× 调查质量（`investigation_quality`），
    取值就是 groom 那张表。没有记录时 score 就等于它——「先验」这个说法正是这个意思。
  - `K = 4` 是先验的等效观测数（先验值折几条现场观测）。取 4：一条刚沉淀、只有一次现场确认的
    case 不该被一次反馈掀到 0.9 或砸到 0.1，而 4 条之后现场证据开始主导。
  - `ρ = 0.5` 是自证（来源会话自己回报 resolve）的权重。自证是弱证据：报告的人与做结论的人是
    同一个，且没有独立复核；但它也不是零信息，所以记半分而不是整分。
  - 时间衰减：每经过 `HALF_LIFE_WEEKS = 12` 周，一次运行的计数权重减半。12 周与 groom 的
    「近 12 周未解决」是同一个窗口——两个地方用同一个时间尺度，读的人不必换算。
    **衰减锚点取记录里最新一次运行所处的周（数据值），不取当天日期**：生成物不写日期、也不随
    时钟变，索引的 `--check` 是逐字节门——按当天衰减会让索引在没有任何知识变更时变红。
    搬运行（`kind: baseline`）没有运行周，不参与衰减，按原样进入后验（它是生命周期累计值）。

`score_override`（案例的可选字段，`{score, reason, by}`）优先于算分：罕见的人工干预走显式字段，
`reason` 必填（没有理由的覆盖在半年后无法判断该不该撤）。

**输入是生成物不是源**：记录读 `metrics/entry-activity/<部署>.yaml`（读端只读生成物，与面板同一条）。
索引是全仓共享的生成物、会在 CI 重建并与提交的那份逐字节比，所以这里读**仓里全部部署**的记录
生成物并按 id 求和——按本机部署取值会让同一份索引在不同检出算出不同分数，门恒红。
面板的排行仍然按部署分家（那是「这次部署发生了什么」的问题，不是排序问题）。

用法：
  python3 scripts/score_entries.py                 # 人读：分数分布 + 用了先验的条目
  python3 scripts/score_entries.py --json          # 机器读（build_index.py 直接用它的函数）
  python3 scripts/score_entries.py --entry VLLM-ASC-12430
  python3 scripts/score_entries.py --root <检出>

退出码：0 = 正常；1 = `--check-overrides` 发现不合法的覆盖字段；2 = 环境不可用。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import entry_activity as ea  # noqa: E402
from _stdio import pin_utf8_stdio  # noqa: E402

#: 冷启动先验表（groom 的 `verification \ confidence(调查质量)` 那张表，执行值不另存一处）。
PRIORS = {
    "upstream-fix-merged": {"high": 0.75, "medium": 0.6, "low": 0.5},
    "upstream-official-doc": {"high": 0.7, "medium": 0.55, "low": 0.45},
    "upstream-maintainer-confirmed": {"high": 0.65, "medium": 0.5, "low": 0.4},
    "engineer-report": {"high": 0.85, "medium": 0.7, "low": 0.6},
    "investigation": {"high": 0.6, "medium": 0.3, "low": 0.1},
}
#: 未填来源时按 `investigation` 行（与 groom 表一致）。
DEFAULT_VERIFICATION = "investigation"
#: 调查质量的合法档。表外的值（实测有 `low-medium`）落到 `low`，并在输出里报出来。
QUALITIES = ("high", "medium", "low")
DEFAULT_QUALITY = "low"

#: 先验的等效观测数（先验值折几条现场观测）。
PRIOR_STRENGTH = 4.0
#: 自证的权重（弱证据记半分）。
SELF_WEIGHT = 0.5
#: 计数权重减半所需的周数（与 groom 的「近 12 周未解决」同一窗口）。
HALF_LIFE_WEEKS = 12.0


def _week_index(week: str):
    """ISO 周标签 → 可用于求差的序数（周一起算）。解析不出返回 None。"""
    try:
        y, w = int(week[:4]), int(week[6:])
        return date.fromisocalendar(y, w, 1).toordinal() // 7
    except (ValueError, IndexError):
        return None


def _decay(week: str, anchor: str) -> float:
    """一次运行的计数权重：距锚点每 HALF_LIFE_WEEKS 周减半。"""
    a, b = _week_index(week), _week_index(anchor)
    if a is None or b is None:
        return 1.0
    weeks = max(0, b - a)
    return 0.5 ** (weeks / HALF_LIFE_WEEKS)


def _prior(source, quality):
    row = PRIORS.get(source if source in PRIORS else DEFAULT_VERIFICATION)
    q = quality if quality in QUALITIES else DEFAULT_QUALITY
    return row[q]


def load_records(root: Path):
    """读仓里全部部署的记录生成物 → ({id: {counts, by_week, baseline}}, 锚点周, 覆盖的部署)。"""
    merged, anchor, deps = {}, None, []
    d = ea.generated_dir(root)
    if not d.is_dir():
        return merged, anchor, deps
    for f in sorted(d.glob("*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        deps.append(((doc.get("covered") or {}).get("deployment") or f.stem))
        for cid, e in (doc.get("cases") or {}).items():
            slot = merged.setdefault(str(cid), {"by_week": {}, "baseline": False})
            tot = e.get("totals") or {}
            if tot.get("baseline"):
                # 搬运行跨部署要**求和**：同一个 id 在两份部署里各有一条搬运行时，赋值会让
                # 后读到的那份覆盖前一份，而模块头注与设计文档写的都是「按 id 求和」。
                slot["baseline"] = True
                for k in ("resolved", "misdiagnosed", "self_resolved"):
                    slot["baseline_" + k] = slot.get("baseline_" + k, 0) + int(tot.get(k, 0) or 0)
            for wk, wc in (e.get("by_week") or {}).items():
                cur = slot["by_week"].setdefault(str(wk), {"resolved": 0, "misdiagnosed": 0,
                                                           "self_resolved": 0})
                for k in cur:
                    cur[k] += int((wc or {}).get(k, 0) or 0)
                if anchor is None or str(wk) > anchor:
                    anchor = str(wk)
    return merged, anchor, sorted(set(deps))


def case_meta(root: Path):
    """全库案例 → ({id: {verification_source, quality, score_override, file}}, 表外值清单)。"""
    out, odd_q, odd_v = {}, [], []
    kdir = Path(root) / "knowledge"
    if not kdir.is_dir():
        return out, odd_q, odd_v
    for f in sorted(kdir.rglob("*.yaml")):
        if f.name.startswith("_") or "_archive" in f.parts:
            continue
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for c in (doc.get("cases") or []):
            cid = c.get("id")
            if not cid:
                continue
            v = c.get("verification") or {}
            src = (v.get("source") if isinstance(v, dict) else None) or None
            q = c.get("investigation_quality")
            if q is not None and q not in QUALITIES:
                odd_q.append(f"{cid}: investigation_quality={q!r}")
            if src is not None and src not in PRIORS:
                odd_v.append(f"{cid}: verification.source={src!r}")
            out[str(cid)] = {"verification_source": src, "quality": q,
                             "score_override": c.get("score_override"), "file": str(f)}
    return out, odd_q, odd_v


def compute(root: Path):
    """全库算分 → {cases: {id: {...}}, meta: {...}}。"""
    records, anchor, deps = load_records(root)
    meta, odd_q, odd_v = case_meta(root)
    cases = {}
    for cid in sorted(meta):
        m = meta[cid]
        src = m["verification_source"]
        p0 = _prior(src, m["quality"])
        rec = records.get(cid) or {}
        resolved = mis = self_n = 0.0
        for wk, wc in (rec.get("by_week") or {}).items():
            w = _decay(wk, anchor) if anchor else 1.0
            resolved += w * wc.get("resolved", 0)
            mis += w * wc.get("misdiagnosed", 0)
            self_n += w * wc.get("self_resolved", 0)
        # 搬运行没有运行周，不参与衰减（生命周期累计值按原样进入后验）。
        resolved += rec.get("baseline_resolved", 0)
        mis += rec.get("baseline_misdiagnosed", 0)
        self_n += rec.get("baseline_self_resolved", 0)

        ov = m["score_override"]
        if isinstance(ov, dict) and ov.get("score") is not None:
            score = float(ov["score"])
            source = "override"
        elif resolved or mis or self_n:
            a = p0 * PRIOR_STRENGTH + resolved + SELF_WEIGHT * self_n
            b = (1 - p0) * PRIOR_STRENGTH + mis
            score = a / (a + b)
            source = "records"
        else:
            score = p0
            source = "prior"
        cases[cid] = {
            "score": round(score, 4),
            "source": source,
            "prior": p0,
            "verification_source": src or DEFAULT_VERIFICATION,
            "investigation_quality": m["quality"] if m["quality"] in QUALITIES else DEFAULT_QUALITY,
            "resolved": round(resolved, 3),
            "misdiagnosed": round(mis, 3),
            "self_resolved": round(self_n, 3),
            **({"override": ov} if source == "override" else {}),
            "file": m["file"],
        }
    modes = {c["source"] for c in cases.values()}
    mode = ("prior" if modes == {"prior"} else "records" if modes == {"records"}
            else "records+prior" if modes == {"records", "prior"} else "mixed")
    return {
        "cases": cases,
        "meta": {
            "anchor_week": anchor,
            "deployments": deps,
            "records_present": bool(deps),
            "score_source": mode,
            "prior_strength": PRIOR_STRENGTH,
            "self_weight": SELF_WEIGHT,
            "half_life_weeks": HALF_LIFE_WEEKS,
            "unrecognized_quality": odd_q,
            "unrecognized_verification": odd_v,
            "with_records": sum(1 for c in cases.values() if c["source"] == "records"),
            "prior_only": sum(1 for c in cases.values() if c["source"] == "prior"),
            "overridden": sum(1 for c in cases.values() if c["source"] == "override"),
        },
    }


def check_overrides(root: Path):
    """`score_override` 的判据：必须是 `{score, reason, by}`，`reason` 非空、score 在 [0,1]。"""
    bad = []
    kdir = Path(root) / "knowledge"
    if not kdir.is_dir():
        return bad
    for f in sorted(kdir.rglob("*.yaml")):
        if f.name.startswith("_") or "_archive" in f.parts:
            continue
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for c in (doc.get("cases") or []):
            ov = c.get("score_override")
            if ov is None:
                continue
            where = f"{f.relative_to(root)}（{c.get('id')}）"
            if not isinstance(ov, dict):
                bad.append(f"{where}: score_override 应为映射（score/reason/by）")
                continue
            try:
                s = float(ov.get("score"))
            except (TypeError, ValueError):
                bad.append(f"{where}: score_override.score 缺失或不是数字")
                continue
            if not (0.0 <= s <= 1.0):
                bad.append(f"{where}: score_override.score={s} 不在 [0, 1]")
            if not str(ov.get("reason") or "").strip():
                bad.append(f"{where}: score_override 必带 reason（没有理由的覆盖半年后无法判断该不该撤）")
            if not str(ov.get("by") or "").strip():
                bad.append(f"{where}: score_override 必带 by（谁覆盖的）")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description="条目排序分数：记录计数 + 冷启动先验")
    ap.add_argument("--root", default=None, help="检出根（默认：脚本上两级）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--entry", default=None, help="只看某一条的算分明细")
    ap.add_argument("--check-overrides", action="store_true", help="只校验 score_override 字段")
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]

    if args.check_overrides:
        bad = check_overrides(root)
        for b in bad:
            print(f"score_override 问题：{b}")
        if bad:
            return 1
        print("✓ score_override 字段合法（有则必带 reason 与 by，score ∈ [0,1]）")
        return 0

    result = compute(root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0
    m = result["meta"]
    if args.entry:
        c = result["cases"].get(args.entry)
        if not c:
            print(f"没有这条条目：{args.entry}", file=sys.stderr)
            return 2
        print(json.dumps(c, ensure_ascii=False, indent=1))
        return 0
    print(f"算分：{len(result['cases'])} 条案例；锚点周 {m['anchor_week']}；"
          f"分数来源 {m['score_source']}（有记录 {m['with_records']} / 退回先验 {m['prior_only']}"
          f" / 人工覆盖 {m['overridden']}）")
    print(f"参数：先验等效观测 {m['prior_strength']}、自证权重 {m['self_weight']}、"
          f"衰减半衰期 {m['half_life_weeks']} 周")
    if m["unrecognized_quality"]:
        print("调查质量档表外的条目（按 low 处理，请改成 high/medium/low）：")
        for x in m["unrecognized_quality"]:
            print(f"  · {x}")
    if m["unrecognized_verification"]:
        print("来源验证档表外的条目（按 investigation 处理，请改正）：")
        for x in m["unrecognized_verification"]:
            print(f"  · {x}")
    return 0


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
