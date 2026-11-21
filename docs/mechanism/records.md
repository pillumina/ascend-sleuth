# 记录与数据契约

记录分四类：signal、RSI 实验（样本 / 执行 / 结论）、高风险 EV 授权、版本坐标。普通确定性修复与内容改动不强制四件套；只有行为质量实验需要完整 RSI 记录。

读者是要改字段或 schema、写记录、查某条数据进不进 git 的人。前置是 [rsi-mechanism.md](rsi-mechanism.md)（机制入口）与 [evaluation.md](evaluation.md)（样本怎么选、结论怎么判）。只跑流程、不碰数据的人不必读本文。

范围：signal、RSI 实验、高风险 EV 授权、接口、存储归属、版本坐标、代码入口。不含评估集与判定的规则（[evaluation.md](evaluation.md)）、运行节奏（[operations.md](operations.md)）、诊断侧字段（[diagnosis-observability.md](diagnosis-observability.md)）。

本文不写会过期的数字。卡片张数与状态分布用 `python3 scripts/ev_measure.py --audit` 现算；库内条数用 `python3 scripts/index_counts.py`。

## 1 解决什么问题

行为质量改动要能事后复核，缺的是三样东西：一个 RSI proposal 说不清改哪、现状是什么、怎么算改完；一次实验没有能复现的版本坐标；一条结论没有可追加的判断记录。

signal 补观察来源；RSI proposal 补执行前契约；样本补评估输入；执行与结论补判定数据与理由；版本补复现坐标。高风险 EV 卡只补授权与历史，不是普通改动的默认记录。

明确不解决：结论怎么判（在 [evaluation.md](evaluation.md)）、什么节奏跑（在 [operations.md](operations.md)）、现场有效性（只认工程师回报）。

## 2 最小可执行模型

按改动性质写：

- 确定性 bug：最小回归测试 + PR；不产生 EV 卡或 RSI 记录。
- 内容缺口：内容记录（case / reference / ingest 的来源与验证）。
- 行为质量：signal → RSI proposal → 一个或多个样本 → 执行 → 结论。
- 高风险授权：轻量 EV 卡，记录授权、回滚与历史；不替代 RSI 或 PR。

存储只分两种归属：资产进 git，运行时件留本地。判据是「这份数据是否逐轮变化」：proposal 契约、结论与授权是资产；逐轮进度、token 记录、池文件是运行时件。

## 3 完整机制

### 3.1 高风险 EV 授权卡

卡只用于高风险授权或历史记录：写清改哪、风险、谁授权、怎么回滚；不承担普通行为改动的 proposal/experiment 职责。它不含 git 协作状态，批提交、提 PR、合入是流程层的事。

```yaml
id: EV-2026-XXX                 # 真实卡号由 ev_proposal --new 分配
layer: L2                        # L1 知识内容 / L2 流程与 skill / L3 工作流与编排
title: triage 分支 vllm-ascend 启动参数族执行错率 0.6 → 修订该分支
status: in_experiment            # in_experiment / validated / rejected / superseded
authorization: review            # auto / review / dual：这次改动合入要不要人签字
supersedes: []                   # 本卡替代的旧卡；superseded_by 指被哪张卡替代
created_at: 2026-09-01
source_signals: [{signal: component_error, evidence: "组件 triage 的 execution_error 归因 6 条", trajectory: ["traces/*.yaml#attribution"]}]
hypothesis: 修订该分支的症状匹配逻辑后，执行错率降至 0.3 以下
predicted_effect: {metric: 组件执行错率, from: 0.6, to: "<0.3", measure: {command: python3 scripts/eval_arena.py --gate, expect_exit: 0}}
validation: {method: golden_replay, success_criteria: golden 无回归且归因簇不再增长, rollback: revert}
actual_cost: null                # validated 后必填 {tokens, source}
decisions: []                    # 只追加：proposal / action / eval / decision 四类
```

字段分两组。一组是执行契约，回答四个问题：

| 契约项 | 要写什么 | 缺了会怎样 |
|---|---|---|
| `target_component` | 组件标识，实测取值都是仓库内路径 | 不知道改哪，或改错组件 |
| `baseline_behavior` | 改前快照，加 1 到 3 个具体反例：输入与当前的错误输出 | 无法验证改完是否变了 |
| `edit_semantics` | 编辑语义：add / delete / modify，加新旧规则对照 | 只给方向不给处方，改动会偏 |
| `affected_paths` | 该组件被哪些下游流程引用 | 修好 A 弄坏 B |
| `hypothesis` | 因果链：触发信号 → 归因 → 为什么这样改能修好 | 处方与诊断脱节 |
| `predicted_effect` | 可测预期：从什么值到什么值 | 没有判定基准，改动无法证伪 |
| `predicted_effect.measure` | 一条命令加期望（`expect_exit` 与 `expect_stdout` 至少一项）；确实不可度量时写 `reason` | 预测退化成散文，评审只能在「开全文」与「直接批」之间二选一（橡皮图章） |
| `verification` | 验证数据、测法、观察窗长度；落到 `validation.method` 与 `success_criteria` | 不可证伪的变更不该合入 |
| `rollback` | 回滚方式：revert、分支丢弃或配置开关 | 变更不可逆 |

另一组是审计链：`source_signals[].trajectory` 记问题在哪一段记录里，`decisions` 记谁在何时依据哪份证据判断什么。高风险 EV 卡只在授权时创建，不是普通改动的默认对象。

四条完整性规则：

1. 普通 signal 不产卡；只有高风险授权或历史归档才创建 EV 卡。行为质量改动走 RSI，不要求卡。
2. 终态卡必须有判断记录。`validated`、`rejected`、`superseded` 的卡，`decisions` 里必须有对应结论与所依据的评估数据；缺了是审计缺口。
3. `validated` 后 `actual_cost` 必填。没有实际成本记录的卡不可审计。
4. `supersedes` 与 `superseded_by` 构成替换链；同一时刻每个 `target_component` 至多一张 `validated` 卡。

终态是 agent 依据合入前可得的验证做出的判断。现场有效性（工程师回报）在合入后的观察窗里结算，结果作为追加记录写回卡，不改变卡状态。

必填字段清单以 `scripts/verify_proposals.py` 的 `REQUIRED` 为唯一事实源（`grep -n "^REQUIRED" scripts/verify_proposals.py`）。`target_component` 与 `predicted_effect.measure` 各有生效日检查，日期只写在脚本的 `TARGET_CUTOVER` 与 `MEASURE_CUTOVER` 常量里，本文不重复。存量卡豁免强制要求，缺口由 `python3 scripts/ev_measure.py --audit` 报出，不静默跳过。

脱敏：卡进 git 时只含聚合值与证据引用（记录路径加事件索引、issue 号加段落号），不含现场原文。原文留在本地 `traces/evidence/`；跨机器或对外分享时证据降级为摘要，并在卡上标注缺失的部分。

### 3.2 样本

样本记录输入、答案或 rubric、来源与用途。三个字段决定它怎么被评估、怎么被维护、能回答什么问题，三者正交：

- `object_type` 决定评分器与判定方法（diagnosis / case / reference / trace）。
- `origin` 决定维护方式（core 静态集 / field 动态集）。
- `purpose` 决定用途与答案可见性（六个取值，见 [evaluation.md](evaluation.md)）。

```yaml
sample:
  id: VLLM-ASC-14871
  status: candidate            # candidate / active / retired / rejected
  object_type: diagnosis       # diagnosis / case / reference / trace
  origin: field                # core / field
  purpose: evaluation          # evaluation / feedback / test / regression / cross / scale
  source: https://github.com/vllm-project/vllm-ascend/issues/14871
  input: {symptoms: "..."}
  expected: {namespace: inference/vllm-ascend, category: interrupt}
  expected_kind: resolution    # resolution / assertion / rubric
  rubric: null                 # case / reference / trace 使用
  non_diagnostic: false
  limits: null                 # 只有 scale 用：max_tokens / max_calls
```

状态与维护方式（origin）是两套词：状态只有 `candidate`、`active`、`retired`、`rejected`，origin 只有 `core`、`field`。状态只走这几条路径：

- `candidate → rejected`：来源、答案、脱敏、去重不过；终态，不复活。
- `candidate → active`（origin 为 field）：维护者通过。
- `active` 的 origin 从 field 转 core：稳定、覆盖足够、季度复核（`sample promote`）。
- `active → retired`：重复、来源失效、版本过期。
- `retired → candidate`：复活重审，不直接回 active。

不允许候选直接以 core 入场、core 退回 field、active 样本被标 rejected。状态与 origin 的变化都记时间、原因与操作人；旧结论随状态、origin 或用途变化作废。候选与 field 样本放本地运行件，core 样本放 tracked `eval/core/`；客户数据或未脱敏 trace 不升 core。

### 3.3 执行与结论

执行记录一次评估的数据，结论记录一次判定的结果与理由。两者都是一条记录一个文件或一行，只追加。

```yaml
run:
  sample: VLLM-ASC-14871
  versions: {protocol: p1, policy: policy-3, base_kb: 9f2c1a, candidate_kb: 9f2c1a, candidate: C-14871-001, model: deepseek-flash, algorithm: baseline, algorithm_version: manual, budget: {}, seed: 0}
  metrics: {routing: true, case_hit: false, root_cause: null, fix: null, safety: pass}
  cost:
    source: provider_billed     # provider_billed / normalized / estimate
    cache_accounting: reliable  # reliable / unreliable / unknown
    tokens: {uncached: 209617, cache_read: 27300000, cache_write: 0, out: 111653, billed: 27387126}
    calls: {knowledge: 3, source: 2, web: 0, command: 4}
    tool_ms: {total: 94000, pending: 0}
    rounds: null                # 回放单发，不可用；corrections 是现场读数，回放也不可用
  harness_session: null         # 回放必须补，否则 token 挂不到样本
  trace_ref: traces/2026-11-17-....yaml
```

版本坐标必须带 `algorithm`/`algorithm_version`；算法实验还带 `budget`/`seed`。手工 baseline 写 `algorithm: baseline`、`algorithm_version: manual`；不写算法身份的结论不能用于 GEPA/AEL 对照。`metrics` 是开放字典，缺数据的维度记 `null`，不补 `false` 或 0。`cost` 拿不到写 `null`，不写 0。回放必须带 `harness_session`，否则成本挂不到样本。指标的角色与方向写在 `sleuth.config.yaml 的 evolution.policy`，新增维度先在策略里注册。

```yaml
conclusion:
  decision: insufficient       # accept / insufficient / reject / unknown
  metrics: {routing: 0.9, case_hit: 0.6, root_cause: null, fix: null, safety: pass}
  cost: {tokens: 18342, calls: 12, ms: 94000, baseline_tokens: 20000}
  reason: "b=2, c=0, p=0.25 > alpha_eff=0.10"
  versions: {...}
  pool_hash: 5c1d2e
  reuse_index: 0
  alpha_eff: 0.10
```

四个取值的含义与判定条件在 [evaluation.md](evaluation.md) 的判定一节。这里只记形状：结论必须带 `reason` 与 `versions`；配对读数（`b`、`c`、`n`、`p_value`、`delta_q`、`cost_ratio`）与 `pool_hash`、`reuse_index`、`alpha_eff` 一起记，作为复现这次判定的坐标；同一份评估池每判一次，`reuse_index` 加一。

失败与补丁是中间产物，不落长期记录。审查结论只追加，不就地改写；要改判就重跑一次评估、写一条新结论，旧结论留在记录里并标作废原因。

### 3.4 版本

版本是执行与结论的共同坐标，六个字段缺一不可：

| 坐标 | 字段 | 含义 |
|---|---|---|
| 评估协议 | `protocol` | 样本分层、答案可见性、结论含义；改了它旧结论不可比 |
| 可调策略 | `policy` | 主指标、阈值、样本量、成本预算、测试集划分 |
| 基线知识库 | `base_kb` | 改动前检出的 HEAD 短 sha（`kb_rev` 同口径） |
| 候选知识库 | `candidate_kb` | 候选 worktree 的 HEAD；有未提交补丁时写成 `<base>+patch:<补丁哈希>`，worktree 失效记 `unknown` |
| 候选改动 | `candidate` | 候选 id；pilot 的补丁在隔离 worktree 内未提交，差异由 `candidate_kb` 的 patch 哈希标识 |
| 模型 | `model` | provider、model、思考等级；trace 的 `model`、非 DSH agent 写入的显式值，或 `harness_session` 对应的 DSH 会话记录；取不到写 `unknown` |

判定时协议、策略、基线知识库与模型必须相同；候选知识与候选改动可以不同，但差异必须等于候选补丁。两个知识库版本都要记：基线是 HEAD 短 sha；候选是 HEAD，或候选 worktree 有未提交补丁时的 `<base>+patch:<补丁哈希>`；worktree 已失效记 `unknown`。

两项记录的变更方式不同：改协议要单独走一次评审并升版本，旧结论标上当时的版本；改策略写在 `sleuth.config.yaml 的 evolution.policy`，加载时校验未知键、非法枚举与缺失字段，哈希写进 `versions.policy`。改过的策略与旧结论不可直接比较。

### 3.5 存储与写入规则

四类记录与两类派生数据各有归属：

| 数据 | 位置 | 进 git | 写入方 |
|---|---|---|---|
| 改进项卡 | `proposals/ideas/<EV-YYYY-NNN>.yaml` | 是 | agent，随 PR |
| core 样本 | `eval/core/` | 是 | 维护者，随 PR |
| 候选与 field 样本 | 本地运行件（gitignored） | 否 | `evolve.py sample` |
| 判定池与回归池 | `.s2-replay/arena/pool-*.yaml` | 否 | `eval_arena.py --build-pool` |
| 评估台影响记录 | `.s2-replay/arena/impact.yaml` | 否 | `eval_arena.py --gate` |
| 内容流程执行记录 | `metrics/skill-exec-log.yaml` | 否 | `log_skill_exec.py` |
| 结论与执行记录（v1） | `.s2-replay/evolve/conclusions.jsonl`、`runs.jsonl` | 否 | `evolve.py judge --record`；`evolve.py pilot decide` |
| 条目使用记录与本期读数（源） | `metrics/entry-activity.d/<周>.yaml`、`metrics/timeline.d/<期号>.yaml` | 是 | 汇总、结算与组装脚本 |
| 记录生成物 | `metrics/entry-activity/<部署>.yaml`、`metrics/timeline.yaml` | 是，但不手改 | 主干 job 或本地重建 |
| 会话与任务状态 | `proposals/sessions/`、`proposals/tasks/` | 否 | 会话脚本 |
| 季度自评与实验记录 | `proposals/reviews/`、`proposals/experiments/` | 否 | 人或多轮会话 |

三条写入规则：

1. 只追加。结论、判断、使用记录都不就地改写；要改判写新的一条。
2. 一行一条自包含。按周或按期的源文件配 `merge=union`，它是行级合并：嵌套结构里两人在同一处各插一段会拼出非法 YAML，所以每行带 `run`、`kind`、`id` 三个键，读端按三元组去重。
3. 加锁。同一克隆内共享的运行时件（执行记录、结算进度）由写侧持 flock；无锁并发实测里 16 次写入只剩 3 条。读取一律走封装好的入口，不在别处重新实现解析。

存储边界是同一克隆内共享，跨克隆与跨机不聚合。跨机的数据走聚合值进 `metrics/timeline.d/`；运行时件的路径用 `python3 scripts/shared_dir.py <名字>` 解析到主检出，不写相对路径。部署标识取环境变量 `ASCEND_SLEUTH_DEPLOYMENT`，缺省取主检出的目录名；同一克隆的所有 worktree 得到同一个值，面板只读本部署那一份。

### 3.6 记录之间的接口

记录之间是单向数据流：卡声明预期，样本提供输入，执行产生指标与成本，结论比较两侧，影响记录追加一次判定。接口按数据流定义，读文件、调模型、发 PR 都由适配器负责。

| 端口 | 方法 | 输入 → 输出 |
|---|---|---|
| 样本源 | `load()` | → 样本列表 |
| 执行器 | `evaluate(sample, versions)` | 样本、版本 → 执行 |
| 评分器 | `score(sample, run)` | 样本、执行 → 指标 |
| 归因器 | `attribute(feedback, run)` | 反馈样本、执行 → 失败 |
| 改动起草 | `draft(failures, component)` | 失败、位置 → 卡 |
| 评估器 | `decide(baseline, candidate, policy)` | 改前、改后、策略 → 结论 |
| 周读数 | `render(records, metrics)` | 记录、指标 → 读数 |
| 现场来源 | `load()` | → 现场记录 |
| 记录存储 | `append(record)` / `read()` | 结论或执行 → 写入/读回 |

三条约定。权限在接口层强制：执行器拿到的样本不含答案，评分器与评估器拿到的含答案，归因与起草拿到的是反馈集。缺数据返回 `unknown`，不返回 0 或空字符串。错误只保留四类——数据缺失、版本不一致、评审不可用、结果格式错误——统一映射到 `unknown`，不吞异常。

端口层已在 `scripts/evolve/ports.py` 定义五个 Protocol：样本源、执行器、评分器、记录存储、周读数。归因器、改动起草、评估器与现场来源还只有设计，没有对应 Protocol；适配器层（`scripts/evolve/adapters/`）已落地，旧脚本仍保留为完整实现，适配器只做临时/演进期的薄包装；归因器、改动起草、评估器与现场来源仍只有设计。完整设计见 `proposals/2026-11-17-self-evolution-design.md` 第 5.5 节，那里是档案，不作为执行依据。

### 3.7 内容流程的执行记录

内容 skill（issue-ingest、to-postmortem、to-reference、knowledge-groom）在收尾检查之前落一条执行记录，收尾检查自己也落一条，包括没有演进信号的情况；否则「跑了没信号」与「根本没跑」在数据上无法区分。diagnose 不落，它已有 trace，信息更全。

每条记录写入四项：调用（skill 名、版本、时间、来源）、产出（case 或 reference 或卡 id、状态流转）、关键决策的一句话依据、成本（token；没有记账环境用估算并标 `source: estimate`）。记录对象是 skill、动作与产物 id，不涉及人。

schema 在 `metrics/skill-exec-log.yaml`，只追加；`scripts/log_skill_exec.py` 写，`scripts/verify_exec_log.py` 校验，`scripts/tail_exec_log.py` 读（人读尾巴、`--summary` 聚合、`--json` 给面板）。路径由 `scripts/exec_log_path.py` 解析到主检出，同一克隆内所有 worktree 共写共读。文件缺失或空表按正常退化处理，退出码 0。

它覆盖内容流程的现场，不覆盖每次 skill 调用：高频调用全记录会让记录负担超过观测价值。跨克隆与跨机不聚合原文；`scripts/metrics_snapshot.py` 组装每期快照时把 `tail_exec_log --summary` 的聚合（`content_flow_runs`、`evolve_check_runs`、`evolve_check_no_signal`）写进当期源文件。

## 4 边界与失败模式

| 情形 | 行为 | 细则 |
|---|---|---|
| 候选缺来源或 expected / rubric | 退回，记候选终态 | 3.2 |
| 候选直接升 core、core 降回 field | 拒绝 | 3.2 |
| 样本答案中途进知识库、保留测试集被改 | 转回归、旧结论作废；测试集整套重设重跑 | 3.2、[evaluation.md](evaluation.md) |
| 对象缺 `object_type`、`origin` 或 rubric，或版本不一致 | 不判，记 `unknown` 或重跑 | 3.2、3.4 |
| 候选未提交或工作区不干净 | 不判，记 `dirty` | 3.4 |
| 成本缺失 | 记 `null`，不补 0 | 3.3 |
| 执行结果缺字段、或同一样本重复跑 | 缺字段记待办、重评分不重跑；重复跑按缓存键复用 | 3.3 |
| 多人同时写记录、答案泄漏或客户数据 | 加锁只追加；泄漏的样本作废并移出池；客户数据拒绝入库、脱敏 | 3.5、[evaluation.md](evaluation.md)、3.1 |
| 卡不完整（有执行与验证却无终态，或终态无判断记录） | 判为审计缺口，`verify_proposals.py` 校验 | 3.1 |
| 跨机器分享证据 | 降级为摘要，卡上标注缺失部分 | 3.1 |
| 执行记录文件缺失或空表、或跑在 worktree 里 | 缺失按正常退化处理（退出码 0）；共享件锚回主检出 | 3.7、3.5 |

## 5 现状

### 5.1 已落地

- 卡 schema 与生命周期完整性校验、两道生效日检查：`scripts/verify_proposals.py --check`（CI job `proposal-audit`）、`MEASURE_CUTOVER`、`TARGET_CUTOVER`；豁免缺口由 `ev_measure.py --audit` 报出。
- 评审把手与替换链：`python3 scripts/ev_measure.py <卡号> --run` 打印命令、实测与退出码；`supersedes` 与 `superseded_by` 已进 schema。
- v1 数据契约与命令：`scripts/evolve/` 的 `contracts.py`、`object_types.py`、`metrics.py`、`statistics.py`、`decision.py`、`pools.py`、`policy.py`、`samples.py`、`records.py`、`ports.py`；CLI 子命令 `policy`（check / show）、`sample`（new / list / check / review / promote / retire / set-purpose / absorb / draw-test）、`judge`、`brief`；结论与执行记录追加进 `.s2-replay/evolve/`。
- 指标校验与执行记录：`scripts/verify_metrics.py --check`；执行记录的 schema、写入、校验、读取与聚合进 timeline。
- 条目使用记录的源与生成物、`merge=union`、行级去重：见 [diagnosis-observability.md](diagnosis-observability.md)。

### 5.2 蓝图

- 适配器层与旧脚本薄壳：`scripts/evolve/adapters/` 与 `s2_replay.py`、`eval_arena.py` 的薄壳化；当前旧脚本仍是完整实现，v1 只覆盖诊断对象的二元配对判定。
- 知识、先验、过程三类对象的评分器与 rubric：`object_types.py` 有描述表，评分器未实现。
- core 样本与 `eval/core/`：目录不存在，core 样本仍是目标形态。
- 旧数据迁移：现有样本散在 `eval/s2/`、`eval/golden/`、`eval/holdout.yaml` 与池文件里，尚未迁进样本队列。
- 观察窗超时降级的正式状态（`unconfirmed_valid` / `unconfirmed` / `rolled_back`）：现场反馈断供持续两期以上再实现，此前用「标存疑加提醒人」；候选过期态 `stale` 参数待校准。
- 内容流程执行记录的服务化：目前是同一克隆内共享的本地文件。

### 5.3 已否决

- 卡里装 git 协作状态（`pending_merge`、`adopted` 一类）：批提交与合入是流程层的事，进卡词表会让状态机随流程变。
- `candidate` 待办态与旧的 `estimated_cost` 字段：前者与「产卡即执行」冲突，后者没有 token 记账时不产生实际约束（已由 `actual_cost` 取代）。
- 每次 skill 调用都落一条执行记录：记录负担超过观测价值；diagnose 有 trace，不重复落。
- 把计数与分数写回 case 文件：计数进记录、分数进索引生成物，case 只为内容层决定而改。
- `predicted_value`、`first_hit`、`expected_window` 三个字段与「把结论写进期文件」：前者依赖现场反馈，而该通道当前没有数据；结论按次记、期文件按周记趋势，粒度不同。

## 6 代码与文档入口

| 用途 | 入口 |
|---|---|
| 卡 schema 与校验 | `scripts/verify_proposals.py`（`REQUIRED` / `TARGET_CUTOVER` / `MEASURE_CUTOVER`）、`examples/sample-idea.yaml` |
| 卡的影响视图与水位 | `scripts/ev_proposal.py --impact`、`--waterline`、`--mark-merged --from-prs` |
| 预测实测 | `scripts/ev_measure.py --run`、`--audit`、`metrics/ev-measure-log.yaml` |
| 卡库聚合与审计缺口 | `scripts/ev_board_data.py` |
| 执行记录 | `scripts/log_skill_exec.py`、`scripts/verify_exec_log.py`、`scripts/tail_exec_log.py`、`scripts/exec_log_path.py` |
| 指标与 timeline | `scripts/metrics_snapshot.py`、`scripts/build_timeline.py`、`scripts/verify_metrics.py`、`metrics/gates.yaml` |
| 条目使用记录 | `scripts/trace_entry_activity.py`、`scripts/build_entry_activity.py`、`scripts/verify_entry_activity.py` |
| 结算 | `scripts/settle_trace_feedback.py`、`scripts/settle_s2_feedback.py` |
| 样本池、判定与样本队列（v1） | [evaluation.md](evaluation.md)；`scripts/evolve.py`（`policy` / `sample` / `judge` / `brief`）、`scripts/evolve/`、`sleuth.config.yaml 的 evolution.policy` |
| 结论与执行记录（v1） | `.s2-replay/evolve/conclusions.jsonl`、`runs.jsonl` |
| 共享路径 | `python3 scripts/shared_dir.py <名字>` |
| 状态与代码入口总表 | [status.md](status.md) |

## 7 外部参考

无。记录契约是本仓内部的约定，不与外部项目对照；外部参照分别在 [evaluation.md](evaluation.md) 的评估实践与 [operations.md](operations.md) 的编排载体两节。
