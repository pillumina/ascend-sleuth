# ascend-sleuth Metrics

本文是 metrics 机制的文档化解释（人读理解用），不是数据存储。指标数据在 [`metrics/timeline.yaml`](../../metrics/timeline.yaml)（生成物；源是 `metrics/timeline.d/<期号>.yaml`，一期一个文件）；机制文档只在机制变化时更新（指标定义、口径、流程），不随每期数据变动。

读者是跑周批、校准闸门、或要引用指标口径的人。只看面板趋势的人不必读。

## 1 做完得到什么

得到一期可读的指标快照：`metrics/timeline.yaml` 里多出一条 live period，体检通过后随 PR 提交。

## 2 前置条件

### 角色分工

| 载体 | 内容 | 变更频率 |
|---|---|---|
| `metrics/timeline.d/<期号>.yaml` | 时序数据的源：一期一个文件（period / kind / metrics / sources / notes） | 每期（谁跑周批谁写一个） |
| `metrics/timeline.yaml` | 生成物：由源重建的聚合（`periods:` 列表，读侧的唯一入口） | 每次源变化后重建（不要手改） |
| `scripts/build_timeline.py` | 聚合重建 / `--check` 校验生成物与源一致（CI 强制） | 随机制 |
| `docs/guide/metrics.md`（本文） | 机制文档：指标定义、口径、汇总流程、示例 | 机制变化时 |
| `metrics/gates.yaml` | 阈值与可解读性下限（数据）：新鲜度上限、读入成本线（类视图 `cell_read_soft_tok` / `cell_read_hard_tok`，兜底视图 `fallback_read_soft_tok` / `fallback_read_hard_tok`）、反馈下限、哪些指标分母为 0 即"不可解读" | 判据变化时 |
| `scripts/metrics_snapshot.py` | 一期快照的单一产出命令：组装诊断侧 + 结构侧 + 内容流程侧（逐块标 `sources`）；撞号自动加后缀 | 随机制 |
| `scripts/metrics_health.py` | 闭环检测器：读 timeline + gates，判新鲜度 / 越界 / 可解读性；`--check` 三态（0 判据全评过且无越界 / 1 有违反 / 2 有判据未被评估）；`--json` 是诊断面板的数据契约 | 随机制 |
| `scripts/trace_metrics.py` | 诊断侧指标（markdown 概览 + `--emit-yaml` 骨架 + `--emit-yaml-only` 供组装） | 随机制 |
| `scripts/verify_metrics.py` | 校验聚合结构（period 唯一 / kind 合法 / live 期号命名 / 比例字段合法 / live 字段白名单），CI 强制 | 随机制 |
| `scripts/session_cost.mjs` | 真实账单（提供方 usage）：解析 DSH 会话日志（多帧 zstd + JSONL），按 (turn, step) 去重后给出未缓存输入 / 缓存读取 / 缓存写入 / 输出与逐轮汇总；`--session <id>` / `--file` / `--all`；exec-log 的 `--cost-source measured` 就该填它读出来的值 | 需要 measured 口径时 |
| `scripts/audit_skill_cost.py` | skill 上下文成本审计：常驻面（CLAUDE.md/AGENTS.md/被注入的 description）、按需面（正文 + 本地 references）、重复面（同一行出现在 ≥2 skill）、强制词密度与输出段数；skill-review 的 A 静态审计调它 | skill 改动前后 |

### 指标定义

指标来自四类来源——不是"单一脚本"：本行原写作"所有指标由 `trace_metrics.py` 计算（单一数据源）"，
而实际 timeline 里还有结构侧与评测侧指标。这个错误表述让周批只跑 trace_metrics、其余靠人手工搬运，
实测导致结构指标 10 天没进快照（快照 `case_total 52` vs 现实 158，某格已 `85/30` 而快照里还是 `36/30`）。

| 来源 | 谁产出 | 指标 |
|---|---|---|
| 诊断侧 | `trace_metrics.py`（读 `traces/*.yaml`） | 命中率、误诊率、路由准确率、归因比、按类命中、置信度分布、trace 完整性、Tier 3、反馈捕获、reference 引用/消费点、流程加载与跟随 |
| 结构侧 | `index_counts.py`（条数，现算）+ `index_read_cost.py`（读入成本，现算）+ `verify_references.py` | `case_total`、`reference_total`、`capacity_by_ns`（每格 `count` + `tok`；成本才是被治理的量）。一次诊断的读入账另有三个分项由 `index_read_cost.py` 现算（兜底视图 / 先验层 / 阶段二候选全文），体检的 `capacity_fallbacks` 取自它 |
| 内容流程侧 | `log_skill_exec.py` → `tail_exec_log.py --summary` | `content_flow_runs`、`evolve_check_runs`、`evolve_check_no_signal` |
| 评测侧 | ixn / golden / S2 等按需 | `ixn_*`、`golden_suite`、S2 内容验证（口径见下） |

`metrics_snapshot.py` 把 ①②③ 拼成一期骨架（④ 按需；拿不到的块不写，不用 0 冒充）。
比例类指标要连同分母解读，样本量小（分母不足 10）时波动很大。

traces 是各检出各一份的运行时件：在 worktree 里跑周批读不到主检出的 trace
（实测会静默产出空诊断指标）。`metrics_snapshot.py` 会自动解析该读哪一份（优先主检出）
并在 `sources.diagnose_side` 里标明；手工跑 `trace_metrics.py` 时需显式 `--root <主检出>`。

| 指标 | 含义 | 数据来源 |
|---|---|---|
| 命中率 | Tier 2 直接匹配并解决的比例 | trace `hit` 事件 + session 最终 status |
| 误诊率 | 命中了但 fix 没有解决问题的比例 | hit + feedback `not_resolved`/`partial` |
| 路由准确率 | 最终 root cause 所在 namespace 是否在被加载集合内 | triage `routed` / triage_semantic `namespace` vs hit case 实际 namespace |
| 执行-误诊归因比 | 误诊中 case 错与执行错的比例 | trace `attribution` 事件 verdict（diagnose 反馈 not_resolved 后自动归因） |
| 按类命中 | interrupt / precision / performance 各自的命中率 | trace triage/triage_semantic 的 category vs hit |
| triage miss 归类 | 未命中里「token 在场而词法层没接住」（真缺陷，进 E2 错例池）/「本来无 token」（级联换挡）/「routed 未记录」（取数字段缺口）各多少 | 每个 session 的 user 文本是否含 token 类信号（错误码/环境变量名/算子名/文件名/版本）与 triage / triage_semantic 事件形态 |
| 置信度分布 | 低置信（score<0.5）case 占比 | `knowledge/_index.yaml` score 统计 |
| 自起草采纳率 | groom 验证通过的草案 / agent 起草总数 | 暂无数据源（agent 自起草未落地，落地后补） |
| trace 完整性 | 有 trace 记录的 step / 实际执行 step | proxy：含 triage + 过滤步 |
| Tier 3 挽救率 | 走 Tier 3 兜底检索且最终 resolved 的比例 | trace `tier3` action |
| 反馈捕获率 | 回报 fix 结果的 session / 给出 fix 的 session | trace `feedback` action |
| reference 引用 | 引用次数 / 引用后 resolve 率 / 平台分布 / 消费点分布（`reference_purposes`：collect / signature / background / fix / procedure，进 live 快照）/ 触发三态分布（hit / miss / skipped） | trace `reference_lookup` 事件（引用后 outcome 从 session 最终 status 派生；消费点看 `purpose`——`collect` 是数据缺口的采集面，此前无该值可记，等于零观测）。触发三态（EV-2026-093）看 `outcome`：`hit` 用到、`miss` 查了没命中（指向知识库覆盖缺口）、`skipped` 没查且写了理由（指向流程执行）。三态缺一，"没查"与"查了没命中"同形，消费率无法归因。`skipped` 不计入「引用次数」——那个口径是"查过" |
| 流程加载与跟随 | 流程加载率（`purpose: procedure` 的会话占比）/ 每条流程的加载次数与跟随深度（`procedure_follow` 的 `steps_executed` 长度 / `branch_taken` 分布）/ 跟随后 resolve 率 | trace `reference_lookup`（purpose=procedure）+ `procedure_follow` 事件。这是流程层唯一的可观测面——没有它就无法判断某条流程该留、该改、该摘（EV-2026-038）。注意：加载率是活动度量不是价值度量（加了触发点必然接近 100%），必须与"跟随后 resolve 率"配对读。注意 `purpose: procedure` 也会计入上表的"reference 引用次数"——该口径自此混装五个消费点（collect / signature / background / fix / procedure），看消费点构成请用 `purpose` 分布，不要只看总数。强度标注（原则十）：加载率是确定性的（来自 `reference_lookup` 事件）；
跟随深度（`steps_executed` / `branch_taken` / `conflict`）是 agent 自报——属弱观测，只可作趋势与异常信号，
不可当验收证据；跟随后 resolve 率来自工程师反馈闭环（S1），是本行唯一较强的效果信号 |
| 零执行评估所需的记录 | 停止原因记了几单 / 未记录几单；同批并发标记与候选全集各记了几条事件；字段违规几处（给总数，另列前 5 条） | trace 顶层 `stop_reason`（词表 = `scripts/trace_metrics.py` 的 `KNOWN_STOP_REASONS`）与 agent 事件的 `parallel_group`、`considered_candidates`。这是用历史记录离线比较探索策略的前提：不知道当时在哪停、哪些动作是同一批并行、筛候选时看过哪些，换一个策略在历史上走一遍就只能按人回忆重讲。未记录数与记了 `unknown` 分开算：前者是记录缺口，后者是当时确实拿不到；旧 trace 没有这些字段属未记录，不回填 |
| S2 内容验证（口径，数据积累后进 timeline） | case 被 S2 replay 验证的分布：consistent（内容与外部 resolution 一致）/ self_consistent（自证）/ inconsistent（复审） | `.s2-replay/*.result.yaml` → `settle_s2_feedback.py` 结算 → case `validation_record`。口径纪律：consistent ≠ 现场 resolve——S1 现场解决率看 confidence（上表命中率/误诊率），S2 内容验证是独立通道，进 timeline 时标注 `source: issue-replay`，不与 S1 混算。按检查准入三条件，待 S2 结算有真实数据（≥2 期）后再扩展 verify_metrics 白名单 |

### 快照 schema（`metrics/timeline.yaml`）

每个 period 条目结构固定（由 `trace_metrics.py --emit-yaml` 生成骨架，人复核后 append）：

```yaml
periods:
  - period: "2026-W36-live-0829"      # 趋势锚点，必须全局唯一；live 期号规则见下
    kind: live                      # live（活诊断周期快照）| replay（回放评估）| example（示例）
    title: "本期诊断指标"
    recorded_at: "2026-08-29"       # 人复核日期（不可自动戳）
    source: "metrics_snapshot.py 组装（诊断侧+结构侧+内容流程侧）"
    sources:                        # 逐块出处（组装命令写入；手写快照可省）
      diagnose_side: "trace_metrics.py（traces/*.yaml ← 主检出，12 个 session）"
      structural_side: "index_counts.py 现算 + verify_references.py"
      content_flow_side: "log_skill_exec.py → tail_exec_log.py"
    metrics:
      sessions_total: 12
      tier2_hit: 3
      routed_accuracy: {ok: 2, total: 3}
      misdiagnosis_rate: {ok: 1, total: 3}
      by_category_hit: {interrupt: {hit: 1, total: 1}}
      attribution_ratio: {case_error: 1, execution_error: 0}
      confidence_distribution: {low: 19, total: 42}
      feedback_capture: {resolved: 1, not_resolved: 1, partial: 0}
      trace_completeness: {ok: 2, total: 3}
      vocab_compliance: {ok: 22, total: 22}
      tier3: {used: 0, saved: 0}
      reference: {hits: 1, refs: 1}
      case_total: 158                        # 结构侧
      reference_total: 130
      capacity_by_ns: {inference/vllm-ascend: {interrupt: {count: 85, cap: 30}}}
      content_flow_runs: 4                   # 内容流程侧
      evolve_check_runs: 1
      evolve_check_no_signal: 1
    notes: |
      # 人复核时补充本期解读（miss 归因、异常说明、非指标信息），可多行
```

规则：
- 源与生成物：`metrics/timeline.d/<期号>.yaml` 是源（一期一个文件，各人各写一个不互相覆盖）；
  `metrics/timeline.yaml` 是由 `scripts/build_timeline.py` 重建的聚合，读侧只读它，CI 校验两者一致。
  冲突因此是机械动作（重跑一次重建），不是判断题（留哪一份读数）。
- live 期号规则：`YYYY-Www-live-MMDD`（如 `2026-W37-live-0913`；同一天的第二期加后缀 `-2`），
  `verify_metrics.py --check` 强制。为什么带日期：期号是趋势锚点，而周批人人可跑（并发修改靠
  PR merge 合流，见 CLAUDE.md「多 agent 协作」）。手写期号有两种坏结局——同名（CI 靠 period
  唯一性拦住，但拦在 merge 时）与异名同期（各自进 main，趋势线上同一周两个数字，读的人分不清
  哪个是真的）。带快照日期后两人产出的期号天生不重；同一天的第二期由生成器自动加 `-2`。
  `2026-09-12` 之前的期豁免、不追溯改名（改名是改写历史锚点，而源数据是 append-only）——
  豁免是标注，不是放宽。
- `kind` 只有 `live` 参与跨期趋势对比；`replay`（回放评估）与 `example`（示例）供参考，不参与趋势
  - 结构性指标（`case_total` / `reference_total` / `capacity_by_ns`）允许出现在 live：它们是最该看趋势的治理指标，早期只能放在 replay 里 → 按本规则等于没有趋势通道（实测某格已 `85/30`，快照里还停在 `36/30`）
- `verify_metrics.py --check`（CI）校验：period 唯一、kind 合法、recorded_at 必填、metrics 非空、比例字段 ok/total 合法、live 字段在白名单内、`sources` 若填必须是 mapping
- 无数据的指标不写（reference 刚建立时 hits=0 是现状，不是 bug）

### 为什么源与生成物分开，数据不进 docs

为什么源与生成物分开（2026-09-13，起因是提问"两个 PR 都生成了这个文件、同名怎么办"）：
`timeline.yaml` 原先既是源、又是所有人 append 的目标，而它是一个列表文件——任意两人各加一期
都会撞在同一段文本上，冲突要人判断"留哪一份"，而判断错了就静默丢掉一期读数（实测这个冲突连
不同周也会发生，因为大家写的是同一个文件的尾部）。改成"一期一文件 + 生成物"后，冲突的性质变了：
各人各写一个小文件（互不相干），聚合由脚本重建——冲突从"判断题"变成"重跑一次命令"（机械动作）。
这与仓库既有模式一致：`knowledge/` 174 个 case 文件 + 生成的 `_index.yaml`、`proposals/ideas/` 58 张卡。
读侧没变：7 个读点继续读 `metrics/timeline.yaml`。

为什么数据不进 docs：docs 是给人看的稳定文档，指标数据是随使用增长的结构化记录——两者变更节奏不同，混在一起会让文档随数据漂移（曾发生 W28/W35 字段格式不同、跨期不可比的教训）。数据进 `metrics/timeline.yaml` 后，结构由 CI 校验兜底（原则二：不变量写进结构）。

## 3 步骤

### 周批流程（谁做：跑周批的人）

metrics 在周批时机生成并 append（每期一条，团队共享）——不是某个角色的专属动作：
周批可由任何人跑（groom 本身人人可跑），而写入的并发不靠覆盖、也不靠判断：
一期一个源文件（`metrics/timeline.d/<期号>.yaml`），聚合是生成物、由重建命令产出，
两个人最多在各自那个小文件上冲突——合流时是"重跑一次 build_timeline.py"的机械动作
（CLAUDE.md「多 agent 协作」：各 worktree 是各自分支副本，合流时显式合并），
期号唯一性、命名规则与生成物一致性由 `verify_metrics.py --check`、`build_timeline.py --check` 兜底。

工程师不必为此做额外动作：他们只做诊断（本地 trace）+ 回报 fix 结果（case confidence 走 PR）；
中心化指标直接从仓库 case 统计，无需工程师提交。

```
1. 组一期骨架（三块一起，不用再从多个脚本手工搬运）：
   python3 scripts/metrics_snapshot.py --kind live
   → 期号默认按 kind 生成正确形状（live 为 2026-W37-live-0912），不要手写
   → stdout：人读摘要（含"如实缺席"清单 + 已越界格子）+ YAML 骨架（逐块 sources）
2. 体检（判据在 metrics/gates.yaml：新鲜度 / 越界 / 可解读性）：
   python3 scripts/metrics_health.py
   → 逐面列出 ✓/!/✗ 与行动，末尾报"判据覆盖面"
   → `--check` 退出码三态：0 判据全评过且无越界 · 1 有违反 · 2 有判据未被评估（结论不可用）
3. 人复核：核对分母、把"不可解读"的指标写进 notes（禁止把 0/N 读成"零问题"）、
   越界格子按行动列处置（容量拆分走 groom 步骤 6）；`recorded_at` 是复核日期，脚本预填的当天不等于已复核
4. 把这一期写进源文件 `metrics/timeline.d/<期号>.yaml`，再重建聚合：
   python3 scripts/build_timeline.py
   → 不要直接编辑 `metrics/timeline.yaml`（生成物，重建会覆盖；`--check` 会红）
   → 同一天已有同期时生成器会自动加后缀（`…-0913-2`），照它给的期号写
5. python3 scripts/verify_metrics.py --check 通过后随 PR 提交
```

### 季度回顾（固定动作）

用 `metrics/timeline.yaml` 中连续 live 快照：核对命中率/误诊率/路由准确率趋势，校准 [roadmap](../plan/roadmap.md) 闸门数值，确认学习闭环在数据上成立。趋势直接从 YAML 读取，不需人眼 diff。

回顾前先跑一次体检：`python3 scripts/metrics_health.py` —— 它把"哪些指标超期没更新、
哪些闸门越界没人处理、哪些指标本期不可解读"直接列出来，避免回顾时对着过期快照讨论趋势。

## 4 怎么确认做对了

### 闸门与可解读性（`metrics/gates.yaml` + `metrics_health.py`）

阈值落成数据（`metrics/gates.yaml`），由 `metrics_health.py` 在周批流程第 2 步判三件事：

| 面 | 判据（gates.yaml） | 说明 |
|---|---|---|
| 新鲜度 | `live_snapshot_max_age_days` / `structural_max_age_days` | 超期 = 趋势断档（实测：结构侧 10 天没进快照） |
| 越界 | `cell_read_soft_tok`(>8000) / `cell_read_hard_tok`(>=20000) / `fallback_read_soft_tok`(>8000) / `fallback_read_hard_tok`(>=20000) / `feedback_capture_floor`(<=0) | 每条带 `meaning` 与 `action`，报告直接给下一步。容量线按实读 token 判（现算 `scripts/index_read_cost.py`），不按条数——条数只是代理量，实测每条 177 token 而旧政策按 70 估。两条读取路径各判一条线：类视图（category 已定）与 ns 兜底视图（category 未定才读）；先验层与阶段二候选全文只量不判（见下） |
| 可解读性 | `readability` 规则（如 `source_nonzero`） | 分母/来源无数据时把指标标成不可解读，禁止把 `0/N` 读成"零问题" |

### 一次诊断的读入账：四个分项，线只加在有证据的地方

`scripts/index_read_cost.py` 报的是"查一次问题要读进来多少字"，分四项：

| 分项 | 何时读 | 判线 |
|---|---|---|
| 类视图 `knowledge/_index/<ns>__<category>.list` | category 判出来时（命中路径） | 软 8000 / 硬 20000 |
| 兜底视图 `knowledge/_index/<ns>.list` | category 没判出来时 | 同一条线（数值同一套推导，单列 dimension 让"哪条路径越线"看得出来） |
| 先验层（背景索引整读 / 流程选择器 / 分片 / 错误族表） | 步骤 2 收尾与步骤 5 | 不判：检索式读取（一次 grep + ≤5 行），成本不随库大小线性涨 |
| 阶段二候选全文（≤5 条） | 候选验证 | 不判：上限是"读几条候选"，压低字数等于压低证据量 |

先验层的退化量不是 token 而是检索残量（平台 + 类别两刀切完剩多少行，`index_read_cost.py` 现算）——它随词条数线性涨，比 token 更早说明"还找不找得到"。兜底视图此前被明确写在线外：vllm-ascend 兜底视图 24270 tok（全系统最贵的一次读）不在任何判据里、`--json` 退 0。现在它接上同一条线（`fallback_read_soft_tok` / `fallback_read_hard_tok`）。先验层与阶段二先量不判：按准入判据（机械可判 + 确定性后果 + 已复发 ≥2 次），缺的是第三项。

为什么必须单独有这一层：`verify_metrics.py` 只验结构（period 唯一/字段合法），
它不判"该更新的没更新""越界了""这个 0 是没数据还是真没问题"——实测按旧流程走一遍
（trace_metrics → 复核 → append → verify）不会被告知上述任何一条，指标坏了只能等人想起来。
检测器不进 CI：安静的一周没有新快照是正常状态，硬门会假红；它服务于周批与季度回顾。

### `--check` 的三态：把「体检器坏了」与「本期没事」分开

`--check` 的退出码不止"有没有 ✗"（2026-09-11 起），语义与 `ev_measure.py` 三态同形：

| 退出码 | 含义 | 处置 |
|---|---|---|
| `0` | 判据全部被评估过且无越界 | 本期确实没有阻塞项 |
| `1` | 有判据被违反 | 按报告的 `action` 列处置 |
| `2` | 有判据没被评估（结构性） | 结论不可用——"没有越界"不成立，先修检测器/数据源 |

## 5 出错了怎么办

### 检测器假绿：判据没被评估时仍退 0

为什么需要 2 这一态（两个实测假绿的教训）：修前只看"有没有 ✗"，于是
①`metrics_health.py` 里一处 `collect_structural` 漏解包（返回元组未拆）让容量格子恒为空 →
两条容量闸门从未触发过一次，`--check` 照样 exit 0；
②`load_yaml` 把解析异常 `except: return {}` 吞掉 → `gates.yaml` 语法坏掉时判据变成 0 条，
体检器报 `clean（判据全部评过）`——检测器的配置读坏了它自己不会喊。
现在两种情况都报 2，并逐条点名（`--json` 的 `broken` 字段），
报告里也给"判据覆盖面"（`闸门 N/M 条已评估 · 可解读性规则 K/L 条已评估`）——
"没报越界"与"没被检查"从此在数据上可区分。诊断面板的指标 tab 首屏据同一份输出显示
「体检器失效」，而不是"闭环未见阻塞项"。

### 不可解读：不能把 0/N 读成零问题

可解读性纪律：`metrics_health.py` 判为"不可解读"的指标（例：反馈捕获为 0 时的误诊率），
不得在 notes/报告里写成"零误诊/无异常"——那是把"没人回报"读成"没有问题"。写成
"本期该指标不可解读（原因）"。

## 6 怎么退回去

- 手工改坏了共享的 `metrics/timeline.yaml`：不要手改这份生成物，重跑 `python3 scripts/build_timeline.py` 从源重建。
- 源文件写错：`metrics/timeline.d/<期号>.yaml` 是 append-only 的源，不改历史期号（`2026-09-12` 之前的期豁免、不追溯改名）。
- 已合入指标口径的回滚不在本文范围。
