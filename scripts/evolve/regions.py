"""trace 归因到 skill 可变异区的静态映射。

这是“自动选点”的边界：系统从归因组件里选已登记的区，不向用户要区；
没有匹配项就返回空，让 self-evolve 记 insufficient，而不是猜。
"""

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class RegionSpec:
    id: str
    skill: str
    components: tuple
    description: str


REGIONS: Dict[str, RegionSpec] = {
    "diagnose.routing_hints": RegionSpec(
        id="diagnose.routing_hints", skill="diagnose",
        components=("routing", "triage", "routing_miss"),
        description="triage 提示、追问顺序、路由提示；不改 phase/工具/schema",
    ),
    "diagnose.verification_checklist": RegionSpec(
        id="diagnose.verification_checklist", skill="diagnose",
        components=("quickly_check", "verification", "case_hit"),
        description="候选验证与证据检查顺序；不改 case 内容与输出 schema",
    ),
    "diagnose.trace_evidence": RegionSpec(
        id="diagnose.trace_evidence", skill="diagnose",
        components=("skill:diagnose step<trace写作 evidence 落盘>", "trace_evidence"),
        description="trace 写作与 evidence 落盘步骤的说明；不改 trace schema",
    ),
    "knowledge.case_content": RegionSpec(
        id="knowledge.case_content", skill="knowledge",
        components=("case_content", "case_miss", "wrong_case"),
        description="单条 case 的内容/判别力；走 rubric 与人工审",
    ),
    "knowledge.reference_content": RegionSpec(
        id="knowledge.reference_content", skill="knowledge",
        components=("reference_content", "reference_miss"),
        description="reference 词条的事实/范围；走 rubric 与人工审",
    ),
}


def recommend(components: Dict[str, Dict[str, int]]) -> List[Dict[str, object]]:
    """按硬归因数排序，返回可自动实验的区；没有就空。"""
    scored = []
    for region in REGIONS.values():
        hard = sum(
            int((components.get(component) or {}).get("hard", 0))
            for component in region.components
        )
        events = sum(
            int((components.get(component) or {}).get("events", 0))
            for component in region.components
        )
        if hard or events:
            scored.append({
                "region": region.id, "skill": region.skill,
                "hard": hard, "events": events,
                "description": region.description,
            })
    return sorted(scored, key=lambda item: (-item["hard"], -item["events"], item["region"]))
