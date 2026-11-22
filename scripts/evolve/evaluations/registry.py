"""评测面静态注册表。"implemented" 只表示当前是否有端到端 scorer/gate，不表示有真实数据。"""

from typing import Dict

from .base import EvalProfile

EVAL_PROFILES: Dict[str, EvalProfile] = {
    "arena": EvalProfile(
        id="arena", label="诊断回放配对门禁",
        object_types=("diagnosis",), gate="eval_arena", implemented=True,
    ),
    "rubric": EvalProfile(
        id="rubric", label="人工 rubric 双标",
        object_types=("case", "reference"), gate="rubric-review", implemented=True,
    ),
    "replay_trace": EvalProfile(
        id="replay_trace", label="回放工具调用与 trace",
        object_types=("diagnosis", "trace"), gate="replay-trace", implemented=True,
    ),
    "subagent_judge": EvalProfile(
        id="subagent_judge", label="子 agent 对照评审",
        object_types=("diagnosis",), gate="subagent-judge", implemented=False,
    ),
    "end_to_end": EvalProfile(
        id="end_to_end", label="端到端回放与回归",
        object_types=("diagnosis", "case", "reference", "trace"),
        gate="end-to-end-regression", implemented=False,
    ),
}


def get_eval_profile(name: str) -> EvalProfile:
    try:
        return EVAL_PROFILES[name].validate()
    except KeyError as exc:
        raise ValueError(
            f"unknown eval profile {name!r}; expected one of {sorted(EVAL_PROFILES)}"
        ) from exc


def eval_profile_ids():
    return sorted(EVAL_PROFILES)
