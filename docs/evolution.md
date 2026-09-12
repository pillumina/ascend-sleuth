# 演进机制（入口）

> **这是演进机制的唯一入口。** 日常只读这一篇：它给出三个闭环的全图、每件事"由哪篇文档说了算"、以及每周实际要做什么。
> 其余 `mechanism/*.md` 是**论证层**——只在你要改机制本身时才读（分层清单见 [README 的「文档」节](../README.md#文档)）。
>
> 本文不写死任何数字。条数与容量见 `knowledge/_index.yaml` 头注；卡数见 `scripts/ev_measure.py --audit`；
> 指标时序见 `metrics/timeline.yaml`。手写的数字会腐烂（本文曾写"123 条 case、7 张 EV 卡"，而当时已是 158 条、50 张）。

## 一、三个闭环

系统由三个闭环构成。**混起来读是理解这套机制最大的障碍**，所以先分清各自消费什么、产出什么、什么时候发生：

| 闭环 | 什么时候发生 | 入口 | 消费 | 产出 | 详细规则 |
|---|---|---|---|---|---|
| **诊断闭环** | 每次问题（分钟级） | `/skill:diagnose`（被打断则 `/skill:resume-diagnosis`） | 工程师贴来的日志 / 版本 / 报错 | 修复建议 + `traces/<session>.yaml`（含证据与决策依据） | `skills/diagnose/SKILL.md` |
| **沉淀闭环** | 定位结束 / 定期批量 | `/skill:to-postmortem`、`/skill:to-reference`、`/skill:issue-ingest` | 这次定位的知识（或上游 issue） | 待审队列 → groom 升格为 Tier 2 case / reference 词条 | 各 skill 的 SKILL.md；导入管道见 [issue-ingest-pipeline.md](issue-ingest-pipeline.md) |
| **演进闭环** | 内容流程收尾 / 全库观测轮 | `/skill:evolve-check`（伴随）、`/skill:self-evolve`（深度轮） | 上面两个闭环产生的数据：trace、命中率、流程摩擦 | EV 卡 → 执行 → 验证 → 攒批 PR（人审）→ 回到前两个闭环 | 本文 + 论证层 |

三个闭环**共用一条链**：诊断与沉淀产生数据，演进读数据改机制，改完的回落到诊断与沉淀。链条的每一段都要能回答"凭什么说它变好了"——那是 [eval.md](eval.md) 与 [git-workflow.md](git-workflow.md) 的评审把手管的事。

## 二、我该读哪篇（权威归属）

**一件事只有一个权威处**，其余文档都是论证或引用。改之前先看这里说的是哪篇：

| 你要做的事 | 权威文档 | 说明 |
|---|---|---|
| 判断某个设计/改动是否合规 | [design-principles.md](design-principles.md) | 十一条规范条文；不可追溯的变更是可疑的 |
| 改一个 skill 的行为 | `skills/<name>/SKILL.md` | skill 必须自包含：执行规则内联，不依赖 docs/ |
| 改测评门禁 / 跑回归 | [eval.md](eval.md) | 门禁分级、对照集封存、判据强度如实标注 |
| 走 PR / 门控 / 多人协作 | [git-workflow.md](git-workflow.md) | 含「评审把手」：reviewer 怎么判"该不该合" |
| 看指标口径 / 跑周批 | [metrics.md](metrics.md) | 数字在 `metrics/timeline.yaml`，机制在这里 |
| 改演进机制本身 | [mechanism/pipeline.md](mechanism/pipeline.md)（状态机与卡 schema）、[mechanism/execution.md](mechanism/execution.md)（信息契约与验证）、[mechanism/orchestration.md](mechanism/orchestration.md)（会话与预算）、[mechanism/run.md](mechanism/run.md)（持续运行） | 四篇各管一段，互有引用——改前先确认改的是哪一段 |
| 做评测机制（元层 / 交互面） | [mechanism/eval-arena.md](mechanism/eval-arena.md)、[mechanism/ixn-replay.md](mechanism/ixn-replay.md) | 论证层，稳定性要求高 |
| 排下一步工作 / 评估能否推广 | [roadmap.md](roadmap.md)、[rollout-assessment.md](rollout-assessment.md) | 闸门驱动，不按日历 |
| 查"当初为什么这样选" | `docs/adr/` | 决策留痕，含被否决的替代方案与重评条件 |
| 演进闭环自身健不健康（积压 / 可证伪面 / 自证比例 / 指路腐烂） | [mechanism/pipeline.md](mechanism/pipeline.md) §7.1（判据定义） | 判据数据在 `proposals/gates.yaml`，判决命令 `scripts/evolution_health.py`；判据落成数据、面板只渲染不重算（与 metrics 侧同一分工） |

> **关于代号**：本目录曾有一张"指代速查"表，把 L/S/A#/E#/M#/O#/P#/G#/T#/Phase 等设计层代号集中登记。
> 那张表本身是负担——读者要先学会一整套内部台账才能读机制文档，而**机制文档里本来不需要它们**。
> 代号的位置与用法见 [git-workflow.md](git-workflow.md)「人读性与代号约定」：内部记账号只在
> 各自的计划文档里裸用，机制文档、PR body、EV 卡 prose 一律写中文含义。

## 三、演进闭环的五个机制

按作用对象区分，前四个已实现，第四个部分实现。

### 1. 置信度校准（每次 fix 应用后）

case 的 confidence 不是人工设定而是在使用中习得：fix 被应用并确认解决，hits 加一；确认未解决，misdiagnoses 加一；score 随 last_hit 时间衰减。score 决定候选 case 的验证顺序，被反复验证的知识排到前面，被证伪的沉下去。结果捕获是结构化的：`feedback_pending` 标记写在状态文件里，任何一次 diagnose 或 resume 启动都会先追问未回报的结果，不依赖任何人的记性。

feedback 是双通道的，按**反馈对象**分类而非按"谁给的"分级，两条通道分别结算、不混算：

| 通道 | 反馈对象 | 来源 | 结算落点 |
|---|---|---|---|
| **现场 resolve** | fix 在**这个用户环境**是否解决 | 工程师回报 fix 结果（feedback_pending 追问捕获） | `case.confidence`（hits/mis/score，唯一现场解决率口径） |
| **内容验证** | case 的 symptom→rc→fix 是否与外部 ground truth 一致 | issue-replay 对照（issue resolution / fix PR 合入 / committer 确认） | `case.validation_record`（consistent=外部验证过，self_consistent=自证不虚增，inconsistent=复审信号） |

内容验证通道补现场断供的关键意义：confidence 依赖工程师回报（当前捕获率≈0），但 issue 池里已闭环的 resolution 是**不依赖人的 feedback**——沉淀这些 issue 时答案已在手上，replay 只是把它系统化。现场有效性（severity 语义、环境特异性）仍只认现场通道，这是两条通道不可合并的原因。

现场反馈的完整数据流（三个写入点，git 归属刻意不同）：

```
【诊断时】                            【反馈时】                      【周维护时】
工程师贴输入                         工程师回报"已解决/没解决"        groom 重算
   │                                     │                            │
   ▼                                     ▼                            ▼
state 文件（写 trace +                state 文件（trace 记             case 文件
feedback_pending: CASE-ID）           feedback action + 清             （读 hits/mis）
   │        │                        feedback_pending）               │
   │        └──下次 diagnose/resume ──► case 文件（更新                 ▼
   │            启动先扫它、追问结果     confidence: hits+1 /      build_index.py
   │                                   mis+1、score 重算、            重建索引
   │                                   last_hit）                    （score 同步）
   │                                    │
   │                                    ▼
   │                              trace_metrics.py（算指标）
   │                                    │
   │                                    ▼
   │                    metrics/timeline.yaml（数据，人复核后 append）
   │                    docs/metrics.md（机制文档，机制变才变）
```

各写入点归属：

| 写入点 | 内容 | 进 git? | 原因 |
|---|---|---|---|
| `traces/*.yaml` | trace + feedback_pending | 否（gitignored） | 含客户现场信息；运行时状态，终态后留在本地 |
| case 文件 `confidence` | hits/mis/score/last_hit | 是（走知识修改 PR） | 学习环的持久知识：hits+1 必须入库才能改变下次候选排序 |
| `_index.yaml` | score（仅 score） | 是（生成物） | case 变 → 重建 → 随同一 PR；CI `--check` 强制同步 |
| `metrics/timeline.yaml` | 指标时序数据（每期一条） | 是 | **周节奏、人复核**：脚本产出骨架，人看分母后 append；结构由 `verify_metrics.py --check` 校验 |
| `docs/metrics.md` | metrics 机制文档 | 是 | **稳定层**：只承载机制解释，不随每期数据变动 |

要点：**每次反馈直接写的是 case 文件（confidence）**，那是学习环的持久状态；metrics 数据是周期性的观测汇总，不是反馈的即时回写。

### 2. 知识注入（每次定位后）

to-postmortem 接受任意来源的调查记录（本地 session、外部对话、手工笔记、wiki 导出），提取症状、根因、修复，脱敏后进入 `postmortems/inbox/` 待审队列。groom 批处理：预分诊为 new_pattern / variant_of / covered_by 三类并附证据，人审后分别升格为新 case、并入已有 case（扩展版本区间）、或仅转正为 Tier 3 语料（人工沉淀按周批处理；自动化源的草稿 verification 链完整，可直接升格）。判定为已覆盖的记录不丢弃，它仍是检索语料和未来 fixture 的来源。

### 3. 误诊归因（每次误诊后）

误诊发生时，先读 trace 判断错误在哪一侧：trace 显示检索与检查执行都正确、但根因判断错误，是 case 错，修知识库；trace 显示跳过了 fallback、加载了错误命名空间、漏标了低置信，是执行错，修 skill 流程。这个区分防止一种具体的腐化：在执行出错时误改本来正确的 case。

### 4. 结构演化（按闸门触发）

知识库的结构本身也在演化，但由数据触发而非预先规划：命名空间达到容量软上限时 groom 预告拆分（首选拆分轴是 category，目录迁移与索引重建同一 PR 完成）；路由准确率持续偏低时，从 trace 的路由错例提取修订建议，走高风险双签合入；trace 结构挖掘报告低判别力的匹配式与噪声分支。

### 5. 退休与复活（每周）

版本区间过期、或长期被选中却未解决的 case 软退休进 `_archive/`，自动退出活跃索引；从未被选中的 cold case 不退休——罕见但正确的知识占索引成本极低，误删是静默损失。`_archive/` 中的 case 在新的兼容区间出现时可以复活。退休不是删除：trace 历史与 postmortem 全部保留。

## 四、护栏：演化为什么不腐化

每个演化机制都配一道对应的护栏，防止系统越学越错：

| 演化动作 | 护栏 | 挡住什么 |
|---|---|---|
| confidence 回写（现场通道） | 只按已回报的结果回写；串联保护（两次未解决即转人工） | 误诊级联 |
| validation_record 结算（内容通道） | 自证隔离（replay issue = case 来源 → self_consistent 不虚增）；consistent ≠ 现场 resolve（口径不混） | 自证虚高、把"找得到"冒充"用得上" |
| 新 case 升格 | inbox 人审 + 语义校验 + 高风险双签 | 错误知识入库 |
| agent 自起草候选 | 初始低 confidence，必须经 groom 验证 | 未验证知识被当作已验证 |
| 预分诊 / 置信度重算 | 只产出建议与证据，决定权在人 | 自动化误判直接生效 |
| 知识库增长 | 格子容量上限、值重复检测、合并建议 | 检索质量退化 |
| skill 流程修改 | 门禁分级回归（改前后对照）+ 对照集封存 + CODEOWNERS 审批 | 流程回归；"改量尺"绕过回归 |
| EV 卡预测 | `predicted_effect.measure` 必须可复现（reviewer 一条命令复核） | 只写在散文里、无法证伪的"改进" |
| 审查质量 | 随机审序；高风险变更强制深审；reviewer 自行随机抽一处核对 | 审查疲劳与惯性通过 |

两个横切设计贯穿所有护栏。

其一，建议与决定分离。所有自动化环节（预分诊、候选 case 起草、置信度重算）只产出建议加证据，采纳、调整或驳回永远由人执行。自动化负责压缩人的工作量，不接管人的判断。

其二，一切升级由数据触发。预分诊、路由自学习、结构挖掘都有明确入口闸门（见 [roadmap.md](roadmap.md)），闸门数值每季度用实测指标复核。不按日历排期，也不追随技术趋势；[ADR-0002](adr/0002-retrieval-no-rag-lightweight-index.md) 的检索决策重评条件是这一原则的典型样例。

## 五、数据回路：trace → metrics → 闸门

演化的节奏由数据决定。trace 汇入 `scripts/trace_metrics.py`，计算路由准确率、反馈捕获率、兜底挽救率等指标（数据落 `metrics/timeline.yaml`，定义见 [metrics.md](metrics.md)）。指标驱动两类决策。运营层面，路由准确率低则修分诊树，路由准但未命中高则补 case；架构层面，ADR 的重评触发条件是否命中、roadmap 闸门是否解锁。trace 历史永不删除，它是这套系统全部自我认知的数据来源。

**先看体检器再下结论**：`python3 scripts/metrics_health.py` 会报出陈旧、越界、不可解读三类问题（判据数值在 `metrics/gates.yaml`）。没有它，"零误诊"与"没人回报"看起来是一样的。

## 六、每周做什么（runbook）

机制只有落到每周的动作上才算存在。当前节奏与命令：

| 节奏 | 动作 | 命令 / 入口 | 产物 |
|---|---|---|---|
| 每次诊断后 | 回报 fix 结果（下一次诊断启动时会追问） | 回答 diagnose 的追问 | `case.confidence` 更新 |
| 定位结束后 | 沉淀知识 | `/skill:to-postmortem`、`/skill:to-reference` | `postmortems/inbox/` 草稿 |
| 内容流程收尾 | 伴随演进评估（有信号才产卡，无信号一行即止） | `/skill:evolve-check` | EV 卡 或 一行无信号记录 |
| 每周 | 批处理待审队列、升格、去重、退休、重建索引 | `/skill:knowledge-groom` | 知识变更 PR |
| 每周 | 产出指标快照并落一期（**任何人跑周批时都可做**；期号默认生成、一期一个源文件） | `python3 scripts/metrics_snapshot.py --kind live` → 人复核 → 写 `metrics/timeline.d/` → `build_timeline.py` → `metrics_health.py` | `metrics/timeline.d/` 一个源文件 + 重建的 `metrics/timeline.yaml` |
| 每周 | 批量拉取上游 issue | `/skill:issue-ingest` | inbox 草稿 + 导入游标 |
| 随时 | reviewer 判定一张卡 | `python3 scripts/ev_measure.py <卡号> --run` | 符合 / 被证伪 / 无法判定（并落一笔实测记录） |
| 每周 | 演进闭环体检（积压 / 可证伪面 / 自证比例 / 指路腐烂） | `python3 scripts/evolution_health.py` | 逐条判据的 ✓/✗ + 下一步动作（判据在 `proposals/gates.yaml`） |
| 全库体检时 | 深度观测轮 | `/skill:self-evolve` | 候选卡 + 攒批 PR |
| 每季度 | 闸门数值复核 + 四层就绪度重估 | [roadmap.md](roadmap.md)、[rollout-assessment.md](rollout-assessment.md) | 闸门数值修正 |

## 七、当前状态与已知缺口（不写死数字）

- **机制完整度**：五个机制中 1（置信度回写）、2（知识注入）、3（误诊归因）、5（退休复活）已实现；机制 4 的容量预告已实现，路由演进与结构挖掘在路线图上。
- **演进闭环自身的健康度有判据了，且第一条判据当场就是红的**：`python3 scripts/evolution_health.py`
  报出卡库里**从未出现过一次否决**（终态卡 `rejected`/`superseded` 都是 0），另有待合入积压、
  可复现判据一次没测过、外部 ground truth 占比过低等。这些不是"系统做得不好"的指控，而是
  **假设检验缺少拒绝域**在数据上的直接读数——一个只采纳、从不否决的生成器不是在做检验。
- **数据侧最大的前提未满足**：现场反馈捕获率≈0——即机制 1 的输入是空的。这是继续推广前最关键的一条，也是"机制齐备"与"系统在变准"之间的差距所在。补它的动作不在机制侧，而在让真实工程师跑完一次诊断并回报结果。
- **回归保护的覆盖缺口**：`python3 scripts/holdout.py --list` 会报出"有 case 却没有夹具"的格子——当前 training 与 common 段没有任何回归夹具，即改 skill 对这些场景没有 golden 信号。
- **号码与文件位置**：`scripts/ev_measure.py --audit`（卡与预测口径）、`scripts/build_docs_index.py --check`（文档与 skill 名单）、`knowledge/_index.yaml` 头注（条数与容量）。

机制细节见逐篇论证层文档；**改动机制之前先读 [design-principles.md](design-principles.md) 与 [eval.md](eval.md)**（门禁分级与"改量尺"的规矩）。
