# 机制状态与代码入口

本文是全库唯一的机制状态表与代码入口表。各篇机制文档不再各留一份状态表与「正文用词 ↔ 代码名」映射表，只留一行指向本文的指针；机制状态变化时改本文，不改各篇。

状态取值只有四种：**已落地**、**蓝图**（设计保留、触发条件出现才实现）、**已否决**（做过或考虑过，理由记在定义处）、**未建**（设计已写、实现位置为空或不存在）。一条机制只待在一个状态里。

确认方式一律写符号名或可跑命令，不写行号：行号随文件改动失效，符号名与命令不会。数字一律现算，命令写在对应格子或本节末。

## 1 机制状态总表

| 机制 | 定义在哪 | 现状 | 确认方式 |
|---|---|---|---|
| 内容流程收尾的伴随演进 | [operations.md](operations.md) 3.1 | 已落地 | `ls skills/evolve-check/SKILL.md` |
| 部署级演进模式 `evolution.role` | [operations.md](operations.md) 3.1 | 已落地 | `python3 scripts/evolve_mode.py` |
| 全库体检轮 | [operations.md](operations.md) 3.1 | 已落地 | `ls skills/self-evolve/SKILL.md` |
| 每周批审 | [operations.md](operations.md) 3.3 | 已落地 | `ls skills/knowledge-groom/SKILL.md` |
| 信号台账（下游部署的收尾交接） | [signals/README.md](../../proposals/signals/README.md) | 已落地 | `python3 scripts/evolve_signals.py list` |
| 演进记录入口 `evolve_intake` 与信号生命周期 | [evolve-check/SKILL.md](../../skills/evolve-check/SKILL.md) 第 3 步 | 已落地 | `python3 scripts/evolve_intake.py record --help` |
| 改进项的过程档案、状态机与卡 schema 校验 | [records.md](records.md) 3.1 | 已落地 | `python3 scripts/verify_proposals.py --check` |
| 知识层分级 `authorization` 取 auto / review / dual | [records.md](records.md) 3.1、[operations.md](operations.md) 3.2 | 已落地 | `grep -h "^authorization:" proposals/ideas/*.yaml \| sort \| uniq -c` |
| `predicted_effect.measure` 强制 | [records.md](records.md) 3.1 | 已落地 | `grep -n "MEASURE_CUTOVER" scripts/verify_proposals.py` |
| `target_component` 生效日检查 | [records.md](records.md) 3.1 | 已落地 | `grep -n "TARGET_CUTOVER" scripts/verify_proposals.py` |
| 评审把手与判定三态（符合、被证伪、无法判定；声明不可度量是合法退化） | [records.md](records.md) 3.1 | 已落地 | `python3 scripts/ev_measure.py --run`；`--audit` 盘全库缺口与存量豁免 |
| 改进项影响视图 `--impact` 与替换链字段 | [records.md](records.md) 3.1 | 已落地 | `python3 scripts/ev_proposal.py --impact`；`grep -n "supersedes:" examples/sample-idea.yaml` |
| 卡的成本侧字段 `actual_cost` | [records.md](records.md) 3.1 | 已落地 | `grep -n "actual_cost" docs/mechanism/records.md` |
| 积压量水位、上限判据与超限停产 | [operations.md](operations.md) 3.2 | 已落地 | `python3 scripts/ev_proposal.py --waterline`；`grep -n "backlog_over" proposals/gates.yaml` |
| 合入指针回写命令 `--mark-merged --from-prs` | [operations.md](operations.md) 3.2 | 已落地 | `grep -n "mark-merged" scripts/ev_proposal.py` |
| 成本的分子统计单一实现 `has_merge_pointer` | [operations.md](operations.md) 3.2 | 已落地 | `grep -n "has_merge_pointer" scripts/ev_proposal.py` |
| 会话状态文件的保存位置与 gitignore 规则 | [operations.md](operations.md) 3.2 | 已落地 | `grep -n "proposals/sessions" .gitignore` |
| 长期保护判据、元层判决器与四层指标校验 | [operations.md](operations.md) 3.2、3.3 | 已落地 | `ls proposals/gates.yaml scripts/evolution_health.py`；`python3 scripts/verify_metrics.py --check` |
| 体检器三态退出码：`--check` 时 0 全评过无越界、1 有违反、2 有判据未评；不带 `--check` 恒为 0 | [evaluation.md](evaluation.md) 3.5 | 已落地 | `grep -n "exit_code = 2 if" scripts/evolution_health.py` |
| 记录不陈旧（观测记录进 CI）与硬性检查的负例断言 | [evaluation.md](evaluation.md) 3.5 | 已落地 | `python3 scripts/eval_scorecard.py --check`；`grep -n "负例" scripts/rehearse_evolve_loop.py` |
| 冻结对照样本按内容哈希固定 | [evaluation.md](evaluation.md) 5.1 | 已落地 | `python3 scripts/holdout.py --check` |
| issue 回放校准集、判定池吸收分流与运行期重判 | [evaluation.md](evaluation.md) 3.7 | 已落地 | `ls eval/s2/vllm-ascend.yaml`；`grep -n "absorption_rev" scripts/eval_arena.py` |
| arena 设计文档与 `scripts/eval_arena.py` 的子命令 | [evaluation.md](evaluation.md) 3.7 | 已落地 | `python3 scripts/eval_arena.py --help` |
| arena 接受判据（配对检验、复用折减、三态结论） | [evaluation.md](evaluation.md) 3.5、3.7 | 已落地 | `grep -n "exact_mcnemar_ge\|ALPHA_DEFAULT\|reuse_index" scripts/eval_arena.py` |
| arena `--self-test` 进 CI | [evaluation.md](evaluation.md) 3.7 | 已落地 | `grep -n "arena-gate-rule" .github/workflows/kb-checks.yml` |
| 复用判据 `pool_reuse_uncontrolled` | [evaluation.md](evaluation.md) 3.7 | 已落地 | `grep -n "pool_reuse_uncontrolled" proposals/gates.yaml` |
| arena 池按吸收状态分流 | [evaluation.md](evaluation.md) 3.7 | 已落地 | `grep -n "role.*regression\|absorbed" scripts/eval_arena.py` |
| 吸收状态在本池范围内运行期重判 | [evaluation.md](evaluation.md) 3.7 | 已落地 | `python3 scripts/eval_arena.py --pool .s2-replay/arena/pool-val.yaml` |
| `held_out` 在 `--stats` 与 `--gate` 生效 | [evaluation.md](evaluation.md) 3.7 | 已落地 | `grep -n "held_out" scripts/eval_arena.py` |
| 非诊断样本剔出命中率分母与配对 | [evaluation.md](evaluation.md) 3.7 | 已落地 | `grep -n "non_diagnostic" scripts/eval_arena.py scripts/s2_replay.py` |
| 无回归范围写进影响记录（`arena-pool-only`） | [evaluation.md](evaluation.md) 3.7 | 已落地 | `grep -n "no_regression_scope" scripts/eval_arena.py` |
| 证据面记录（`ground_truth: none` 剔出分母，`kb_rev` 进 `replay_revs`） | [evaluation.md](evaluation.md) 3.7 | 已落地 | `grep -n "ground_truth\|replay_revs" scripts/eval_arena.py` |
| 选样的机械判据：流程与文档类前缀硬拒，弱信号默认不收 | [evaluation.md](evaluation.md) 3.7 | 已落地 | `grep -n "include-weak" scripts/s2_calibration.py` |
| 统一执行记录：schema、脚本、收尾接入与聚合 | [records.md](records.md) 3.7 | 已落地 | `python3 scripts/verify_exec_log.py`；`grep -rl "log_skill_exec" skills/`；`grep -n "evolve_check_runs" scripts/metrics_snapshot.py` |
| issue 回放结算 `validation_record` | [operations.md](operations.md) 3.4 | 已落地 | `grep -n "validation_record" scripts/settle_s2_feedback.py` |
| 现场置信只由现场回报写入 | [operations.md](operations.md) 3.4 | 已落地 | `ls scripts/settle_trace_feedback.py` |
| 条目使用记录 | [diagnosis-observability.md](diagnosis-observability.md) 3.3 | 已落地 | `python3 scripts/verify_entry_activity.py` |
| 工具分布 | [diagnosis-observability.md](diagnosis-observability.md) 3.3 | 已落地 | `grep -n '"tool": ("calls"' scripts/entry_activity.py` |
| 诊断详情的四层时间线与追加式修订 | [diagnosis-observability.md](diagnosis-observability.md) 3.1 | 已落地 | `python3 scripts/verify_trace_status.py --all` |
| 诊断续接的漂移检查与读侧版本坐标记录 | [diagnosis-trace.md](../../skills/diagnose/references/diagnosis-trace.md) 的 `kb_rev` 与「顶层知识库同步字段」 | 已落地 | `python3 scripts/kb_drift.py --session <id>`；`python3 scripts/kb_sync.py --show` |
| 归因事件字段 `component` | [diagnosis-trace.md](../../skills/diagnose/references/diagnosis-trace.md) | 已落地 | `grep -n "attribution" skills/diagnose/references/diagnosis-trace.md` |
| groom 终态决定的收尾：记录回写 + 草稿出队 | [agent-groom.md](agent-groom.md) 3.7 | 已落地 | `python3 scripts/groom_close_draft.py --help` |
| 面板先例 `dsh-plugins/ascend-panel` | [operations.md](operations.md) 3.6 | 已落地 | `ls dsh-plugins/ascend-panel` |
| 任务状态目录 | [operations.md](operations.md) 3.6 | 已落地 | `ls -d proposals/tasks` |
| 交互型 replay 机制、工具 v1、规格入库与路线图条目 | [ixn-replay.md](ixn-replay.md) 2、5 | 已落地 | `python3 scripts/ixn_replay.py --help`；`ls eval/ixn-arena/` |
| 交互面验收接线（交互与追问面改动走对口样本） | [ixn-replay.md](ixn-replay.md) 8 | 已落地 | `grep -n 'ixn' docs/guide/eval.md` |
| arena 判定池的 expected 标注与基线回放 | [evaluation.md](evaluation.md) 5.2 | 蓝图 | 继续扩样本；基线已出、逐条向量见 `python3 scripts/eval_arena.py --stats` |
| arena 端到端运转一次（真实 miss → 候选 → 结论 → 合入） | [evaluation.md](evaluation.md) 5.2 | 蓝图 | baseline 可用之后 |
| arena test 分离 | [evaluation.md](evaluation.md) 5.2 | 蓝图 | 池子撑得起两半 |
| issue 回放校准集的 selection 与 test 分离 | [evaluation.md](evaluation.md) 5.2 | 蓝图 | 判定池中未被本系统沉淀过的样本条数够支撑判定 |
| arena 归因层与交互层入台 | [evaluation.md](evaluation.md) 5.2 | 蓝图 | 两层各自有可用的评测集 |
| arena 分数进 timeline | [evaluation.md](evaluation.md) 5.2 | 蓝图 | 样本规模达标（带分母） |
| arena 判定池扩容 | [evaluation.md](evaluation.md) 5.2 | 蓝图 | 规模或数据触发 |
| 评估策略与判定器 | [evaluation.md](evaluation.md) 3.5 | 已落地 | `python3 scripts/evolve.py policy check`；`python3 scripts/evolve.py judge --help` |
| A0-A5 自动档位解析（按 target_component；A3 无 auto-merge 降 A2） | [evaluation.md](evaluation.md) 3.8 | 已落地 | `python3 scripts/evolve.py policy autonomy --component docs.non_normative` |
| judge 双标校准（一致率与 κ 门槛） | [evaluation.md](evaluation.md) 3.5 | 已落地 | `python3 scripts/evolve.py judge-calibration --help` |
| 样本、执行、结论的 v1 契约与样本队列 | [records.md](records.md) 3.2、3.3 | 已落地 | `python3 scripts/evolve.py sample --help`；`python3 scripts/evolve.py brief` |
| tooling 自演进：目标、可改区、候选补丁、评测与门禁 | [evaluation.md](evaluation.md) 3.10.1 | 已落地 | `python3 scripts/evolve.py tool-usage --help`；`grep -n "tooling.source_fetch" scripts/evolve/regions.py` |
| 判定容量（`required_b` 与池样本数） | [evaluation.md](evaluation.md) 3.9 | 已落地 | `grep -n "required_exclusive_wins" scripts/evolve/decision.py`；`python3 scripts/evolve.py brief` |
| pilot 记录闭环：Run/Conclusion 与版本坐标 | [records.md](records.md) 3.2、3.3 | 已落地 | `grep -n "def decide" scripts/evolve/pilot.py` |
| pilot 成本预算与 futility 早停 | [evaluation.md](evaluation.md) 3.5 | 已落地 | `python3 scripts/evolve.py pilot checkpoint --help` |
| baseline trace 复用（只跑 candidate） | [evaluation.md](evaluation.md) 3.5 | 已落地 | `python3 scripts/evolve.py pilot prepare --help` |
| 确定性 benchmark（工具/检索类） | [evaluation.md](evaluation.md) 3.5 | 已落地 | `python3 scripts/evolve.py benchmark --help` |
| regression 预算配置（常规 6 / 全量 30） | [evaluation.md](evaluation.md) 3.4 | 已落地 | `python3 scripts/evolve.py stage plan --stage regression --limit 1` |
| test / regression 通用 stage runner（plan / run / report） | [evaluation.md](evaluation.md) 3.4 | 已落地 | `python3 scripts/evolve.py stage --help` |
| stage agent adapter（dsh / claude / echo / command） | [evaluation.md](evaluation.md) 3.4 | 已落地 | `python3 scripts/agent_adapter.py --help` |
| stage judge（外部评分 + meta 来源 + 校准） | [evaluation.md](evaluation.md) 3.4 | 已落地 | `python3 scripts/evolve.py stage judge --help` |
| test 门禁（field accept / candidate / 完整证据 / 样本封存） | [evaluation.md](evaluation.md) 3.4 | 已落地 | `python3 scripts/evolve.py stage report --help` |
| judge 元数据与成本入 Conclusion | [evaluation.md](evaluation.md) 3.4 | 已落地 | `grep -n "judge" scripts/evolve/pilot.py` |
| regression 子集（`--where key=value`） | [evaluation.md](evaluation.md) 3.4 | 已落地 | `python3 scripts/evolve.py stage plan --help` |
| 按卡回读 + measure | [evaluation.md](evaluation.md) 3.5 | 已落地 | `python3 scripts/evolve.py readback --help` |
| 样本队列操作进行中状态 | [evaluation.md](evaluation.md) 3.4 | 已落地 | `grep -n "sampleQueueBusy" dsh-plugins/ev-panel/panel-client.js` |
| 模型与 token 采集：trace header + DSH 会话记录 | [records.md](records.md) 3.2 | 已落地 | `python3 scripts/trace_begin.py --print-only`；`grep -n "read_session" scripts/evolve/pilot.py` |
| pilot 样本注册进本地队列 | [evaluation.md](evaluation.md) 3.9 | 已落地 | `python3 scripts/evolve.py sample import-pilot --help` |
| 已闭环 case 回流样本（trace / postmortem，完整性与跨集查重） | [evaluation.md](evaluation.md) 3.4 | 已落地 | `python3 scripts/evolve.py sample new --from trace --help`；`python3 scripts/evolve.py sample status --help` |
| 样本队列复核动作（通过 / 退回 / 升 core，失败在队列内显示） | [evaluation.md](evaluation.md) 3.4 | 已落地 | `grep -n "ev-sample-action" dsh-plugins/ev-panel/panel-host.js` |
| 记录端口层 | [records.md](records.md) 3.6 | 已落地 | `grep -n "class .*Protocol" scripts/evolve/ports.py` |
| 适配器层与旧脚本薄壳 | [records.md](records.md) 3.6 | 已落地 | `ls scripts/evolve/adapters`；`python3 scripts/evolve.py replay --help`；`python3 scripts/evolve.py sample import-s2 --help` |
| core 样本与 `eval/core/samples/`（test + regression） | [evaluation.md](evaluation.md) 3.4 | 已落地 | `ls eval/core/samples`；`python3 scripts/evolve.py sample export-core --help` |
| 观察窗超时降级态 `unconfirmed_valid` / `unconfirmed` | [operations.md](operations.md) 5.2 | 蓝图 | 现场反馈断供真实持续两期以上；此前用「标存疑加提醒人」 |
| 候选过期态 `stale` | [records.md](records.md) 5.2 | 蓝图 | 候选停留超过八周且从未被采纳；此前用 inbox 式标红 |
| 策略记忆独立文件 `strategy-memory.yaml` | [operations.md](operations.md) 5.2 | 蓝图 | 季度自评跑通至少一轮后 |
| 稳态降频 `steady` 与任务级批提交跨轮 | [operations.md](operations.md) 5.2 | 蓝图 | 某个范围真实收敛；用户真实要求「跨多轮攒批」后 |
| 多 agent 载体（DSH Agent Teams 一类） | [operations.md](operations.md) 5.2 | 蓝图 | 出现真实的多 agent 并行场景 |
| 冲突检测的机械检查 | [operations.md](operations.md) 5.2 | 蓝图 | `affected_paths` 进卡 schema 后 |
| 会话协议与预算试点、长期任务层跨轮运行 | [operations.md](operations.md) 5.2 | 蓝图 | 前者排在 golden 验证与 issue 回放校准集之后；后者有真实数据后手动试点一轮 |
| 可视化面板与 HTML 报告 | [operations.md](operations.md) 5.2 | 蓝图 | 任务层跑通一轮以上 |
| 长期保护判据接入（回滚率与抽审发现率） | [operations.md](operations.md) 5.2 | 蓝图 | 两项读数接入 `proposals/gates.yaml` |
| 成功模式提取信号 | [operations.md](operations.md) 5.2 | 蓝图 | 常态运行中首次出现可复述的成功模式 |
| 可信自动升格 trusted auto-promotion | [roadmap.md](../plan/roadmap.md) | 蓝图 | 随 v2 池入口：记录达到门槛数、前几项完成、指标趋势连续两季可解读 |
| issue 回放池管理扩展 | [operations.md](operations.md) 3.4 | 蓝图 | issue-ingest 的 `processed` 记录扩展时 |
| `predicted_value` / `first_hit` / `expected_window` 三个字段 | [records.md](records.md) 5.3 | 已否决 | 整套依赖现场反馈，而该通道当前没有数据；两条现成通道已覆盖效果度量 |
| follow-up 观察窗常态化 | [records.md](records.md) 5.2 | 蓝图 | golden 回放或 issue 回放校准集可用 |
| 回滚率、采纳率等机制健康指标进 timeline | [operations.md](operations.md) 5.2 | 蓝图 | 自演进执行流程试点满一轮 |
| agent 供给清单固化为执行清单 | [records.md](records.md) 5.2 | 蓝图 | 执行记录积累一批之后 |
| arena 外部验证卡占比下限 1/3 | [evaluation.md](evaluation.md) 5.3 | 已否决 | 实测不可达，且原判据把动作文案排除出分子却留在分母里；改为 `external_verification_stall` |
| 全库体检的自动发起 | [rsi-mechanism.md](rsi-mechanism.md) 3.4 | 已否决 | 系统不知道业务上现在该关心什么；重新放开要先有不依赖人的触发源 |
| 由 agent 单独决定结构性改动 | [rsi-mechanism.md](rsi-mechanism.md) 3.4 | 已否决 | 影响面无法局部验证，走两人双签 |
| 系统改自己的评分规则与指标定义 | [rsi-mechanism.md](rsi-mechanism.md) 3.4 | 已否决 | 自己改评分标准，验证就不再是外部约束 |
| 退休从没被选中的罕见条目 | [rsi-mechanism.md](rsi-mechanism.md) 3.2 | 已否决 | 过早退休会删掉正确的罕见知识 |
| 旧的 `estimated_cost` 字段 | [records.md](records.md) 5.3 | 已否决 | 没有 token 记账时它不产生实际约束，已由 `actual_cost` 取代 |
| 用 token 换质量 | [operations.md](operations.md) 5.3 | 已否决 | 把成本转移到没有预算科目的地方，违反原则九 |
| 靠无限扩池消化候选 | [operations.md](operations.md) 5.3 | 已否决 | 积压率高说明产卡速度超过消化能力，动作是下调信号权重 |
| 把 `steady` 当永久关闭 | [operations.md](operations.md) 5.2 | 已否决 | 稳态是数据触发的暂停，新信号或新存疑卡出现即解除 |
| 交互型 replay 全池选样 | [ixn-replay.md](ixn-replay.md) 9 | 已否决 | 多数 issue 属详尽型或归因型，追问测不出差别 |
| 把交互型 replay 评测规格放在临时检出 | [ixn-replay.md](ixn-replay.md) 5.3 | 已否决 | `git worktree remove` 会连规格一起删除，已实际发生一次 |
| 把归因型 issue 并入交互型 replay 的样本池 | [ixn-replay.md](ixn-replay.md) 12.4 | 已否决 | 决定性信息来自源码调查而不是追问 |
| 把评测反馈送回知识侧 | [ixn-replay.md](ixn-replay.md) 12.4 | 已否决 | 等于从评测中学习，验证集被自己扰动 |

## 2 未建与空转（含已知缺口）

本节列两类：实现位置为空目录或文件不存在的条目（未建），以及已标蓝图但按当前读数触发条件明显未到的条目（空转）。读数用可跑命令现算，不抄具体数字进文档。

| 机制 | 实现位置 | 当前读数 | 依据 |
|---|---|---|---|
| 策略记忆独立文件 | `proposals/strategy-memory.yaml` | 不存在；`ls proposals/strategy-memory.yaml` | [operations.md](operations.md) 5.2 |
| 冲突检测的机械检查 | 卡 schema 的 `affected_paths` 字段 | 字段不在 schema 里；`grep -n "affected_paths" proposals/ideas/*.yaml` | [operations.md](operations.md) 5.2 |
| 会话协议、长期任务、季度自评与实验记录 | `proposals/sessions/`、`tasks/`、`reviews/`、`experiments/` | 都只有 `.gitkeep`；`ls -A proposals/sessions proposals/tasks proposals/reviews proposals/experiments` | [operations.md](operations.md) 5.2、[records.md](records.md) 3.5 |
| 自演进面板插件 | `dsh-plugins/self-evolve-panel/` | 不存在；`ls -d dsh-plugins/self-evolve-panel` | [operations.md](operations.md) 5.2 |
| 回滚率与抽审发现率接入判据 | `proposals/gates.yaml` 的判据项 | 判据里没有这两项；`grep -n "回滚\|抽审" proposals/gates.yaml` | [operations.md](operations.md) 5.2 |
| 外部验证的第一条独立记录 | 知识条目的外部验证记录 | 需要外部验证类记录的条目数现算；`grep -rl "external_verification" knowledge/` | 缺口第 3 条 |
| 现场反馈通道出数据 | 条目使用记录里的现场解决计数 | 捕获计数现算；`python3 scripts/settle_trace_feedback.py --help` | 缺口第 1 条 |

七个已知缺口，按危害排序：

1. 知识层的输入是空的。现场反馈回报通道没有数据，命中率、误诊率、校准一律标成不可解读。补它的动作不在机制侧，在让真实工程师跑完一次诊断、回报结果。
2. 体检器的判据没有被证明会报错。演练对冻结样本、卡规则、执行记录都有负例断言，体检器的几条判据一条都没有。
3. 外部验证还没有产出第一条独立记录。通道与选样纪律都已就绪，但至今没有一条来自另一个现场的独立验证。
4. 对照样本池的规模不够做判定。池子小到配对检验够不到判定线，实测结论只能落在证据不足；扩容的代价与顺序见 [evaluation.md](evaluation.md) 3.4。
5. 触发信号表与真实信号族脱钩。多数改进项落不进设计表；扩表覆盖还是收窄行为，等维护者决定。
6. 判据阈值都是没校准过的估计，全部通过只证明没有越过猜出来的线；部分评测面（性能类数值断言、平台键控分支、修复正确性、严重性行为）没有自动判定。

## 3 代码与文件入口

正文用白话。改脚本、查数据文件之前，用这张表把正文用词换成代码与文件里的名字。

| 正文里说 | 代码与文件里的名字 |
|---|---|
| 改进项、改进项卡、卡；收尾检查、全库体检轮与每周批审 | `proposals/ideas/` 下的卡；`evolve-check`、`self-evolve`、`knowledge-groom`（各自的 `/skill:<name>`） |
| 判据、体检器 | `proposals/gates.yaml`、`scripts/evolution_health.py`、`metrics/gates.yaml`、`scripts/metrics_health.py` |
| 候选水位读数 | `scripts/ev_proposal.py --waterline` |
| 回写合入指针 | `scripts/ev_proposal.py --mark-merged`、`--mark-merged --from-prs` |
| 分子统计 | `scripts/ev_proposal.py` 的 `has_merge_pointer` |
| 回归样本、冻结对照样本、校准集与用历史问题重跑 | `eval/golden/` 与 `scripts/replay_golden.py`；`eval/holdout.yaml` 与 `scripts/holdout.py --check`；`eval/s2/`、`scripts/eval_arena.py --stats/--gate`、`scripts/s2_replay.py` |
| 预期可复现 | `predicted_effect.measure`、`scripts/ev_measure.py` |
| 诊断记录、执行记录与观测记录 | `traces/<session>.yaml`；`metrics/skill-exec-log.yaml`（运行时件）；`eval/scorecard.yaml` 与 `scripts/eval_scorecard.py --check` |
| 现场反馈回报、内容与外部结论对照 | 反馈通道：现场反馈与 issue 回放：条目使用记录（`metrics/entry-activity.d/`）、`case.validation_record` |
| 影响面、触及面 | 从卡文本派生，判据输出里的 `by_surface`；正文用影响面 |
| 演练 | `scripts/rehearse_evolve_loop.py` |
| 先筛摘要再读正文 | 两阶段加载，Tier 2 索引分片 |
| 归因事件 | trace 顶层的 `attribution` 事件，`scripts/component_tally.py` 按需聚合 |
| 五类演化动作 | [rsi-mechanism.md](rsi-mechanism.md) 3.2 的排序分数校准、知识注入、误诊归因、结构演化、退休与复活 |
| 卡 schema 必填字段与两道生效日检查 | `scripts/verify_proposals.py` 的 `REQUIRED`、`TARGET_CUTOVER`、`MEASURE_CUTOVER` |
| 评审把手 | `scripts/ev_measure.py`（`--run` / `--audit`） |
| issue 回放与现场反馈的结算 | `scripts/settle_s2_feedback.py`（groom 步骤 3.5b）；`scripts/settle_trace_feedback.py` |
| `verification` 档位定义 | `skills/to-postmortem/SKILL.md` 的 verification 段 |
| case 字段清单与 `ref_knowledge` 的 role 校验 | [case-schema.md](../spec/case-schema.md)；`scripts/verify_references.py` |
| issue 源的价值启发式 | `scripts/issue_filter.py` |
| 四层指标与 timeline 校验 | [metrics.md](../guide/metrics.md)、`scripts/verify_metrics.py`、`scripts/trace_metrics.py`、`scripts/index_counts.py` |
| 效果差与回滚率记录 | `metrics/timeline.yaml` |
| 证据原文 | `traces/evidence/` |
| 会话状态、会话级快照与策略记忆 | `proposals/sessions/`（运行时件）；`proposals/strategy-memory.yaml`（资产，见 §2） |
| 成本侧字段 | `predicted_effect.measure`、`actual_cost` |
| 知识库规模 | `python3 scripts/index_counts.py` |
| 长期任务 | `proposals/tasks/<TASK-ID>.yaml` |
| 卡状态、观察窗判定与运行模式 | `in_experiment`、`validated`、`rejected`、`superseded`；`rolled_back` 作为追加判断记录；`hands-off`、`default`（字段 `approval_policy`）；任务层另有 `active`、`paused`、`stopped` |
| 授权分级 | `auto`、`review`、`dual` |
| 自指隔离样本 | `self_consistent` |
| 四层视图 | 面板视图，数据源为 `proposals/`、`metrics/timeline.yaml` 与 `traces/` |
| 长期任务层与执行记录的关键脚本 | `scripts/log_skill_exec.py`、`verify_exec_log.py`、`tail_exec_log.py`、`exec_log_path.py`、`metrics_snapshot.py`、`build_timeline.py`、`settle_s2_feedback.py`、`s2_calibration.py`、`s2_replay.py`、`verify_proposals.py` |
| 评估台、arena | `scripts/eval_arena.py` |
| 样本队列、判定与读数（v1） | `scripts/evolve.py`（`policy` / `sample` / `judge` / `brief`）、`scripts/evolve/`、`sleuth.config.yaml 的 evolution.policy` |
| 结论与执行记录（v1） | `.s2-replay/evolve/conclusions.jsonl`、`runs.jsonl` |
| 判定池 | `.s2-replay/arena/pool-val.yaml`（`role: judgment`） |
| 回归池 | `.s2-replay/arena/pool-val-absorbed.yaml`（`role: regression`） |
| 已吸收样本 | 答案已进知识库的样本，判据是 `knowledge/` 下存在 `VLLM-ASC-<issue>.yaml` |
| 吸收状态指纹 | `absorption_rev`、`absorption_recheck` |
| 池规模条件、触发线 | 判定池可评样本数 ≥ `4 + Σ_{k<K} b*(k)` |
| 判定阈值折减 | `α_eff = α/(k+1)`、`ALPHA_DEFAULT`、`reuse_index()` |
| 三态结论 | `accept`、`weak_accept`、`reject`、`decide()` |
| 影响记录 | `.s2-replay/arena/impact.yaml` |
| 池内容哈希 | `pool_hash` |
| 逐条判决向量 | stats 的 `issues`、`vectors()` |
| 重放版本 | `kb_rev`、`replay_revs`、`scripts/kb_rev.py` |
| 收样判据 | `scripts/s2_calibration.py`、`NON_DIAGNOSTIC_PREFIXES` |
| 交互型 replay 工具 | `scripts/ixn_replay.py`（`cmd_prepare`、`cmd_score`、`cmd_aggregate`） |
| 交互型 replay 对照答案与分期输入 | `eval/ixn-arena/<issue>/gold.yaml`、`stage-k.md` |
| 交互型 replay 样本清单 | `eval/ixn-arena/registry.yaml` |
| 交互回放本地正文与运行件 | `.ixn-replay/<issue>/` |
| 交互面改动检查 | [eval.md](../guide/eval.md) 的交互面对口样本一节 |

## 4 相邻文档分工

八篇机制文档各自管什么、什么时候读，见 [rsi-mechanism.md](rsi-mechanism.md) 第 4 节。本表只列相邻面：

| 文档 | 管什么 |
|---|---|
| 本文 | 全库唯一的机制状态表、未建与空转、代码与文件入口 |
| [evolution-user-guide.md](../guide/evolution-user-guide.md) | 面向使用者的指令、报告与干预语言 |
| [design-principles.md](../spec/design-principles.md) | 原则一至原则十一的出处 |
| [design-theory.md](../spec/design-theory.md) | 理论推导，含注意力预算与常数接受实测重校 |
| [git-workflow.md](../guide/git-workflow.md) | 多 agent 并行的隔离与合流规则 |
| [metrics.md](../guide/metrics.md) | 指标定义与统计规则 |
| [roadmap.md](../plan/roadmap.md) | 演进计划与各事项的条件 |
| `skills/<name>/SKILL.md` | 流程行为。流程自包含，不依赖 `docs/` |
| [writing-norms.md](../spec/writing-norms.md)、[terminology.md](../spec/terminology.md) | 人读文本的行文规则与内部术语 |
| [rollout-assessment.md](../plan/rollout-assessment.md) | 排下一步工作、评估能否推广 |
| `docs/adr/` | 查当初为什么这样选 |

内部记账号只在各自的计划文档里使用。机制文档、PR 说明、卡正文要引用就写中文含义，规则见 [glossary.yaml](../glossary.yaml) 的生存范围字段。

改机制之前先读 [design-principles.md](../spec/design-principles.md) 与 [eval.md](../guide/eval.md)：前者是条文的来源，后者写清了改哪里测哪里的规矩。
