"""evolve 命令行：策略、样本队列、判定与周读数。

编排在这里，规则在核心模块。核心模块不打印、不读文件；CLI 负责路径、
终端输出与退出码：

- ``0``：命令成功（判定结果本身是数据，accept/insufficient/reject/unknown 都算成功）
- ``1``：样本/策略校验不过、状态转换非法、文件格式错
- ``2``：命令行输入错误（judge 的 b/c/n 非法、缺文件等）

按命令组拆到同包子模块（``policy`` / ``sample`` / ``stage`` / ...），
各组只提供 ``register(subparsers)`` 与 handler；``build_parser`` 按原顺序注册。
共用 helper 在 ``common``，这里以原私有名字 re-export，外部可见名字不变。
"""

import argparse
import sys
from typing import Optional, Sequence

from ..adapters.issues import ingest_issues
from ..cli_usage import register as register_usage_dimensions
from ..errors import EvolveError
from .benchmark import cmd_benchmark, register as register_benchmark
from .brief import cmd_brief, register as register_brief
from .candidate import (cmd_candidate_apply, cmd_candidate_diff,
                        cmd_candidate_rollback, cmd_candidate_validate,
                        register as register_candidate)
from .common import (JUDGE_METHODS, PROG, CliError,
                     decide_from_args as _decide_from_args,
                     evolve_base as _evolve_base,
                     finish_judge as _finish_judge,
                     guard_holdout as _guard_holdout,
                     json_object_arg as _json_object,
                     load_plan as _load_plan,
                     policy_for as _policy_for,
                     print_decision as _print_decision,
                     read_json_value as _read_json,
                     record_conclusion as _record_conclusion,
                     root_of as _root,
                     sample_store as _store,
                     where_pairs as _where_pairs,
                     yaml_or_json_object as _yaml_or_json_object)
from .experiment import (cmd_experiment_flow, cmd_experiment_gate,
                         cmd_experiment_list, cmd_experiment_propose,
                         cmd_experiment_record, cmd_experiment_records,
                         cmd_experiment_request, cmd_experiment_resolve,
                         cmd_experiment_search, cmd_experiment_show,
                         register as register_experiment)
from .health import cmd_health, register as register_health
from .judge import (cmd_judge, cmd_judge_calibration, cmd_judge_stats,
                    register as register_judge)
from .pilot import (cmd_pilot_checkpoint, cmd_pilot_collect, cmd_pilot_decide,
                    cmd_pilot_prepare, register as register_pilot)
from .policy import (cmd_policy_autonomy, cmd_policy_check, cmd_policy_show,
                     register as register_policy)
from .readback import cmd_readback, register as register_readback
from .replay import cmd_replay_collect, cmd_replay_prepare, register as register_replay
from .rsi import (cmd_rsi_attribute, cmd_rsi_plan, cmd_rsi_select,
                  cmd_rsi_status, register as register_rsi)
from .run import cmd_run, register as register_run
from .sample import (cmd_sample_absorb, cmd_sample_check,
                     cmd_sample_draw_test, cmd_sample_export_core,
                     cmd_sample_import_ixn, cmd_sample_import_pilot,
                     cmd_sample_import_s2, cmd_sample_ingest_issues,
                     cmd_sample_list, cmd_sample_new, cmd_sample_promote,
                     cmd_sample_retire, cmd_sample_review,
                     cmd_sample_set_answer, cmd_sample_set_purpose,
                     cmd_sample_status, register as register_sample)
from .stage import (cmd_stage_judge, cmd_stage_plan, cmd_stage_report,
                    cmd_stage_run, register as register_stage)
from .store import (cmd_store_history, cmd_store_migrate, cmd_store_verify,
                    register as register_store)
from .traces import cmd_traces_status, cmd_traces_sync, register as register_traces


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="自演进评估循环：策略、样本队列、判定与读数（v1）。",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    register_usage_dimensions(sub)
    register_policy(sub)
    register_sample(sub)
    register_stage(sub)
    register_benchmark(sub)
    register_readback(sub)
    register_judge(sub)
    register_replay(sub)
    register_store(sub)
    register_experiment(sub)
    register_run(sub)
    register_rsi(sub)
    register_pilot(sub)
    register_candidate(sub)
    register_traces(sub)
    register_health(sub)
    register_brief(sub)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except EvolveError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
