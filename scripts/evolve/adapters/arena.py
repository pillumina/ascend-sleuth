"""``eval_arena --stats`` 产出的配对读数。

只做一件事：从 baseline / candidate 两份 stats 的逐条向量 ``issues`` 里数出
配对检验需要的 ``b`` / ``c`` / ``n``。不写 arena 的影响账本，也不替调用方判定；
账本与判词仍归 ``eval_arena.py`` / ``evolve.decision``。

过滤规则与 arena 的 ``vectors()`` 一致：

- 两边都有同一个 ``id``；
- 两侧都不是 ``held_out``（终判集）或 ``non_diagnostic``；
- ``hit`` 可判（必须是布尔）；缺失或非布尔记 unknown，不补 false。

``n`` 是**配对后可判的样本数**，不是某一份 stats 的总样本数。
"""

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml

from . import AdapterError


def _rows(stats: Any, side: str) -> Dict[str, Dict[str, Any]]:
    if not isinstance(stats, dict):
        raise AdapterError(f"{side} stats must be an object")
    issues = stats.get("issues")
    if issues is None:
        return {}
    if not isinstance(issues, list):
        raise AdapterError(f"{side} stats.issues must be a list")
    rows: Dict[str, Dict[str, Any]] = {}
    for row in issues:
        if not isinstance(row, dict):
            continue
        sample = row.get("id")
        if sample is None or str(sample).strip() == "":
            continue
        if row.get("held_out") or row.get("non_diagnostic"):
            continue
        if not isinstance(row.get("hit"), bool):
            continue
        rows[str(sample)] = row
    return rows


def paired_counts(baseline: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    """返回 ``{"b", "c", "n", ...}``；纯函数，只读两份 stats 字典。

    - ``b``：候选命中、基线未命中的样本数；
    - ``c``：基线命中、候选未命中的样本数；
    - ``n``：两侧同 id 且 ``hit`` 可判的样本数。
    """
    base = _rows(baseline, "baseline")
    cand = _rows(candidate, "candidate")
    common = sorted(set(base) & set(cand))
    candidate_only: List[str] = []
    baseline_only: List[str] = []
    for sample in common:
        base_hit = base[sample]["hit"]
        cand_hit = cand[sample]["hit"]
        if cand_hit and not base_hit:
            candidate_only.append(sample)
        elif base_hit and not cand_hit:
            baseline_only.append(sample)
    return {
        "b": len(candidate_only),
        "c": len(baseline_only),
        "n": len(common),
        "paired_ids": common,
        "candidate_only_ids": candidate_only,
        "baseline_only_ids": baseline_only,
    }


def _load_stats(path: Any, side: str) -> Dict[str, Any]:
    stats_path = Path(path)
    try:
        text = stats_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AdapterError(f"cannot read {side} stats {stats_path}: {exc}") from exc
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AdapterError(f"invalid {side} stats YAML {stats_path}: {exc}") from exc
    if not isinstance(document, dict):
        raise AdapterError(f"{side} stats must contain an object: {stats_path}")
    return document


def _assert_comparable(baseline: Dict[str, Any], candidate: Dict[str, Any]) -> None:
    """拒绝跨池纪元与吸收状态已失效的两份 stats。

    这和 ``eval_arena.decide()`` 的跨池守卫同一语义：池内容哈希不同，两次读数
    不是同一把尺子；吸收状态 stale 说明样本答案已进知识库，读数测的是背诵。
    """
    hb = baseline.get("pool_hash")
    hc = candidate.get("pool_hash")
    if hb and hc and hb != hc:
        raise AdapterError(
            "cross-pool comparison rejected: baseline and candidate pool_hash differ"
        )
    for side, stats in (("baseline", baseline), ("candidate", candidate)):
        recheck = stats.get("absorption_recheck")
        if isinstance(recheck, dict) and recheck.get("stale"):
            raise AdapterError(
                f"{side} absorption state is stale; re-run --stats before judging"
            )


def counts_from_files(baseline: Any, candidate: Any) -> Dict[str, Any]:
    """读两份 stats YAML 再配对；跨池/吸收失效直接拒绝。"""
    base = _load_stats(baseline, "baseline")
    cand = _load_stats(candidate, "candidate")
    _assert_comparable(base, cand)
    return paired_counts(base, cand)


def paired_rows(
    baseline: Dict[str, Any], candidate: Dict[str, Any]
) -> Iterable[Tuple[str, bool, bool]]:
    """逐条产出 ``(id, baseline_hit, candidate_hit)``，便于调用方做别的配对读数。"""
    base = _rows(baseline, "baseline")
    cand = _rows(candidate, "candidate")
    for sample in sorted(set(base) & set(cand)):
        yield sample, base[sample]["hit"], cand[sample]["hit"]
