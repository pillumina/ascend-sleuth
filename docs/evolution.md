# 自演进设计

诊断知识系统有两种失败终点。一种是停止演化：知识库过时、命中率衰减，最终没人再用。另一种是失控演化：重复条目膨胀、错误 case 积累、检索质量下降。自演进设计的目标是在两者之间维持一条受控路径：知识随使用持续改进，每一条变更都有护栏挡住腐化。

本文说明演化的整体回路、五个演化机制、护栏的构成，以及数据如何驱动演化节奏。机制的理论生成处是[设计理论](design-theory.md) §4.3（两级学习闭环：快环回写置信、慢环归因改结构）；原则层面的依据见[设计原则](design-principles.md)；操作细节见 `skills/knowledge-groom/SKILL.md`；演进中的机制（路由自学习、结构挖掘等）见 [roadmap.md](roadmap.md)；把观测数据转成系统自身改进提案的三层闭环（L1 知识 / L2 流程与 skill / L3 工作流编排，含自演进执行流程设计）见 [evolution-pipeline.md](evolution-pipeline.md)。

> **指代速查**（本组文档代号总登记处——读前先看；各代号在各自定义处详述。**新增代号必须先在此登记，禁止与既有代号撞车**，撞车实例教训：WikiSkill 增量初稿用 G1/G2/G3，与下表的治理缺口 G1–G8 冲突，EV-2026-009 复审后改描述名）：
>
> | 代号 | 含义 | 定义处 |
> |---|---|---|
> | **L1 / L2 / L3** | 演进对象三层：知识内容（case/reference）/ 流程与 skill / 工作流与编排 | evolution-pipeline.md §1 |
> | **S1 / S2 / S3** | 评分源分级（反馈按对象分）：S1 现场回报→confidence / S2 issue-replay 对照→validation_record / S3 golden 回归门 | evolution-pipeline.md §2.1 |
> | **A# / E# / M# / O# / P#** | roadmap 事项 ID（架构/可演进性/可维护性/可观测性/流程），如 E2=router 从 trace 错例演进 | roadmap.md 各维度表 |
> | **G1–G8** | 治理缺口标注（G1 会话层缺失…G8 无暂停重启）——**不是"改进增量"系列** | evolution-orchestration.md 引言 |
> | **T#** | evolve-check 触发信号条目（如 T4=执行错无归属 → L2 卡） | skills/evolve-check/SKILL.md 信号表 |
> | **EV-YYYY-NNN** | 自演进决策档案卡 ID（proposals/ideas/） | evolution-pipeline.md §7 |
> | **Phase A–E** | 落地阶段（A 文档采纳…E 常态化），与 roadmap 的 "E6" 无关联 | evolution-pipeline.md §11 |

## 演化回路

诊断循环每次运行产生三种数据：trace（哪些步骤按什么顺序执行了）、fix 结果反馈（解决了没有）、postmortem（这次定位的完整知识）。演化循环消费这些数据，产出更准的知识库，回到诊断：

```
诊断循环（每次问题，分钟级）              演化循环（git 门控）

trace ─────────────► 误诊归因：case 错改知识库 / 执行错改 skill 流程
fix 结果回报 ───────► confidence 回写：hits / misdiagnoses → 候选排序
postmortem ─────────► inbox 待审队列 → groom 三分类 → 升格 / 并入 / 转正
        ▲                                              │
        └──────────── 下次诊断直接命中 ◄────────────────┘
```

## 五个演化机制

按作用对象区分，前四个已实现，第四个部分实现：

### 1. 置信度校准（每次 fix 应用后）

case 的 confidence 不是人工设定而是在使用中习得：fix 被应用并确认解决，hits 加一；确认未解决，misdiagnoses 加一；score 随 last_hit 时间衰减。score 决定候选 case 的验证顺序，被反复验证的知识排到前面，被证伪的沉下去。结果捕获是结构化的：`feedback_pending` 标记写在状态文件里，任何一次 diagnose 或 resume 启动都会先追问未回报的结果，不依赖任何人的记性。

feedback 是双通道的（2026-09 确认，selfevolve-loop 重构），按**反馈对象**分类而非按"谁给的"分级，两条通道分别结算、不混算：

| 通道 | 反馈对象 | 来源 | 结算落点 |
|---|---|---|---|
| **S1 现场 resolve** | fix 在**这个用户环境**是否解决 | 工程师回报 fix 结果（feedback_pending 追问捕获） | `case.confidence`（hits/mis/score，唯一现场解决率口径） |
| **S2 内容验证** | case 的 symptom→rc→fix 是否与外部 ground truth 一致 | S2 issue-replay 对照（issue resolution / fix PR 合入 / committer 确认，issue 本身的 resolution 就是 feedback） | `case.validation_record`（consistent=内容被外部验证，self_consistent=自证，inconsistent=复审信号；settle_s2_feedback.py 结算） |

S2 通道补 S1 断供空缺的关键意义：confidence 依赖工程师回报（当前捕获率≈0），但 issue 池里已闭环的 resolution（fix PR 合入、committer 确认）是**不依赖人的 feedback**：系统沉淀这些 issue 时答案已在手上，S2 replay 只是把它系统化。现场有效性（severity 语义、环境特异性）仍只认 S1，这是两条通道不可合并的原因。

S1 feedback 闭环的完整数据流（三个写入点，git 归属刻意不同）：

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
| `traces/*.yaml` | trace + feedback_pending | 否（gitignored） | 含客户现场信息；运行时状态，终态后留在 traces/（本地） |
| case 文件 `confidence` | hits/mis/score/last_hit | 是（走 knowledge_modification PR） | 学习环的持久知识：hits+1 必须入库才能改变下次候选排序 |
| `_index.yaml` | score（仅 score，ADR-0004） | 是（生成物） | case 变 → 重建 → 随同一 PR；CI `--check` 强制同步 |
| `metrics/timeline.yaml` | 指标时序数据（每期一条） | 是 | **周节奏、人复核**：trace_metrics 产出 YAML 骨架，人看分母后 append，非每次反馈自动写；结构由 `verify_metrics.py --check`（CI）校验 |
| `docs/metrics.md` | metrics 机制文档（定义/口径/流程） | 是 | **稳定层**：只承载机制解释（人读理解），不随每期数据变动 |

要点：**每次反馈直接写的是 case 文件（confidence）**，那是学习环的持久状态；metrics 数据是周期性的观测汇总，不是反馈的即时回写。反馈回写 case 后应作为变更提交（groom 批次或独立小 PR），演示可随 commit，正式使用走门控。

### 2. 知识注入（每次定位后）

to-postmortem 接受任意来源的调查记录（本地 session、外部对话、手工笔记、wiki 导出），提取症状、根因、修复，脱敏后进入 `postmortems/inbox/` 待审队列。groom 批处理：预分诊为 new_pattern / variant_of / covered_by 三类并附证据，人审后分别升格为新 case、并入已有 case（扩展版本区间）、或仅转正为 Tier 3 语料（人工沉淀按周批处理；issue-ingest 等自动化源的草稿 verification 链完整，可直接升格，不等周批）。判定为已覆盖的记录不丢弃，它仍是检索语料和未来 fixture 的来源。

### 3. 误诊归因（每次误诊后）

误诊发生时，先读 trace 判断错误在哪一侧：trace 显示检索与检查执行都正确、但根因判断错误，是 case 错，修知识库；trace 显示跳过了 fallback、加载了错误命名空间、漏标了低置信，是执行错，修 skill 流程。这个区分防止一种具体的腐化：在执行出错时误改本来正确的 case。没有 trace，两种修复会混在一起，改坏正确的知识只是时间问题。

### 4. 结构演化（按闸门触发）

知识库的结构本身也在演化，但由数据触发而非预先规划：命名空间达到容量 80% 时 groom 预告拆分（首选拆分轴是 category，目录迁移与索引重建同一 PR 完成）；路由准确率持续偏低时，从 trace 的路由错例提取 triage-tree 修订建议，走高风险双签合入（roadmap E2，v1.5）；trace 结构挖掘报告低判别力的 quickly_check 与噪声分支（roadmap E5，v2）。容量预告已实现，后两项在路线图上。

### 5. 退休与复活（每周）

版本区间过期、或长期被选中却未解决的 case 软退休进 `_archive/`，自动退出活跃索引；从未被选中的 cold case 不退休，罕见但正确的知识占索引成本极低，误删是静默损失。`_archive/` 中的 case 在新的 compat 区间出现时可以复活（例如某框架 2.7 引入的缺陷在 2.8 修复，相关 case 先退休后恢复）。退休不是删除：trace 历史与 postmortem 全部保留。

## 护栏：演化为什么不腐化

每个演化机制都配一道对应的护栏，防止系统越学越错：

| 演化动作 | 护栏 | 挡住什么 |
|---|---|---|
| confidence 回写（S1） | 只按已回报的结果回写；串联保护（两次未解决即转人工） | 误诊级联 |
| validation_record 结算（S2） | self-referential 隔离（replay issue = case 来源 → self_consistent 不虚增）；consistent ≠ 现场 resolve（口径不混）；inconsistent 走 case 复审 | 自证虚高、把"找得到"冒充"用得上" |
| 新 case 升格 | inbox 人审 + 语义校验 + 高风险双签 | 错误知识入库 |
| agent 自起草候选 | 初始低 confidence，必须经 groom 验证 | 未验证知识被当作已验证 |
| 预分诊 / 置信度重算 | 只产出建议与证据，决定权在人 | 自动化误判直接生效 |
| 知识库增长 | 每命名空间 30 条上限、值重复检测、合并建议 | 检索质量退化 |
| skill 流程修改 | golden 回归（改前后对照）+ CODEOWNERS 审批 | 流程回归 |
| 审查质量 | 随机审序；高风险变更强制深审，不走快通道 | 审查疲劳与惯性通过 |

两个横切设计贯穿所有护栏。

其一，建议与决定分离。所有自动化环节（预分诊、候选 case 起草、置信度重算）只产出建议加证据，采纳、调整或驳回永远由人执行。自动化负责压缩人的工作量（单条知识从二十分钟降到半分钟），不接管人的判断。

其二，一切升级由数据触发。embedding 预分诊、路由自学习、结构挖掘都有明确入口闸门（见 roadmap），闸门数值本身每季度用实测指标复核。不按日历排期，也不追随技术趋势；[ADR-0002](adr/0002-retrieval-no-rag-lightweight-index.md) 的检索决策重评条件是这一原则的典型样例。

## 数据回路：trace → metrics → 闸门

演化的节奏由数据决定。trace 汇入 `scripts/trace_metrics.py`，计算路由准确率、反馈捕获率、Tier 3 挽救率等指标（数据落 `metrics/timeline.yaml`，定义见 [metrics.md](metrics.md)）。指标驱动两类决策。运营层面，路由准确率低则修 triage-tree，路由准但未命中高则补 case；架构层面，ADR 的重评触发条件是否命中、roadmap 闸门是否解锁。trace 历史永不删除，它是这套系统全部自我认知的数据来源。

## 当前状态

机制 1（confidence 回写）、2（知识注入）、3（误诊归因）、5（退休复活）已实现；机制 4 的容量预告已实现（inference/vllm-ascend interrupt 81/30 超 hard_cap，EV-006 健康指标评估判暂不拆），路由演进与结构挖掘在 roadmap（E2、E5）。真实闭环已运转：123 条 case、7 张 EV 卡全 validated、自动化 ingest 升格 5 case、S2 校准集 20 条、L3 季度自评框架完成 dry-run 预演（2026-Q3）。self-evolve 机制工程面重构（PR #104，2026-09）落地：S2 feedback 回流到 case validation_record、归因事件按需聚合、过度设计清除。完整机制细节见 [evolution-pipeline.md](evolution-pipeline.md)。
