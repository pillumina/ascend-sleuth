"""trace 归因到 skill 可变异区的静态映射。

这是“自动选点”的边界：系统从归因组件里选已登记的区，不向用户要区；
没有匹配项就返回空，让 self-evolve 记 insufficient，而不是猜。
"""

from dataclasses import dataclass
from typing import Dict, List

from .targets.base import DEFAULT_TARGET


@dataclass(frozen=True)
class RegionSpec:
    id: str
    skill: str
    components: tuple
    description: str
    target_kind: str = DEFAULT_TARGET
    paths: tuple = ()
    markers: tuple = ()


REGIONS: Dict[str, RegionSpec] = {
    "diagnose.routing_hints": RegionSpec(
        id="diagnose.routing_hints", skill="diagnose",
        components=("routing", "triage", "routing_miss"),
        description="triage 提示、追问顺序、路由提示；不改 phase/工具/schema",
        markers=("triage", "路由", "追问", "routing"),
    ),
    "diagnose.verification_checklist": RegionSpec(
        id="diagnose.verification_checklist", skill="diagnose",
        components=("quickly_check", "verification", "case_hit", "diagnosis"),
        description="候选验证与证据检查顺序；不改 case 内容与输出 schema",
        markers=("quickly_check", "验证", "候选", "排除"),
    ),
    "diagnose.trace_evidence": RegionSpec(
        id="diagnose.trace_evidence", skill="diagnose",
        components=("skill:diagnose step<trace写作 evidence 落盘>", "trace_evidence"),
        description="trace 写作与 evidence 落盘步骤的说明；不改 trace schema",
        markers=("trace", "evidence", "证据"),
    ),
    "diagnose.source_usage": RegionSpec(
        id="diagnose.source_usage", skill="diagnose",
        components=("source_usage", "source_fetch", "source_query", "source_analysis"),
        description="源码访问策略：缓存优先、固定 ref、限定路径与 grep 范围、失败停止；不改知识内容/schema",
        markers=("源码分析", "src_fetch", "grep 定位", "source_analysis"),
    ),
    "diagnose.knowledge_usage": RegionSpec(
        id="diagnose.knowledge_usage", skill="diagnose",
        components=("knowledge_usage", "case_retrieval", "case_loading", "reference_lookup"),
        description="知识检索顺序、读索引/全文时机、候选数、reference 查询与停止条件；不改 case 内容/schema",
        markers=("知识", "reference", "索引", "全文", "候选数"),
    ),
    "knowledge.case_content": RegionSpec(
        id="knowledge.case_content", skill="knowledge", target_kind="knowledge",
        components=("case_content", "case_miss", "wrong_case"),
        description="单条 case 的内容/判别力；走 rubric 与人工审",
        markers=("症状", "symptoms", "quickly_check", "判别"),
    ),
    "knowledge.reference_content": RegionSpec(
        id="knowledge.reference_content", skill="knowledge", target_kind="knowledge",
        components=("reference_content", "reference_miss"),
        description="reference 词条的事实/范围；走 rubric 与人工审",
        markers=("词条", "适用范围", "来源", "scope"),
    ),
    "harness.scheduler": RegionSpec(
        id="harness.scheduler", skill="harness", target_kind="harness",
        components=("harness_scheduler", "scheduler", "budget", "stop"),
        description="调度、控制流、预算与停止条件；高风险，走 end-to-end 回归",
        paths=("scripts/", "eval/"),
        markers=("scheduler", "调度", "budget", "预算", "stop", "停止"),
    ),
    # tooling 区改的是工具本身，不是使用工具的提示文本。
    "tooling.source_fetch": RegionSpec(
        id="tooling.source_fetch", skill="tooling", target_kind="tooling",
        components=("source_fetch", "source_cache", "source_retry"),
        description="源码获取工具的缓存、重试、ref 解析与失败停止；不改诊断 skill 的指示",
        paths=("scripts/src_fetch.py", "source-catalog.d"),
        markers=("src_fetch", "cache", "缓存", "retry", "重试", "ref"),
    ),
    "tooling.source_catalog": RegionSpec(
        id="tooling.source_catalog", skill="tooling", target_kind="tooling",
        components=("source_catalog", "source_catalog_miss"),
        description="源码仓与签名候选表（数据，不改解析代码）",
        paths=("source-catalog.d",),
        markers=("catalog", "repo", "仓", "签名", "signature"),
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
                "target_kind": region.target_kind,
                "hard": hard, "events": events,
                "description": region.description,
            })
    return sorted(scored, key=lambda item: (-item["hard"], -item["events"], item["region"]))
