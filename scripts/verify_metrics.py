#!/usr/bin/env python3
# verify_metrics.py —— 校验 metrics/timeline.yaml 的指标时序数据结构
#
# 目的（原则二：不变量写进结构）：metrics 曾因快照字段格式漂移（W28/W35 字段
# 完全不同）导致跨期不可比、趋势不可算。把"每期必须记录什么、字段怎么组织"
# 从约定变成 CI 可校验的结构。
#
# 校验内容：
#   1. period 必填且全局唯一（趋势对比的锚点）
#   2. kind ∈ {live, replay, example}（只有 live 参与趋势）
#   3. metrics 为 mapping 且非空（每期必须带指标数据）
#   4. 常见比例字段（ok/total 形）合法：total 为正整数、ok 不越界
#   5. recorded_at 必填（人审日期，不可自动戳——与 reference last_verified 同语义）
#
# 用法：python3 scripts/verify_metrics.py [--check] [--root <repo>]
# 返回非零 = 校验失败。--check 与默认行为一致（对称 build_index / verify_references）。

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import yaml


def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"__yaml_error__": str(e)}


# live 快照字段白名单
# ——来源一：trace_metrics.py --emit-yaml（诊断侧，单一实现）
# ——来源二：metrics_snapshot.py 组装的结构侧与内容流程侧（2026-09-10 起）
#   为什么结构侧也要进 live：容量格子/case 数/reference 数是**最该看趋势**的治理指标，
#   而它们原先只能出现在 kind=replay 的快照里，按"只有 live 参与趋势"的规则等于没有趋势通道
#   （实测：某格已 85/30、快照里还停在 36/30）。字段名仍是白名单制，防漂移。
LIVE_FIELDS = {
    # 诊断侧（trace_metrics.py）
    "sessions_total", "tier2_hit", "routed_accuracy", "misdiagnosis_rate",
    "by_category_hit", "attribution_ratio", "confidence_distribution",
    "feedback_capture", "trace_completeness", "vocab_compliance", "tier3",
    "reference", "reference_detail",
    # 结构侧（metrics_snapshot.py ← build_index 头注 / verify_references）
    "case_total", "reference_total", "capacity_by_ns",
    # 内容流程侧（metrics_snapshot.py ← tail_exec_log 聚合）
    "content_flow_runs", "evolve_check_runs", "evolve_check_no_signal",
}


def check_ratio(rel: str, period: str, field: str, val, errors: list):
    """校验 {ok, total} 形比例字段：total 为正整数、ok 非负且不越界。"""
    if not isinstance(val, dict):
        errors.append(f"{rel} [{period}]: metrics.{field} 应为 {ok,total} 形 mapping")
        return
    ok = val.get("ok")
    total = val.get("total")
    if not isinstance(total, int) or total <= 0:
        errors.append(f"{rel} [{period}]: metrics.{field}.total 必须为正整数（{total!r}）")
        return
    if not isinstance(ok, int) or ok < 0 or ok > total:
        errors.append(f"{rel} [{period}]: metrics.{field}.ok 必须为 0..total 的整数（{ok!r}）")


# live 期号的命名规则（2026-09 起）：`YYYY-Www-live-MMDD`，如 `2026-W37-live-0912`。
#
# 为什么需要：期号是**趋势锚点**，而周批可由任何人跑（CLAUDE.md 多 agent 节：并发修改靠 PR merge
# 显式合并）。两个 groomer 各 append 一期时，手写期号有两种坏结局——同名（CI 靠 period 唯一性拦住，
# 但拦在 merge 时）与异名同期（各自进 main，趋势线上同一周两个数字，读的人分不清哪个是真的）。
# 期号带上快照日期后，两个人产出的期号天然不撞，"两个不同时点"也一眼可辨。
#
# 存量豁免（沿用 verify_proposals 的 MEASURE_CUTOVER 先例）：早于 cutover 的期不追溯改名——
# 改名是改写历史锚点，而 metrics/timeline.yaml 是 append-only 数据。豁免是如实标注，不是放宽。
#
# 末尾的 `(-\d+)?` 是**同天第二期**的后缀：期号只带日期、不带人，同一天两人各跑一次会撞同一个号，
# 生成器撞号时自动加 `-2`（见 metrics_snapshot.next_available_period）。不带后缀的横线形状即
# "一天一期"，带后缀即"同一天的第 N 期"——两者都合法，且都不会撞上别人的号。
PERIOD_NAMING_CUTOVER = date(2026, 9, 12)
LIVE_PERIOD_RE = re.compile(r"^\d{4}-W\d{2}-live-\d{4}(-\d+)?$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="CI 模式（与默认行为一致，对称 build_index）")
    ap.add_argument("--root", default=None, help="仓库根目录（默认：脚本上两级）")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    path = root / "metrics" / "timeline.yaml"
    if not path.exists():
        print(f"metrics/timeline.yaml 不存在 —— metrics 数据层未落地？")
        sys.exit(1)

    doc = load_yaml(path)
    if isinstance(doc, dict) and doc.get("__yaml_error__"):
        print(f"metrics/timeline.yaml YAML 解析失败: {doc['__yaml_error__']}")
        sys.exit(1)
    if not isinstance(doc, dict) or "periods" not in doc:
        print("metrics/timeline.yaml 缺少 periods 列表")
        sys.exit(1)

    periods = doc["periods"]
    if not isinstance(periods, list) or len(periods) == 0:
        print("metrics/timeline.yaml periods 必须是非空列表（至少一条历史记录）")
        sys.exit(1)

    VALID_KINDS = {"live", "replay", "example"}
    errors = []
    seen = {}
    for i, p in enumerate(periods):
        if not isinstance(p, dict):
            errors.append(f"periods[{i}] 不是 mapping")
            continue
        pid = p.get("period")
        if not pid:
            errors.append(f"periods[{i}]: 缺少 period")
            continue
        if pid in seen:
            errors.append(
                f"periods[{i}]: period '{pid}' 与 periods[{seen[pid]}] 重复（趋势锚点必须唯一）。"
                f"两种合法处置：① 同期两次快照 → 给其中一期加后缀（如 '-2'，见 metrics_snapshot 的自动加后缀）；"
                f"② 确认两份读数一致 → 删掉一份。**不要**两份都留（趋势线上同一期两个数字，读者分不清哪个是真的）"
            )
        else:
            seen[pid] = i

        rel = f"periods[{i}]"
        kind = p.get("kind")
        if not kind:
            errors.append(f"{rel} [{pid}]: 缺少 kind")
        elif kind not in VALID_KINDS:
            errors.append(f"{rel} [{pid}]: kind '{kind}' 非法（合法: {', '.join(sorted(VALID_KINDS))}）")

        if not p.get("recorded_at"):
            errors.append(f"{rel} [{pid}]: 缺少 recorded_at（人审日期，不可自动戳）")

        # live 期号命名规则（cutover 后强制；见 LIVE_PERIOD_RE 的注释说明为什么）
        if kind == "live" and isinstance(pid, str) and not LIVE_PERIOD_RE.match(pid):
            ra = p.get("recorded_at")
            ra_date = None
            if hasattr(ra, "year"):
                ra_date = date(ra.year, ra.month, ra.day)
            elif ra is not None:
                try:
                    ra_date = date.fromisoformat(str(ra)[:10])
                except ValueError:
                    ra_date = None
            if ra_date is not None and ra_date >= PERIOD_NAMING_CUTOVER:
                errors.append(
                    f"{rel} [{pid}]: live 期号应为 YYYY-Www-live-MMDD（同天第二期加 -2 等后缀），"
                    f"如 2026-W37-live-0913 / 2026-W37-live-0913-2；期号是趋势锚点，带快照日期才不至于"
                    f"两人产出同名或同期两个数字（{PERIOD_NAMING_CUTOVER.isoformat()} 之前的期豁免，"
                    f"不追溯改名）"
                )

        metrics = p.get("metrics")
        if not isinstance(metrics, dict) or len(metrics) == 0:
            errors.append(f"{rel} [{pid}]: metrics 必须是非空 mapping（每期必须带指标数据）")
        else:
            # 比例字段白名单（{ok,total} 形）——结构固定才能跨期对比
            # （golden_suite 是 before/after 增长，不是 ok/total 比例，不在此列）
            for field in ("semantic_validation_rate", "routed_accuracy", "candidate_recall",
                          "cross_replay_rank1"):
                if field in metrics:
                    check_ratio(rel, pid, field, metrics[field], errors)
            # live 字段白名单（防字段漂移——W28/W35 教训的 live 侧）
            # live 快照字段集合由 trace_metrics.py 固定生成（单一数据源），
            # 人复核只能增删"值"不能发明"新字段名"（字段名漂移 = 跨期不可比）。
            # 允许字段缺失（诚实退化：无数据如实不写），但不允许白名单外字段。
            if kind == "live":
                unknown = sorted(set(metrics.keys()) - LIVE_FIELDS)
                if unknown:
                    errors.append(
                        f"{rel} [{pid}]: live 字段超出白名单 {unknown}"
                        f"（合法字段: {', '.join(sorted(LIVE_FIELDS))}；字段名漂移=跨期不可比，"
                        f"W28/W35 教训）"
                    )
        # sources：逐块出处（metrics_snapshot.py 组装时写；没有也能是手写快照）
        srcs = p.get("sources")
        if srcs is not None and not isinstance(srcs, dict):
            errors.append(f"{rel} [{pid}]: sources 应为 mapping（块名 → 出处说明），便于回溯每个指标块")

    if errors:
        print(f"metrics/timeline.yaml 校验失败（{len(errors)} 处）：")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    n_live = sum(1 for p in periods if p.get("kind") == "live")
    print(f"metrics 校验通过（{len(periods)} 期，其中 live {n_live}）")


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
