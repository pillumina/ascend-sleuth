"""评测门禁：每个评测面一套执行逻辑，CLI 只整理参数与打印。

新增评测面 = 在这里写一个 gate 函数、注册到 ``GATES``，并在
``evaluations/registry.py`` 的 ``EvalProfile.gate`` 里指向它；不再往 CLI 的
``experiment gate`` 里加分支。

门禁自己读文件（比对两份 JSON）、起子进程（arena 走 ``scripts/eval_arena.py``）；
评分与判定规则留在 ``scoring``、``tool_usage`` 等核心模块。
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from ..inputs import json_object
from ..scoring import score_rubric
from ..tool_usage import compare as compare_tool_usage


class GateError(ValueError):
    """门禁缺参数、目标未实现，或输出不满足评测面的前提。"""


@dataclass(frozen=True)
class GateRequest:
    """一次门禁调用的输入：CLI 填参数与已加载的样本，门禁自己解析 JSON 文本。"""

    root: Path
    profile_id: str
    target: str
    baseline: Optional[str] = None
    candidate: Optional[str] = None
    component: Optional[str] = None
    candidate_ref: Optional[str] = None
    note: Optional[str] = None
    alpha: float = 0.05
    object_types: Tuple[str, ...] = ()
    sample: Any = None
    scores_text: Optional[str] = None
    threshold: Optional[float] = None


@dataclass(frozen=True)
class GateOutcome:
    """退出码与人读输出；``passthrough`` 表示子进程已自己打印。"""

    code: int
    lines: Tuple[str, ...] = ()
    passthrough: bool = False


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise GateError(message)


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _parse_scores(text: Optional[str]) -> Optional[Dict[str, float]]:
    """在样本检查之后解析 --scores：顺序与旧实现一致，组合错误报旧的先。"""
    return json_object(text, "--scores", GateError)


def _run_arena_gate(request: GateRequest) -> GateOutcome:
    _require(request.baseline and request.candidate and request.component,
             "arena gate requires --baseline, --candidate and --component")
    root = Path(request.root)
    command = [sys.executable, str(root / "scripts" / "eval_arena.py"),
               "--gate", "--baseline", request.baseline,
               "--candidate", request.candidate,
               "--component", request.component,
               "--alpha", str(request.alpha), "--root", str(root)]
    if request.candidate_ref:
        command += ["--candidate-ref", request.candidate_ref]
    if request.note:
        command += ["--note", request.note]
    return GateOutcome(code=subprocess.run(command, cwd=str(root)).returncode,
                       passthrough=True)


def _run_replay_trace_gate(request: GateRequest) -> GateOutcome:
    _require(request.baseline and request.candidate,
             "replay_trace gate requires --baseline and --candidate")
    result = compare_tool_usage(_read_json(request.baseline),
                                _read_json(request.candidate))
    lines = (
        f"target: {request.target}",
        f"eval_profile: {request.profile_id}",
        f"decision: {result['decision']}",
        f"reasons: {', '.join(result['reasons']) or 'none'}",
        json.dumps(result["deltas"], ensure_ascii=False, sort_keys=True),
    )
    return GateOutcome(code=0 if result["decision"] == "accept" else 1, lines=lines)


def _run_rubric_gate(request: GateRequest) -> GateOutcome:
    _require(request.sample is not None and request.scores_text is not None,
             "rubric gate requires --sample and --scores")
    sample = request.sample
    if sample.object_type not in request.object_types:
        raise GateError(
            f"sample {sample.id!r} object_type {sample.object_type!r} is not "
            f"in target {request.target!r} ({', '.join(request.object_types)})"
        )
    if sample.rubric is None:
        raise GateError(f"sample {sample.id!r} has no rubric")
    scores = _parse_scores(request.scores_text)
    result = score_rubric(sample.rubric, scores, threshold=request.threshold)
    lines = [
        f"target: {request.target}",
        f"eval_profile: {request.profile_id}",
        f"passed: {str(result.passed).lower()}",
        (f"score: {result.score:.4f}" if result.score is not None
         else "score: unavailable"),
        f"threshold: {result.threshold:.4f}",
    ]
    if result.failed_dimensions:
        lines.append("failed_dimensions: " + ", ".join(result.failed_dimensions))
    if result.missing:
        lines.append("missing: " + ", ".join(result.missing))
    return GateOutcome(code=0 if result.passed else 1, lines=tuple(lines))


@dataclass(frozen=True)
class GateAdapter:
    """一个评测面的门禁：需要哪些类别的输入、怎么执行。"""

    label: str
    needs_sample: bool
    run: Callable[[GateRequest], GateOutcome]


GATES: Dict[str, GateAdapter] = {
    "eval_arena": GateAdapter(label="arena", needs_sample=False, run=_run_arena_gate),
    "replay-trace": GateAdapter(label="replay_trace", needs_sample=False,
                                run=_run_replay_trace_gate),
    "rubric-review": GateAdapter(label="rubric", needs_sample=True,
                                 run=_run_rubric_gate),
}


def gate_for(gate_id: str) -> GateAdapter:
    try:
        return GATES[gate_id]
    except KeyError as exc:
        raise GateError(
            f"gate {gate_id!r} has no implementation; known: {sorted(GATES)}"
        ) from exc
