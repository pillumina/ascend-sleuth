"""用量维度的接线表：命令行、pilot 与 flow 共用一份。

一个维度 = 名字、组件、collect 里的键、trace 解析、汇总、判定与人读输出。
新增维度加一条记录（与一个模块）即可；CLI 子命令、pilot 的约束循环与 flow 的
证据映射都从这里取，不改三处各自的实现。
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from . import knowledge_usage, source_usage, tool_usage


@dataclass(frozen=True)
class TraceOption:
    """``from-trace`` 的附加参数：文本参数或 true/false 三态参数。"""

    dest: str
    flag: str
    choices: Tuple[str, ...] = ()

    def convert(self, raw: Any) -> Any:
        if raw is None:
            return None
        if self.choices:
            return raw == "true"
        return raw


@dataclass(frozen=True)
class UsageDimension:
    name: str
    label: str
    help: str
    component: str
    arm_key: str
    from_trace: Callable[..., Dict[str, Any]]
    evaluate: Callable[[Any], Dict[str, Any]]
    compare: Callable[[Any, Any], Dict[str, Any]]
    trace_options: Tuple[TraceOption, ...] = ()
    trace_help: str = "从 diagnose trace 推导 usage"
    evaluate_help: str = "汇总 usage"
    compare_help: str = "usage 门禁"
    trace_lines: Callable[[Dict[str, Any]], List[str]] = lambda result: []
    evaluate_lines: Callable[[Dict[str, Any]], List[str]] = lambda result: []
    compare_lines: Callable[[Dict[str, Any]], List[str]] = lambda result: []
    human_evaluate: bool = False
    human_compare: bool = False


def _knowledge_trace_lines(result: Dict[str, Any]) -> List[str]:
    return [f"sample_id: {result['sample_id']}",
            f"hit: {result['hit']} first_hit_step={result['first_hit_step']}"]


def _source_trace_lines(result: Dict[str, Any]) -> List[str]:
    return [f"sample_id: {result['sample_id']}",
            f"files_read: {result['files_read']} tool_calls: {result['tool_calls']}"]


def _tool_trace_lines(result: Dict[str, Any]) -> List[str]:
    return [f"sample_id: {result['sample_id']}",
            f"tool_calls: {result['tool_calls']} fetch: {result['fetch_calls']} "
            f"grep: {result['grep_calls']} retries: {result['retries']}"]


def _knowledge_evaluate_lines(result: Dict[str, Any]) -> List[str]:
    return [f"samples: {result['n']}",
            f"hit_rate: {result['hit_rate']:.3f}",
            f"wrong_cases: {result['wrong_cases']}"]


def _knowledge_compare_lines(result: Dict[str, Any]) -> List[str]:
    return [f"decision: {result['decision']}",
            f"reasons: {', '.join(result['reasons']) or 'none'}",
            f"baseline hit_rate: {result['baseline']['hit_rate']:.3f}",
            f"candidate hit_rate: {result['candidate']['hit_rate']:.3f}"]


DIMENSIONS: Tuple[UsageDimension, ...] = (
    UsageDimension(
        name="knowledge", label="knowledge-usage", help="知识使用效率观测/对照",
        component="diagnose.knowledge_usage", arm_key="knowledge_usage",
        from_trace=knowledge_usage.from_trace,
        evaluate=knowledge_usage.evaluate,
        compare=knowledge_usage.compare,
        trace_options=(TraceOption("expected_case", "--expected-case"),),
        trace_help="从 diagnose trace 推导 usage",
        evaluate_help="汇总一份 usage 记录",
        compare_help="baseline/candidate 使用效率门禁",
        trace_lines=_knowledge_trace_lines,
        evaluate_lines=_knowledge_evaluate_lines,
        compare_lines=_knowledge_compare_lines,
        human_evaluate=True,
        human_compare=True,
    ),
    UsageDimension(
        name="source", label="source-usage", help="源码访问效率观测/对照",
        component="diagnose.source_usage", arm_key="source_usage",
        from_trace=source_usage.from_trace,
        evaluate=source_usage.evaluate,
        compare=source_usage.compare,
        trace_options=(TraceOption("source_ok", "--source-ok", ("true", "false")),),
        trace_help="从 diagnose trace 推导 source usage",
        evaluate_help="汇总 source usage",
        compare_help="source usage 门禁",
        trace_lines=_source_trace_lines,
    ),
    UsageDimension(
        name="tool", label="tool-usage", help="工具使用与工具性能观测/对照",
        component="", arm_key="tool_usage",
        from_trace=tool_usage.from_trace,
        evaluate=tool_usage.evaluate,
        compare=tool_usage.compare,
        trace_options=(TraceOption("resolved", "--resolved", ("true", "false")),),
        trace_help="从 diagnose trace 推导 tool usage",
        evaluate_help="汇总 tool usage",
        compare_help="tool usage 门禁",
        trace_lines=_tool_trace_lines,
    ),
)

BY_NAME: Dict[str, UsageDimension] = {dimension.name: dimension for dimension in DIMENSIONS}
BY_COMPONENT: Dict[str, UsageDimension] = {
    dimension.component: dimension for dimension in DIMENSIONS if dimension.component
}
