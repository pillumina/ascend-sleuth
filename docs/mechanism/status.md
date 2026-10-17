# 机制状态与代码入口

本文是全库唯一的机制状态表与代码入口表。`docs/mechanism/` 下各篇不再各留一份状态三表与「正文用词↔代码名」映射表，只留一行指向本文的指针；机制状态发生变化时改本文，不改各篇。

状态取值只有四种：**已落地**、**蓝图**（设计保留、触发条件出现才实现）、**已否决**（做过或考虑过，理由记在定义处）、**未建**（设计已写、落点为空或不存在）。一条机制只待在一个状态里。

写进本文的确认方式一律是符号名或可跑命令，不写行号：行号随文件改动失效，符号名与命令不会。数字一律现算，命令写在对应格子或本节末。

## 1 机制状态总表

| 机制 | 定义在哪 | 现状 | 确认方式 |
|---|---|---|---|
| 内容流程收尾的伴随演进 | [rsi-mechanism.md](rsi-mechanism.md) 「什么时候会发生演进」 | 已落地 | `ls skills/evolve-check/SKILL.md` |
| 全库体检轮 | [rsi-mechanism.md](rsi-mechanism.md) 「什么时候会发生演进」 | 已落地 | `ls skills/self-evolve/SKILL.md` |
| 每周批审 | [rsi-mechanism.md](rsi-mechanism.md) 「哪一步需要人，哪一步可以交给 agent」 | 已落地 | `ls skills/knowledge-groom/SKILL.md` |
| 改进项的过程档案与可复现预期 | [rsi-mechanism.md](rsi-mechanism.md) 「从触发到落地」 | 已落地 | `python3 scripts/verify_proposals.py --check` |
| 判定三态：符合、被证伪、无法判定；声明不可度量为合法退化 | [rsi-mechanism.md](rsi-mechanism.md) 「验证怎么闭环」 | 已落地 | `python3 scripts/ev_measure.py --audit` |
| 判定池的吸收分流与运行期重判 | [rsi-mechanism.md](rsi-mechanism.md) 「验证怎么闭环」 | 已落地 | `grep -n "absorption_rev" scripts/eval_arena.py` |
| 冻结对照样本按内容哈希固定 | [rsi-mechanism.md](rsi-mechanism.md) 「验证怎么闭环」 | 已落地 | `python3 scripts/holdout.py --check` |
| 观测账本进 CI | [rsi-mechanism.md](rsi-mechanism.md) 「验证怎么闭环」 | 已落地 | `python3 scripts/eval_scorecard.py --check` |
| 硬性检查配负例断言 | [rsi-mechanism.md](rsi-mechanism.md) 「验证怎么闭环」 | 已落地 | `grep -n "负例" scripts/rehearse_evolve_loop.py` |
| 体检器三态退出码：`--check` 时 0 全评过无越界、1 有违反、2 有判据未评；不带 `--check` 恒为 0 | [rsi-mechanism.md](rsi-mechanism.md) 「验证怎么闭环」 | 已落地 | `grep -n "exit_code = 2 if" scripts/evolution_health.py` |
| 选样的机械判据：流程与文档类前缀硬拒，弱信号默认不收 | [rsi-mechanism.md](rsi-mechanism.md) 「从触发到落地」 | 已落地 | `grep -n "include-weak" scripts/s2_calibration.py` |
| 积压量水位与超限停产 | [rsi-mechanism.md](rsi-mechanism.md) 「边界与失败模式」 | 已落地 | `python3 scripts/ev_proposal.py --waterline` |
| 候选水位上限判据 `backlog_over` | [orchestration.md](orchestration.md) 「token 预算与成本侧」 | 已落地 | `grep -n "backlog_over" proposals/gates.yaml` |
| 合入指针回写命令 `--mark-merged --from-prs` | [orchestration.md](orchestration.md) 「token 预算与成本侧」 | 已落地 | `grep -n "mark-merged" scripts/ev_proposal.py` |
| 成本的分子口径单一实现 `has_merge_pointer` | [orchestration.md](orchestration.md) 「token 预算与成本侧」 | 已落地 | `grep -n "has_merge_pointer" scripts/ev_proposal.py`；`--waterline` 与统计函数 `collect_stats` 同源 import（脚本 `scripts/ev_proposal.py` 引模块 `scripts/ev_board_data.py`：`grep -n "import ev_board_data" scripts/ev_proposal.py`；函数定义：`grep -n "def collect_stats" scripts/ev_board_data.py`） |
| 卡的成本侧字段 `actual_cost` | [orchestration.md](orchestration.md) 「token 预算与成本侧」 | 已落地 | `grep -n "actual_cost" docs/mechanism/pipeline.md` |
| 会话状态文件的落盘位置与 gitignore 规则 | [orchestration.md](orchestration.md) 「全局上下文页与执行编排规则」 | 已落地 | `grep -n "proposals/sessions" .gitignore` |
| 数字现算，不写进文档 | [rsi-mechanism.md](rsi-mechanism.md) 「从触发到落地」 | 已落地 | `python3 scripts/index_counts.py` |
| 记账号的生存范围 | [status.md](status.md) 「代码与文件入口」末段的记账号规则 | 已落地 | `python3 scripts/render_review_summary.py --scan docs/mechanism/rsi-mechanism.md` |
| 归因事件字段 `component` | [pipeline.md](pipeline.md) 「观测基座：归因事件写入 trace，报告按需聚合」 | 已落地 | `grep -n "attribution" skills/diagnose/references/diagnosis-trace.md` |
| 改进项状态机与 schema 校验 | [pipeline.md](pipeline.md) 「改进项的 schema 与状态机」 | 已落地 | `python3 scripts/verify_proposals.py --check` |
| 知识层分级 `authorization` 取 auto / review / dual | [pipeline.md](pipeline.md) 「L2 流程与 skill 层：从半闭环到全闭环」 | 已落地 | `grep -h "^authorization:" proposals/ideas/*.yaml \| sort \| uniq -c` |
| S2 单池校准集 | [pipeline.md](pipeline.md) 「观测基座：归因事件写入 trace，报告按需聚合」 | 已落地 | `ls eval/s2/vllm-ascend.yaml` |
| 改进项影响视图 `--impact` | [pipeline.md](pipeline.md) 「改进项的 schema 与状态机」 | 已落地 | `python3 scripts/ev_proposal.py --impact` |
| 元层判据与判决器 | [pipeline.md](pipeline.md) 「改进项的 schema 与状态机」 | 已落地 | `ls proposals/gates.yaml scripts/evolution_health.py` |
| reviews 与 experiments 独立目录 | [pipeline.md](pipeline.md) 「改进项的 schema 与状态机」 | 已落地 | `git ls-files proposals/reviews proposals/experiments` |
| 改进项卡 schema v3 | [execution.md](execution.md) 「改进项信息契约」 | 已落地 | `python3 scripts/verify_proposals.py --check` |
| `predicted_effect.measure` 强制 | [execution.md](execution.md) 「改进项信息契约」 | 已落地 | `grep -n "MEASURE_CUTOVER" scripts/verify_proposals.py`；不可度量时声明 `reason` 也是合法退化 |
| 评审把手 `--run` / `--audit` | [execution.md](execution.md) 「改进项信息契约」 | 已落地 | `python3 scripts/ev_measure.py --run` 打印判据命令、实测输出与退出码；`python3 scripts/ev_measure.py --audit` 盘全库缺口与存量豁免 |
| `target_component` 生效日闸门 | [execution.md](execution.md) 「改进项信息契约」 | 已落地 | `grep -n "TARGET_CUTOVER" scripts/verify_proposals.py` |
| `validation_record` 的 S2 结算 | [execution.md](execution.md) 「知识沉淀契约」 | 已落地 | `grep -n "3.5b" skills/knowledge-groom/SKILL.md` |
| 现场置信只由现场回报写入 | [execution.md](execution.md) 「知识沉淀契约」 | 已落地 | `ls scripts/settle_trace_feedback.py` |
| 四层指标与 timeline 结构校验 | [execution.md](execution.md) 「metrics 分层」 | 已落地 | `python3 scripts/verify_metrics.py --check` |
| 条目使用记录 | [diagnosis-observability.md](diagnosis-observability.md) 「记录与生成物」 | 已落地 | `python3 scripts/verify_entry_activity.py` |
| 工具分布 | [diagnosis-observability.md](diagnosis-observability.md) 「记录与生成物」 | 已落地 | `grep -n '"tool": ("calls"' scripts/entry_activity.py` |
| S2 feedback 结算 | [run.md](run.md) 「Issue 的三重角色与 S2 即时对照」 | 已落地 | `grep -n "validation_record" scripts/settle_s2_feedback.py` |
| 统一执行记录 schema 与脚本 | [run.md](run.md) 「统一执行记录」 | 已落地 | `python3 scripts/verify_exec_log.py` |
| 内容 skill 收尾接入 | [run.md](run.md) 「统一执行记录」 | 已落地 | `grep -rl "log_skill_exec" skills/` |
| exec-log 聚合进 timeline | [run.md](run.md) 「统一执行记录」 | 已落地 | `grep -n "evolve_check_runs" scripts/metrics_snapshot.py`；同处组装 `content_flow_runs` 与 `evolve_check_no_signal` |
| `supersedes` 与 `superseded_by` 字段 | [run.md](run.md) 「替换与回滚」 | 已落地 | `grep -n "supersedes:" examples/sample-idea.yaml` |
| 长期保护判据文件 | [run.md](run.md) 「停止条件汇总」 | 已落地 | `ls proposals/gates.yaml` |
| 面板先例 `dsh-plugins/ascend-panel` | [run.md](run.md) 「可视化」 | 已落地 | `ls dsh-plugins/ascend-panel` |
| 任务状态目录 | [run.md](run.md) 「落地工程形态」 | 已落地 | `ls -d proposals/tasks` |
| arena 设计文档与 `scripts/eval_arena.py` 的子命令（`--build-pool`、`--pool`、`--stats`、`--gate`、`--rc-check`、`--self-test`） | [eval-arena.md](eval-arena.md) 「工具」 | 已落地 | `python3 scripts/eval_arena.py --help` |
| arena 接受判据（配对检验、复用折减、三态判词） | [eval-arena.md](eval-arena.md) 「门控协议：接受与回滚」 | 已落地 | `grep -n "exact_mcnemar_ge\|ALPHA_DEFAULT\|reuse_index" scripts/eval_arena.py` |
| arena `--self-test` 进 CI | [eval-arena.md](eval-arena.md) 「工具」 | 已落地 | `grep -n "arena-gate-rule" .github/workflows/kb-checks.yml` |
| 复用判据 `pool_reuse_uncontrolled` | [eval-arena.md](eval-arena.md) 「门控协议：接受与回滚」 | 已落地 | `grep -n "pool_reuse_uncontrolled" proposals/gates.yaml` |
| arena 池按吸收状态分流 | [eval-arena.md](eval-arena.md) 「池构建」 | 已落地 | `grep -n "role.*regression\|absorbed" scripts/eval_arena.py` |
| 吸收状态在本池范围内运行期重判 | [eval-arena.md](eval-arena.md) 「评分口径」 | 已落地 | `python3 scripts/eval_arena.py --pool .s2-replay/arena/pool-val.yaml`；建池与聚合分别用 `--build-pool` 与 `--stats`，退出码与一致性向量检查用 `--rc-check`、`--self-test` |
| `held_out` 在 `--stats` 与 `--gate` 生效 | [eval-arena.md](eval-arena.md) 「评分口径」 | 已落地 | `grep -n "held_out" scripts/eval_arena.py` |
| 非诊断样本剔出命中率分母与配对 | [eval-arena.md](eval-arena.md) 「评分口径」 | 已落地 | `grep -n "non_diagnostic" scripts/eval_arena.py scripts/s2_replay.py` |
| 无回归范围写进账本（`no_regression_scope: arena-pool-only`） | [eval-arena.md](eval-arena.md) 「门控协议：接受与回滚」 | 已落地 | `grep -n "no_regression_scope" scripts/eval_arena.py` |
| 证据面留痕（`ground_truth: none` 剔出结论一致率分母，重放版本 `kb_rev` 进 `replay_revs` 并在跨版本时告警） | [eval-arena.md](eval-arena.md) 「评分口径」 | 已落地 | `grep -n "ground_truth\|replay_revs" scripts/eval_arena.py` |
| 交互型 replay 机制决议与本文档 | [ixn-replay.md](ixn-replay.md) 「解决什么问题与不解决什么」 | 已落地 | `grep -n 'ixn-replay.md' docs/_manifest.yaml` |
| 交互型 replay 评测工具 v1（含 `prepare` / `score` / `aggregate`） | [ixn-replay.md](ixn-replay.md) 「运行协议（agent 侧）与运行时数据归属」 | 已落地 | `python3 scripts/ixn_replay.py --help` |
| 交互型 replay 评测规格入库 | [ixn-replay.md](ixn-replay.md) 「样本与评测规格：选样、入库、分流」 | 已落地 | `ls eval/ixn-arena/` |
| 交互型 replay 运行时件排除 | [ixn-replay.md](ixn-replay.md) 「运行协议（agent 侧）与运行时数据归属」 | 已落地 | `grep -n "^\.ixn-replay/" .gitignore` |
| 交互型 replay 路线图条目 | [ixn-replay.md](ixn-replay.md) 「最小可执行模型」 | 已落地 | `grep -n "交互型 replay" docs/plan/roadmap.md` |
| 交互型 replay 首批出分记录 | [ixn-replay.md](ixn-replay.md) 「成本（试点实测量级）」末段的校准门槛 | 已落地 | 逐条读数以 `python3 scripts/ixn_replay.py --aggregate` 的输出为准；期号源文件见 `ls metrics/timeline.d/` |
| 交互面闸门接线（交互/追问面改动走 ixn 对口样本） | [ixn-replay.md](ixn-replay.md) 「成本（试点实测量级）」末段的校准门槛 | 已落地 | `grep -n 'ixn' docs/guide/eval.md` |
| arena 判定池的 expected 标注与基线回放 | [eval-arena.md](eval-arena.md) 「池构建」 | 蓝图 | 继续扩样本；基线已出、判定池逐条向量见 `python3 scripts/eval_arena.py --stats` |
| arena 门控端到端运转一次（真实 miss → 候选 → gate → 合入） | [eval-arena.md](eval-arena.md) 「门控协议：接受与回滚」 | 蓝图 | baseline 可用后；见 [pipeline.md](pipeline.md) 「现状与落地节奏（闸门衔接，不按日历）」 |
| 交互型 replay 判定池的 expected 标注与基线 | [ixn-replay.md](ixn-replay.md) 的「首次出分与门槛」 | 蓝图 | 首次出分记录与逐条读数以 `python3 scripts/ixn_replay.py --aggregate` 的输出为准 |
| 现场反馈通道出数据 | [rsi-mechanism.md](rsi-mechanism.md) 「已知缺口」 | 蓝图 | 真实工程师跑完一次诊断、回报修复结果，捕获计数不再为 0；见 [rsi-mechanism.md](rsi-mechanism.md) 的「已知缺口」 |
| 体检器判据的负例断言 | [rsi-mechanism.md](rsi-mechanism.md) 「已知缺口」 | 蓝图 | 给体检器的每一条判据配一个故意改坏的负例 |
| 外部验证的第一条独立记录 | [rsi-mechanism.md](rsi-mechanism.md) 「已知缺口」 | 蓝图 | 出现一条既不来自该知识的来源、也不被该知识正文引用的验证 |
| 对照样本池扩容 | [rsi-mechanism.md](rsi-mechanism.md) 「已知缺口」 | 蓝图 | 新增未吸收样本入场、逐条向量齐备 |
| 触发信号表覆盖真实信号族 | [rsi-mechanism.md](rsi-mechanism.md) 「已知缺口」 | 蓝图 | 维护者决定扩表覆盖真实信号族，或收窄行为、把表外信号归一 |
| 判据阈值的实测重校 | [rsi-mechanism.md](rsi-mechanism.md) 「已知缺口」 | 蓝图 | 有实测数据后重校越界线 |
| 未覆盖评测面的判据 | [rsi-mechanism.md](rsi-mechanism.md) 「已知缺口」 | 蓝图 | 为性能类数值断言、平台键控分支、修复正确性、严重性行为补判据 |
| 判据越界的自动读取 | [rsi-mechanism.md](rsi-mechanism.md) 「哪一步需要人，哪一步可以交给 agent」 | 蓝图 | 把体检挂到已有的收尾动作上，让判据越界自己成为入口 |
| 观察窗超时降级态 `unconfirmed_valid` / `unconfirmed` | [pipeline.md](pipeline.md) 「现状与落地节奏（闸门衔接，不按日历）」 | 蓝图 | S1 断供真实持续两期以上；此前用「标存疑加提醒人」 |
| 候选过期态 `stale` | [pipeline.md](pipeline.md) 「现状与落地节奏（闸门衔接，不按日历）」 | 蓝图 | 候选停留超过八周（参数待校准）且从未被采纳；此前用 inbox 式标红 |
| 策略记忆独立文件 `strategy-memory.yaml` | [pipeline.md](pipeline.md) 「现状与落地节奏（闸门衔接，不按日历）」 | 蓝图 | 季度自评跑通至少一轮后；此前结构级教训并入 session context |
| 稳态降频 `steady` | [pipeline.md](pipeline.md) 「现状与落地节奏（闸门衔接，不按日历）」 | 蓝图 | 某个范围真实收敛，连续两轮满足四个条件；此前用停止条件里的「收敛」 |
| 运行模式细化（任务级批提交跨轮） | [pipeline.md](pipeline.md) 「现状与落地节奏（闸门衔接，不按日历）」 | 蓝图 | 用户真实要求「跨多轮攒批」后 |
| 成功模式提取信号 | [pipeline.md](pipeline.md) 「现状与落地节奏（闸门衔接，不按日历）」 | 蓝图 | 常态运行中首次出现可复述的成功模式（无信号即止，不预设轮次） |
| 可信自动升格 trusted auto-promotion | [pipeline.md](pipeline.md) 「现状与落地节奏（闸门衔接，不按日历）」 | 蓝图 | 随 v2 池入口：trace 达到门槛数、完成前几项、指标趋势连续两季可解读；判据见 [roadmap.md](../plan/roadmap.md) |
| 多 agent 载体（DSH Agent Teams 一类） | [pipeline.md](pipeline.md) 「现状与落地节奏（闸门衔接，不按日历）」 | 蓝图 | 出现真实的多 agent 并行场景 |
| 改进项影响视图的首个 rejected 或回滚簇 | [pipeline.md](pipeline.md) 「现状与落地节奏（闸门衔接，不按日历）」 | 蓝图 | 出现首个真实 L2 rejected 或回滚簇 |
| S2 池管理扩展 | [run.md](run.md) 「Issue 的三重角色与 S2 即时对照」 | 蓝图 | issue-ingest 的 `processed` 记录扩展时 |
| 长期保护判据接入（回滚率与抽审发现率） | [run.md](run.md) 「停止条件汇总」 | 蓝图 | 回滚率与抽审发现率接入 `proposals/gates.yaml` 的判据 |
| 可视化面板与 HTML 报告 | [run.md](run.md) 「可视化」 | 蓝图 | 任务层跑通一轮以上 |
| `supersedes` 回滚语义激活 | [run.md](run.md) 「替换与回滚」 | 蓝图 | 出现首个新改进项替代旧实现的场景 |
| 长期任务层跨轮运行 | [run.md](run.md) 「长期任务层」 | 蓝图 | 落地顺序的步骤 1 到 2b 有真实数据后手动试点一轮 |
| `predicted_value` / `first_hit` / `expected_window` 三个字段 | [execution.md](execution.md) 「沉淀效果度量」 | 蓝图 | 出现第一次真实沉淀批次，且 S1 反馈恢复 |
| follow-up 观察窗常态化 | [execution.md](execution.md) 「合入后跟踪验证链路」 | 蓝图 | golden 回放或 S2 校准集可用 |
| 回滚率、采纳率等机制健康指标进 timeline | [execution.md](execution.md) 「metrics 分层」 | 蓝图 | 自演进执行流程试点满一轮 |
| agent 供给清单固化为执行 checklist | [execution.md](execution.md) 「agent 决策点的信息供给」 | 蓝图 | 落地顺序的步骤 1 到 3 有真实执行记录 |
| 冲突检测的机械检查 | [orchestration.md](orchestration.md) 「全局上下文页与执行编排规则」 | 蓝图 | `affected_paths` 进卡 schema 后；此前靠读卡判断改动范围的交集 |
| 会话协议与预算试点 | [orchestration.md](orchestration.md) 「全局上下文页与执行编排规则」 | 蓝图 | 排在 golden 验证门与 S2 校准集之后；见 [pipeline.md](pipeline.md) 「现状与落地节奏（闸门衔接，不按日历）」 |
| arena test 分离 | [eval-arena.md](eval-arena.md) 「池构建」 | 蓝图 | 池子撑得起两半；这是 arena 池的口径 |
| S2 单池校准集的 selection 与 test 分离 | [run.md](run.md) 「Issue 的三重角色与 S2 即时对照」 | 蓝图 | 判定池中未被本系统沉淀过的样本条数够支撑判定；与上一行的 arena test 分离是两处口径（S2 单池与 arena 池），各自独立 |
| arena 归因层与交互层入台 | [eval-arena.md](eval-arena.md) 「池构建」 | 蓝图 | 两层各自有可用的评测集 |
| arena 分数进 timeline | [eval-arena.md](eval-arena.md) 「评分口径」 | 蓝图 | 样本规模达标（带分母） |
| arena 判定池扩容 | [eval-arena.md](eval-arena.md) 「池构建」 | 蓝图 | 规模或数据触发 |
| 交互型 replay 评分阈值与筛选标准固化 | [ixn-replay.md](ixn-replay.md) 「成本（试点实测量级）」末段的校准门槛 | 蓝图 | `held_out` 样本达到门槛条数后按实测校准；见 [roadmap.md](../plan/roadmap.md) |
| 交互面分数进 timeline | [ixn-replay.md](ixn-replay.md) 「评分口径：双层指标加防过早」 | 蓝图 | `held_out` 达到门槛条数且带分母 |
| 归因型 replay 工具化（用 PR 引用作标注） | [ixn-replay.md](ixn-replay.md) 「最小可执行模型」 | 蓝图 | 出现归因评测需求，且样本可追溯到 PR 引用 |
| 合成变体生成器（case 派生扰动加 seed） | [ixn-replay.md](ixn-replay.md) 「样本与评测规格：选样、入库、分流」 | 蓝图 | [roadmap.md](../plan/roadmap.md) 的 fixture 自动生成事项落地后 |
| arena 外部验证卡占比下限 1/3 | [eval-arena.md](eval-arena.md) 「门控协议：接受与回滚」 | 已否决 | 实测不可达，且原判据把自己的动作文案排除出分子却留在分母里；改为 `external_verification_stall` |
| 全库体检的自动发起 | [rsi-mechanism.md](rsi-mechanism.md) 「哪一步需要人，哪一步可以交给 agent」（「发起全库体检」一行） | 已否决 | 系统不知道业务上现在该关心什么；要重新放开先要有不依赖人的触发源 |
| 由 agent 单独决定结构性改动 | [rsi-mechanism.md](rsi-mechanism.md) 「哪一步需要人，哪一步可以交给 agent」（「结构性改动」一行）；[rsi-mechanism.md](rsi-mechanism.md) 「明确不做（防过度设计）」 | 已否决 | 骨架、路由、新 skill 立项的影响面无法局部验证，走两人双签 |
| 系统改自己的评分口径与指标定义 | [rsi-mechanism.md](rsi-mechanism.md) 「哪一步需要人，哪一步可以交给 agent」（「指标口径与评分定义」一行）；[rsi-mechanism.md](rsi-mechanism.md) 「明确不做（防过度设计）」 | 已否决 | 自己改评分标准，验证就不再是外部约束 |
| 退休从没被选中的罕见条目 | [rsi-mechanism.md](rsi-mechanism.md) 「五类演化动作与对应的护栏」（「退休与复活」一行） | 已否决 | 过早退休会删掉正确的罕见知识 |
| 旧的 `estimated_cost` 字段 | [orchestration.md](orchestration.md) 「token 预算与成本侧」 | 已否决 | 在没有 token 记账的情况下它不产生实际约束，已由 `actual_cost` 取代 |
| 用 token 换质量 | [orchestration.md](orchestration.md) 「token 预算与成本侧」 | 已否决 | 把成本转移到没有预算科目的地方，违反原则九 |
| 靠无限扩池消化候选 | [orchestration.md](orchestration.md) 「token 预算与成本侧」 | 已否决 | 积压率高说明产卡速度超过消化能力，动作是下调信号权重而不是扩池 |
| 把 `steady` 当永久关闭 | [orchestration.md](orchestration.md) 「目标函数与停止准则」 | 已否决 | 稳态是数据触发的暂停，新信号或新降级态出现即自动解除 |
| 让 agent 改评分与指标定义 | [orchestration.md](orchestration.md) 「自我指涉治理」 | 已否决 | 这等于被评的一方改写评分标准，是红线 |
| 交互型 replay 全池选样 | [ixn-replay.md](ixn-replay.md) 「明确不做（防过度设计）」 | 已否决 | 多数 issue 属详尽型或归因型，追问测不出差别，样本进去也不产生信号 |
| 把交互型 replay 评测规格放在临时检出 | [ixn-replay.md](ixn-replay.md) 「明确不做（防过度设计）」 | 已否决 | `git worktree remove` 会连规格一起删除，已实际发生一次、需要重建 |
| 把归因型 issue 并入交互型 replay 的样本池 | [ixn-replay.md](ixn-replay.md) 的「外部参考」 | 已否决 | 决定性信息来自源码调查而不是追问，评追问测不出差别 |
| 把评测反馈送回知识侧 | [ixn-replay.md](ixn-replay.md) 的「外部参考」 | 已否决 | 等于从评测中学习，验证集被自己扰动 |
| execution.md 契约层的整条否决 | [execution.md](execution.md) 「明确不做（防过度设计）」 | 已否决 | 无。这份契约至今没有整条否决的内容；被压缩掉的三个字段按触发条件缓行，属蓝图，不算否决 |
| run.md 已落地区块之外的「已否决」 | [run.md](run.md) 「明确不做（防过度设计）」 | 已否决 | 已否决项集中在 [run.md](run.md) 的「明确不做（防过度设计）」，不在这里重复；它们不进蓝图表，触发条件出现也不做 |

## 2 未建与空转

本节列出两类：落点为空目录或文件不存在的条目（未建），以及已标蓝图但按当前读数触发条件明显未到的条目（空转）。读数用可跑命令现算，不抄具体数字进文档。

| 机制 | 落点 | 当前读数 | 依据 |
|---|---|---|---|
| 策略记忆独立文件 | `proposals/strategy-memory.yaml` | 不存在；`ls proposals/strategy-memory.yaml` | [pipeline.md](pipeline.md) 「现状与落地节奏（闸门衔接，不按日历）」、[orchestration.md](orchestration.md) 「全局上下文页与执行编排规则」列为蓝图 |
| 冲突检测的机械检查 | 卡 schema 的 `affected_paths` 字段 | 字段不在 schema 里；`grep -n "affected_paths" proposals/ideas/*.yaml` | [orchestration.md](orchestration.md) 「全局上下文页与执行编排规则」列为蓝图 |
| 会话协议与预算试点的落点 | `proposals/sessions/` | 目录内只有 `.gitkeep`；`ls -A proposals/sessions` | [orchestration.md](orchestration.md) 「全局上下文页与执行编排规则」列为蓝图 |
| 长期任务层试点 | `proposals/tasks/` | 目录内只有 `.gitkeep`；`ls -A proposals/tasks` | [run.md](run.md) 「落地工程形态：四层装配」列为蓝图 |
| reviews 独立目录的内容 | `proposals/reviews/` | 目录内只有 `.gitkeep`；`ls -A proposals/reviews` | [pipeline.md](pipeline.md) 「改进项的 schema 与状态机」列为已落地（目录与放行规则），内容仍空 |
| experiments 独立目录的内容 | `proposals/experiments/` | 目录内只有 `.gitkeep`；`ls -A proposals/experiments` | [pipeline.md](pipeline.md) 「改进项的 schema 与状态机」列为已落地（目录与放行规则），内容仍空 |
| 自演进面板插件 | `dsh-plugins/self-evolve-panel/` | 不存在；`ls -d dsh-plugins/self-evolve-panel` | [run.md](run.md) 「落地工程形态：四层装配」列为蓝图 |
| 回滚率与抽审发现率接入判据 | `proposals/gates.yaml` 的判据项 | 判据里没有这两项；`grep -n "回滚\|抽审" proposals/gates.yaml` | [run.md](run.md) 「落地工程形态：四层装配」列为蓝图 |
| 外部验证的第一条独立记录 | 知识条目的外部验证记录 | 需要外部验证类记录的条目数现算；`grep -rl "external_verification" knowledge/` | [rsi-mechanism.md](rsi-mechanism.md) 「已知缺口」列为蓝图 |
| 现场反馈通道出数据 | 条目使用记录里的现场解决计数 | 捕获计数现算；`python3 scripts/settle_trace_feedback.py --help` | [rsi-mechanism.md](rsi-mechanism.md) 「已知缺口」列为蓝图 |

## 3 其他文档落地项的归属阶段

落地阶段的定义、各阶段的内容与入口闸门在 [pipeline.md](pipeline.md) 第 11 节，落地的唯一权威总纲是那一节；[execution.md](execution.md) 第 10 节与 [run.md](run.md) 第 9 节是各自维度的细化，不是平行计划，只回答本层内部先做什么。本表把它们的各项归到 pipeline 的阶段：阶段用 [pipeline.md](pipeline.md) 第 11 节那张表的「内容」列指代（那张表里每个阶段还带一个字母代号，代号只在 pipeline.md 裸用），本表不重复它的代号。「第一批落地」指让机制第一次真实跑起来的最小组件集，即第 1 节机制状态总表里标「已落地」的那些行。

| 其他文档的落地项 | 归属的阶段（内容见 [pipeline.md](pipeline.md) 第 11 节） |
|---|---|
| [execution.md](execution.md) 第 10 节：改进项 schema v3 落模板 | 归因事件字段落地（已完成：schema 加 `verify_proposals.py`） |
| [execution.md](execution.md) 第 10 节：沉淀效果字段（predicted_value / first_hit） | 归因事件按需聚合跑通（归因事件与首条 L2 卡之后，随首批沉淀） |
| [execution.md](execution.md) 第 10 节：follow-up 观察窗常态化 | golden 验证门常态化（依赖 fixture replay 与 S2 的即时判定） |
| [execution.md](execution.md) 第 10 节：回滚率等机制指标进 timeline | 自演进执行流程试点满 1 轮后 |
| [run.md](run.md) 第 9 节：统一执行记录 | 第一批已完成（schema、脚本、四个内容 skill 收尾接入：issue-ingest / to-reference / to-postmortem / knowledge-groom，evolve-check 自身也落记录）。收敛边界：只覆盖内容 skill 收尾，diagnose 走 trace 不重复落（见 [run.md](run.md) 第 4 节） |
| [run.md](run.md) 第 9 节：supersede 字段与回滚语义 | 自演进执行流程试点（出现首个替代场景时，schema 已含字段） |
| [run.md](run.md) 第 9 节：长期任务层试点 | 自演进执行流程试点（试点即含轮间调度） |
| [run.md](run.md) 第 9 节：可视化 | auto 级扩权与参数校准常态化之后，或常设（任务层跑通 ≥1 轮） |

## 4 代码与文件入口

正文用白话。改脚本、查数据文件之前，用这张表把正文用词换成代码与文件里的名字。同一概念在多篇里有多种写法时都保留，用 `/` 或分号并列。

| 正文里说 | 代码与文件里的名字 |
|---|---|
| 改进项、改进项卡、卡 | `proposals/ideas/` 下的卡 |
| 收尾检查、内容流程收尾、收尾评估 | `evolve-check`、`/skill:evolve-check` |
| 全库体检轮 | `self-evolve`、`/skill:self-evolve` |
| 每周批审 | `knowledge-groom`、`/skill:knowledge-groom` |
| 判据、体检器 | `proposals/gates.yaml`、`scripts/evolution_health.py`、`metrics/gates.yaml`、`scripts/metrics_health.py` |
| 积压量、候选水位读数 | 水位读数，`scripts/ev_proposal.py --waterline` |
| 候选水位判据 | `proposals/gates.yaml` 的 `backlog_over`（`grep -n "backlog_over" proposals/gates.yaml`） |
| 回写合入指针、批提交的合入指针回写 | `scripts/ev_proposal.py --mark-merged`、`scripts/ev_proposal.py --mark-merged --from-prs`；一个 PR 装一批卡 |
| 分子口径 | `scripts/ev_proposal.py` 的 `has_merge_pointer`（`grep -n "has_merge_pointer" scripts/ev_proposal.py`） |
| 回归样本、golden | golden fixture，`eval/golden/` 下的 fixture、`scripts/replay_golden.py` |
| 冻结的对照样本 | holdout，`eval/holdout.yaml` |
| 对照样本集、校准集 | arena 池，`scripts/eval_arena.py --stats/--gate`；`eval/s2/vllm-ascend.yaml`、`eval/s2/vllm-ascend-cross.yaml` |
| 用历史问题重跑、S2 单发先例 | S2 issue-replay，`scripts/s2_replay.py` |
| 预期可复现 | `predicted_effect.measure`，`scripts/ev_measure.py` |
| 诊断记录 | trace，`traces/<session>.yaml`（运行时件） |
| 执行记录 | `metrics/skill-exec-log.yaml`（运行时件，同一克隆共享） |
| 观测账本 | `eval/scorecard.yaml`，`scripts/eval_scorecard.py --check` |
| 现场反馈回报 | 反馈通道 S1，条目使用记录（`metrics/entry-activity.d/`） |
| 内容与外部结论对照 | 反馈通道 S2，`case.validation_record` |
| 影响面、触及面、轴 | 从卡文本派生，判据输出里的 `by_surface`；三者指同一件事，正文用影响面，体检器输出用触及面，更早的文档里写轴 |
| 闭环演练 | `scripts/rehearse_evolve_loop.py` |
| 先筛摘要再读正文 | 两阶段加载，Tier 2 索引分片 |
| 归因事件 | trace 顶层的 `attribution` 事件，`scripts/component_tally.py` 按需聚合 |
| 可信自动升格 | roadmap 的 trusted auto-promotion 事项 |
| 五类演化动作 | [rsi-mechanism.md](rsi-mechanism.md) 的置信度校准、知识注入、误诊归因、结构演化、退休与复活 |
| 卡 schema 必填字段 | `scripts/verify_proposals.py` 的 `REQUIRED`（`grep -n "^REQUIRED = \[" scripts/verify_proposals.py`） |
| `target_component` 生效日闸门 | `TARGET_CUTOVER`（`grep -n TARGET_CUTOVER scripts/verify_proposals.py`） |
| `predicted_effect.measure` 强制与存量豁免 | `MEASURE_CUTOVER`（`grep -n MEASURE_CUTOVER scripts/verify_proposals.py`） |
| 评审把手 | `scripts/ev_measure.py`（`--run` / `--audit`） |
| S2 结算 `validation_record` | `scripts/settle_s2_feedback.py`、groom 步骤 3.5b（`grep -n "3.5b" skills/knowledge-groom/SKILL.md`） |
| S1 结算现场解决计数 | `scripts/settle_trace_feedback.py`（只写记录，不改案例） |
| `verification` 档位定义 | `skills/to-postmortem/SKILL.md` 的 verification 段（`grep -n "verification" skills/to-postmortem/SKILL.md`） |
| case 完整字段清单 | [case-schema.md](../spec/case-schema.md)；`ref_knowledge` 见其「source_ref」与「ref_knowledge」两节 |
| `ref_knowledge` 的 role 校验 | `scripts/verify_references.py` |
| issue 源的价值启发式 | `scripts/issue_filter.py` |
| 四层指标口径与 timeline 校验 | [metrics.md](../guide/metrics.md)、`scripts/verify_metrics.py`、`scripts/trace_metrics.py`、`scripts/index_counts.py` |
| 效果差与回滚率记录 | `metrics/timeline.yaml` |
| 证据原文 | `traces/evidence/` |
| 会话状态 | `proposals/sessions/<SESSION-ID>.yaml`（运行时件，`grep -n "proposals/sessions" .gitignore`） |
| 会话级快照 | `proposals/sessions/<SESSION-ID>.context.yaml`（运行时件，gitignore） |
| 策略记忆 | `proposals/strategy-memory.yaml`（资产，进 git；见 §2） |
| 成本侧字段 | `predicted_effect.measure`、`actual_cost`（[pipeline.md](pipeline.md) 的「改进项的 schema 与状态机」） |
| 知识库规模、知识库条数 | `python3 scripts/index_counts.py` |
| 长期任务 | `proposals/tasks/<TASK-ID>.yaml` |
| 卡状态 | `in_experiment`、`validated`、`rejected`、`superseded`；任务层另有 `active`、`paused`、`stopped` |
| 观察窗判定 | `rolled_back`，作为追加 decision 记录留痕 |
| 运行模式 | `hands-off`、`default` |
| 运行模式字段 | `approval_policy` |
| 授权分级 | `auto`、`review`、`dual`，见 [pipeline.md](pipeline.md) 的「运行模式、批提交与授权升级门槛」 |
| 自指隔离样本 | `self_consistent` |
| 轮间调度载体 | DSH Agent Teams（实验性），见 [pipeline.md](pipeline.md) 的「角色与多 agent 编排」 |
| 四层视图 | 面板视图，数据源为 `proposals/`、`metrics/timeline.yaml` 与 `traces/` |
| 长期任务层与统一执行记录的关键脚本 | `scripts/log_skill_exec.py` 写一条执行记录；`scripts/verify_exec_log.py` 校验 seq 唯一与字段；`scripts/tail_exec_log.py` 读执行记录（尾巴、`--summary` 聚合、`--json`）；`scripts/exec_log_path.py` 把执行记录解析到主检出，写侧持 flock；`scripts/metrics_snapshot.py` 组装每期快照并把 exec-log 聚合写进 `metrics/timeline.d/<期号>.yaml`；`scripts/build_timeline.py` 重建 `metrics/timeline.yaml`；`scripts/settle_s2_feedback.py` S2 反馈结算到 `case.validation_record`；`scripts/s2_calibration.py` 生成 S2 校准集 `eval/s2/vllm-ascend.yaml`；`scripts/s2_replay.py` 用历史 issue 重跑诊断；`scripts/verify_proposals.py` 校验 `proposals/ideas/` 的卡结构 |
| eval 台、arena | `scripts/eval_arena.py` |
| 判定池 | `.s2-replay/arena/pool-val.yaml`（`role: judgment`） |
| 回归池 | `.s2-replay/arena/pool-val-absorbed.yaml`（`role: regression`） |
| 已吸收样本 | 答案已进知识库的样本，判据是 `knowledge/` 下存在 `VLLM-ASC-<issue>.yaml` |
| 吸收状态指纹 | `absorption_rev`、`absorption_recheck` |
| 池规模闸门、触发线 | 判定池可评样本数 ≥ `4 + Σ_{k<K} b*(k)` |
| 判定阈值折减 | `α_eff = α/(k+1)`、`ALPHA_DEFAULT`、`reuse_index()`（`grep -n "def reuse_index" scripts/eval_arena.py`） |
| 三态判词 | `accept`、`weak_accept`、`reject`，`decide()` |
| 影响账本 | `.s2-replay/arena/impact.yaml` |
| 池内容哈希 | `pool_hash` |
| 逐条判决向量 | stats 的 `issues`，`vectors()` |
| 重放版本 | `kb_rev`、`replay_revs`、`scripts/kb_rev.py` |
| 结算 | `scripts/settle_s2_feedback.py` |
| 收样判据 | `scripts/s2_calibration.py`、`NON_DIAGNOSTIC_PREFIXES` |
| arena 里 `--gate` 与结论一致率所用的字段 | `core_match` 与 `rc`，即 `rc = r.get("rc_match", r.get("root_cause_ok"))`（`grep -n "root_cause_ok" scripts/eval_arena.py`） |
| 评测工具（交互型 replay） | `scripts/ixn_replay.py`，子命令 `cmd_prepare`、`cmd_score`、`cmd_aggregate`、`main`（`grep -n "^def cmd_\|^def main" scripts/ixn_replay.py`） |
| 对照答案与分期输入（交互型 replay） | `eval/ixn-arena/<issue>/gold.yaml`、`stage-k.md`；目录规范见 [ixn-replay.md](ixn-replay.md) 的「存放：规格入库，正文与结果留在本地」 |
| 样本清单（交互型 replay） | `eval/ixn-arena/registry.yaml` |
| 本地正文与运行件（交互型 replay） | `.ixn-replay/<issue>/`；排除规则见 `grep -n "^\.ixn-replay/" .gitignore` |
| 单发 S2 先例 | `scripts/s2_replay.py`、`eval/s2/`；S2 口径见 [pipeline.md](pipeline.md) 的「评分源分级：反馈数据不只有工程师回报」 |
| 交互面改动门禁 | [eval.md](../guide/eval.md) 的交互面对口样本一节（`grep -n 'ixn' docs/guide/eval.md`） |

## 5 相邻文档分工

| 文档 | 管什么 |
|---|---|
| 本文（status.md） | 全库唯一的机制状态总表、未建与空转、代码与文件入口对照、相邻文档分工；各篇机制文档只留一行指向本文的指针，状态变化改本文 |
| [rsi-mechanism.md](rsi-mechanism.md) | 自演进元机制的技术入口与机制地图；对象层（case 与 reference）的闭环与五类演化动作；日常执行看它 |
| [pipeline.md](pipeline.md) | 机制总览：三层闭环、分级授权、卡 schema 与状态机、自演进执行流程、落地节奏；唯一权威落地总纲 |
| [execution.md](execution.md) | 单张改进项卡的执行契约：记录什么、follow-up 怎么验证、沉淀效果怎么度量；pipeline 的执行级规范 |
| [orchestration.md](orchestration.md) | 单轮会话的边界、目标函数与停止条件、token 预算、自我指涉治理 |
| [run.md](run.md) | 把一轮轮会话装配成长期持续运行：长期任务、issue 评测循环、执行记录、可视化 |
| [eval-arena.md](eval-arena.md) | 元层评测台：分层与池构建、门控协议、配对检验与复用折减、影响账本 |
| [ixn-replay.md](ixn-replay.md) | 交互层，兄弟台；本台管交互面，arena 管检索/路由层 |
| S2 单池评测（[pipeline.md](pipeline.md) 的「评分源分级：反馈数据不只有工程师回报」） | arena 是 S2 的门控化形态。S2 单池评测照旧用于日常，arena 是演进时的门，改动时才跑 |
| 路由错例演进（从 trace 提取路由错例，产出 triage 修订建议）与 fixture 回放半自动化 | arena 提供它们的自动评分数据源（[roadmap.md](../plan/roadmap.md) 里的两个可演进事项） |
| [evolution-user-guide.md](../guide/evolution-user-guide.md) | 面向使用者的指令、报告与干预语言 |
| [design-principles.md](../spec/design-principles.md) | 原则一至原则十一的出处 |
| [design-theory.md](../spec/design-theory.md) | 理论推导，含注意力预算与常数接受实测重校 |
| [git-workflow.md](../guide/git-workflow.md) | 多 agent 并行的隔离与合流规则 |
| [metrics.md](../guide/metrics.md) | 指标定义与指标口径纪律 |
| [roadmap.md](../plan/roadmap.md) | 交互型 replay 评测的路线状态与门槛规则 |
| `skills/<name>/SKILL.md` | 流程行为。流程必须自包含，不依赖 docs/ |
| [eval.md](../guide/eval.md) | 改测评检查、跑回归 |
| [writing-norms.md](../spec/writing-norms.md) | 写给人看或给人审的文本 |
| [rollout-assessment.md](../plan/rollout-assessment.md) | 排下一步工作、评估能否推广 |
| `docs/adr/` | 查当初为什么这样选 |

内部记账号只在各自的计划文档里使用。机制文档、PR 说明、改进项正文要引用就写中文含义，规则见 [glossary.yaml](../glossary.yaml) 的生存范围字段。

改机制之前先读 [design-principles.md](../spec/design-principles.md) 与 [eval.md](../guide/eval.md)：前者是条文的来源，后者写清了改哪里测哪里的规矩。
