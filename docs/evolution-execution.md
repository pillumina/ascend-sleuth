# 执行链路：proposal 契约、follow-up 验证与效果度量

> 本文是 [evolution-pipeline.md](evolution-pipeline.md) 的**执行级规范**：机制总览（三层闭环、分级授权、状态机、落地节奏）在那边；本文回答执行时的问题——**一条 proposal 到底要记录什么信息、改动的验证如何区分"合入前可判"与"合入后需真实反馈"、一次知识沉淀的效果怎么度量、agent 在每个决策点拿到什么。** 把"一轮自演进"作为一个可审计会话来运行（人怎么下指令、目标函数与停止条件、token 预算、自我指涉治理）见 [evolution-orchestration.md](evolution-orchestration.md)；从一条指令到持续运行（长期任务、issue 评测循环、执行记录、可视化）见 [evolution-run.md](evolution-run.md)；面向使用者的指令/报告语言见 [evolution-user-guide.md](evolution-user-guide.md)。
> 推导依据：原则一（验证先于交付）、二（不变量写进结构）、五（建议与决定分离）、七（变更可逆）、八（可观测先于改进）、九（资源预算）、十一（数据触发）；理论见 design-theory §4.2–4.4。**本文自身修订 = L3 结构（methodology PR + 体系维护人审）。** 未来落成 skill 时，执行参数须内联进 SKILL.md（skill 自包含纪律），本文退为可选论证层。

## 1. 为什么需要执行级规范：机制闭环的四个执行空洞

v2 机制把"观测 → 候选 → 授权 → 合入"串起来了，但执行时 agent/评审人仍会卡在四个空洞：

1. **proposal 的"可执行性"无契约**——一张卡写"修订 triage 分支 vllm-ascend 启动参数族"，agent 不知道：改哪几行、现状行为是什么、怎么算改完、改完影响谁；
2. **真实反馈类改动缺 follow-up**——对依赖真实场景的改动（content/fix），旧机制只验证到"合入时 golden 通过"，没回答"这条改动在真实使用里真的改善了吗？没改善算谁的责任、何时回滚"（即时判定类已在合入前由 S2/golden 验证，不在此列）；
3. **"每次沉淀效果"没有定义**——知识库整体有命中率，但"这次 to-postmortem/to-reference 沉淀的那条 case 是否有效"无度量：沉淀时没有预期，沉淀后没有跟踪；
4. **agent 执行时信息供给不足**——决策点只有聚合值，没有执行所需的完整证据与历史先例。

**统一框架：把每条 proposal、每次沉淀当成一次带预期的实验。** 执行前写下可测的 `predicted_effect`/`predicted_value`，执行后进入 follow-up 观察窗，对照预期判定（达标 / 再迭代 / 回滚），判定结果写回卡、指标、台账。合理性不是合入那一刻的静态判断，而是"预期 → 实测"对照的动态闭环。

## 2. Proposal 信息契约（skill/流程优化）

适用：改 skill 步骤、triage 分支、quickly_check、script、提示词。字段目标：**agent 拿到卡能回答"改哪、现状是什么、怎么算改完、影响谁"**。

| 字段 | 内容 | 缺了会怎样 |
|---|---|---|
| `target_component` | 组件 ID（skill:diagnose step3 / triage:vllm-ascend-startup / script:build_index / check:507018-p） | 不知道改哪，或改错组件 |
| `baseline_behavior` | before 快照 + **1–3 个具体反例**：输入（症状/日志原文或充分证据）+ 当前错误输出。反例来自 trace/issue/postmortem | 无法验证"改完是否真的变了"——无 before 的 after 无意义 |
| `edit_semantics` | 编辑语义：add/delete/modify + 新旧规则对照（可 diff 形态） | 只给方向不给处方，agent 自由发挥改偏 |
| `affected_paths` | 该组件被哪些下游流程引用（谁调它、影响哪些 namespace/category） | 修好 A 弄坏 B（改 triage 影响全部诊断） |
| `hypothesis` | 因果链：触发信号 → 归因（组件错）→ 为什么这样改能修好 | 处方与诊断脱节，改了错的地方 |
| `predicted_effect` | **可测预期**：mis 率 X→Y / 该类 issue 命中率升 Z / 错例复测归位率 | follow-up 判定的基准缺失 = 无法证伪 |
| `verification` | 验证数据（S2 校准 / golden / 台账）+ before/after 测法 + 观察窗长度（见第 5 节） | 不可证伪的变更不该合入 |
| `rollback` | 回滚方式（revert / 分支丢弃 / 配置开关） | 原则七落空 |

**脱敏纪律（信息完整性与隐私的张力）**：卡入 git，只含聚合值与**证据引用**（trace 路径 + 事件索引 / issue 号 + 段落号），**不含客户现场原文**（与 eval fixture 同一纪律，见 .gitignore 注释）。原文留在本地 `traces/evidence/`，同文件系统内执行 agent 可读；跨机器/分享时如实降级为摘要并标注缺失（诚实退化），不伪造"证据已含"。

## 3. 知识沉淀 proposal 契约（case / reference）

适用：to-postmortem / to-reference 产出、groom 三分类、Tier3 转正。与 skill 优化的区别：问题不是"改什么"而是**"值不值得沉淀 + 沉淀后有没有效"**。

| 字段 | 内容 | 判定用途 |
|---|---|---|
| `source_evidence` | 来源（issue/trace/postmortem id）+ 现象/日志/根因证据引用 | 证据充分性判定（缺证据的低置信沉淀） |
| `sediment_form` | 新 case / variant 并入 / reference / Tier3 转正 | 决定验证方式与审批路径 |
| `evidence_strength` | 症状/根因/fix 三证据各自强度：确证 / 推测 / 缺失 | 初始置信度（investigation_quality 对应物）与诚实标注 |
| `verification` | 来源验证状态：`upstream-fix-merged`（fix PR 合入）/ `upstream-maintainer-confirmed` / `investigation` / `engineer-report` | **初始 score 先验档位**（与 evidence_strength 区分：strength=调查判断，verification=外部证据强度）——见 groom 置信度重算规则表 |
| `discriminative_power` | quickly_check 能否区分同 namespace 相似 case（对比候选） | 防重复沉淀、防低判别力污染候选集 |
| `predicted_value` | **预期命中场景**：这条沉淀预计命中哪类未来问题（可检验的描述，见第 4 节） | 沉淀效果度量的对比基准 |
| `ref_knowledge` | 关联的 active reference（role 合法，verify_references 校验） | 已有机制，沉淀时一并评估 |

## 4. 沉淀效果度量：每次沉淀 = 一次带预期的实验

### 4.1 三段闭环

```
① 沉淀时：记 predicted_value（预期命中场景）+ expected_window（观察窗，如 4 周或 N 次同类诊断）
② 沉淀后：跟踪该 case 的 first_hit（首次被选中时间）、选中后 resolve、在预期场景类中的选中率
③ 观察窗结束判定（resolve 的判定必须区分信号来源，见下）：
   ├─ 被选中且 resolve（S1 现场确认）  → 沉淀有效（记 metrics: sediment_value，高置信）
   ├─ 被选中且 retrieval-hit（仅 S2/golden 检索命中）→ 沉淀"检索有效"（低置信，标注 source: issue-replay，
   │                                    不算现场解决——只证明"找得到"，不证明"用得上"）
   ├─ 从未被选中            → 区分两种归因：
   │                          a. 预期场景没出现（预测偏差，非沉淀之过）
   │                          b. 场景出现了但没选中它（判别力/覆盖问题 → 该 case 需复审）
   └─ 被选中未 resolve      → 沉淀有误 → 走误诊归因（case 错改知识 / 执行错改流程）
```

**resolve 数据源限定（方案级关键）**：沉淀判定的 **resolve 只认 S1（工程师现场反馈）**——S2/golden 只能证明"检索命中该 case"（retrieval hit），不能证明"该 case 在现场解决了问题"。理由：case 的核心价值是 fix 在现场有效，检索命中只是必要条件。因此：
- 有 S1 确认 → `sediment_value`（高置信沉淀有效）；
- 仅 S2/golden 命中 → 记"检索有效"但标注 `source: issue-replay`、降置信（诚实标注，execution §4.3）；
- 无任何命中 → 归因（场景未出现 vs 判别力问题）。

**与 verification 的分层（内容置信 ≠ 现场置信）**：`verification`（来源验证：fix PR 合入等）提高的是**内容正确性先验**——根因/修复被外部验证过，case 内容可默认可信；但 **resolve（现场有效）仍只认 S1**。两者独立：fix-merged case 初始 score 高（内容可信），不等于它在任意客户环境都被验证过——现场确认仍需 S1 回报。verification 只给冷启动先验，不替代 S1 校准（见 groom 置信度重算规则表）。
此限定防两件事：把"找得到"冒充"用得上"（虚报沉淀价值）、把 S2 检索 miss 当成 case 内容错去改知识（污染正确 case）。

### 4.2 需要的记录扩展

- **case YAML 扩展**（相对现有 confidence 字段）：`predicted_value`（沉淀时写，人/groom 可改）、`first_hit`、`expected_window`。`confidence`（hits/mis/score）语义不变——沉淀效果度量复用它做 resolve 侧，新增字段做"预期对照"侧。
- **first_hit 的数据源限定（防 S2 replay 虚增）**：`first_hit` 指该 case 在**真实诊断**中被选中的首次时间（trace hit 事件，S1 侧）——**S2 replay 的检索命中不计入 first_hit**。若不限定，S2 批量 replay（一天几百条 issue）会让新沉淀 case 的 first_hit 立即触发，把"检索到"冒充"真实诊断选中"。S2 命中只作为"检索有效"旁证（§4.1 降置信路径），不进 first_hit/resolve 统计。区分口径：first_hit/resolve = 真实诊断侧；retrieval-hit = S2/golden 侧，两套计数分开。
- **groom 职责扩展**：每轮 groom 检查进入观察窗的沉淀（到窗未判定 → 标红提醒）；判定结果写回卡/索引。
- **反馈到源头**：某 issue 源（如 vllm-ascend 池）的沉淀连续预测不准或从未命中 → 调 `issue_filter.py` 的价值启发式，**而不是继续堆沉淀**——这使"沉淀质量"从 to-postmortem 环节延伸到 issue-ingest 的筛选环节（原则十一：数据回流到假设）。

### 4.3 诚实标注

- 观察窗未结束的沉淀：状态 `awaiting_validation`，不冒充已有效；
- 无 S1 反馈、仅 S2/golden 佐证的沉淀：指标标注 `source: issue-replay`，与 S1 口径分开（见 6 节）；
- "从未被选中"≠"沉淀失败"——若预期场景本身没出现（该框架版本无人用），如实记"场景未出现"，不把预测偏差当案例错误。

## 5. Follow-up 验证链路：proposal 改动后的合理性

### 5.1 状态机：EV 卡 = agent 决策档案（权威定义在 pipeline.md §7 v4，此处只重复关键语义）

**关键原则：EV 卡的终态是 agent 依据 eval 的判断，不是"合入"语义。** 一个 proposal 从执行
修改到 eval 检查"改动是否真解决问题"都在提 PR 前做完；agent 判断采纳（validated）或不采纳
（rejected）基于合入前可得的验证（S2/golden/台账复测）。**攒批、提 PR、人审合入是流程层**
（session/批边界）的事，不进卡状态——人审发生在目标态完成/降级完成时，审视整个自演进过程
是否 solid（含 rejected 卡——诚实实验记录）。

```
● 即时判定类（检索/路由/skill 流程/脚本——S2/golden 可即时出结果）：
   candidate ──► in_experiment（action + eval）──eval solid──► validated（agent 采纳：改动保留）
        │                                 └──eval 不成立──► rejected（agent 不采纳：留结论）
        └──发现更好方向──► superseded（新 proposal 替代）

● 真实反馈类（content 沉淀 / fix 有效——现场有效性只能等真实场景/S1）：
   candidate ──► in_experiment（实现 + S2 佐证）──agent 判 validated（采纳：已实现 + S2 佐证）
        │              └──实验失败──► rejected
   validated 后：现场有效性进入观察窗（流程层跟踪，非卡状态）——S1 确认/退化/超时结果作为
   **追加 decision 记录**到卡（"PR #N 合入"、"观察窗 S1 确认现场有效"、"现场退化已回滚"），
   不改变卡状态（卡状态 = agent 决策的终态；观察窗是效果结算层）。
```

**状态词表与 schema 的唯一事实源是 pipeline.md §7（v4）**：EV 卡 status 词表
（candidate/in_experiment/validated/rejected/superseded + 蓝图态 stale——**不含
pending_merge/adopted 等 git 合入态**）、supersedes/superseded_by 替换链、
estimated/actual_cost 成本字段都在那边定义，本文不重复定义只引用——防两处状态机再次漂移。
**注意对象区分**：`awaiting_validation` 是沉淀对象（case）的观察窗状态（§4.3），属 case 的
跟踪字段，不是 EV 卡 status——两种对象不混用词表。

### 5.1a 观察窗超时降级（蓝图态：触发条件到才启用，见 pipeline §11.1——S1 断供持续 ≥2 期后，此前用"标存疑 + 提醒人"轻量处理）

> 设计保留：以下为完整机制设计。第一批落地（Phase A–D）不实现正式降级态，观察窗到期无反馈时以"存疑标注 + 面板提醒"兜底，人可补反馈或回滚。

content/fix 类观察窗依赖 S1 现场反馈，而反馈可能长期断供（当前捕获率≈0 是现实）——若没有超时结算，沉淀永久 awaiting_validation、已采纳改动（validated）的现场有效性永远悬空，follow-up 机制在"永远等答案"中空转。超时处理按观察窗长度分级（默认：即时类=无超时、content 类=expected_window ×2、fix 类=最长窗 ×2，参数落地校准）：

```
观察窗到期未结算（无 S1 反馈）——按对象分列（EV 卡与沉淀 case 状态机不同，不混用）：
● EV 卡侧（validated 已采纳改动的现场效果结算——追加 decision，不改卡状态）：
├─ 有 S2/golden 检索命中证据 → 追加 decision"检索有效、现场未确认"（unconfirmed_valid 语义，
│     效果按 source: issue-replay 入指标，不无限滞留）
├─ 无任何命中证据 → 追加 decision"观察窗超时无证据"（unconfirmed 语义）：如实标注存疑，
│     不冒充有效；触发降权信号（证据不足，重审或回滚候选）
└─ 有退化证据（S2 miss 增长）→ 追加 decision"现场退化，已回滚改动"（rolled_back 语义，不等 S1）
● 沉淀 case 侧：awaiting_validation 到期 → 按 §4.1 结算——有 S1 → sediment_value；
  仅 S2/golden 命中 → "检索有效"标注；无命中 → 归因（场景未出现 vs 判别力）
```

规则：**观察窗不是无限等待**——到期必结算，结算结果作为**追加 decision** 记录到 validated 卡
（如实标注证据强度：有 S1=S1 / 仅 S2=检索有效 / 无证据=存疑），**不改变卡状态**（卡状态 =
agent 决策终态；观察窗是流程层效果结算）。与 §4.3"到窗标红"的关系：标红是提前提醒（人还有
机会补反馈），超时结算是最终兜底（人不补就如实标注，不无限等）。

**结算后的后续动作（防积压悬空）**：观察窗结算为存疑/未确认的改动不悬空——它们可继续参与演进：
- **可被 supersede**：新卡可在未确认的改动上提出替代（未确认说明原方案现场证据不足，正是"更好 idea"的适用场景），supersede 规则同 run §5；
- **可重新验证**：无证据存疑的改动可开新卡重新设计验证方案（补 S2 证据或改验证设计）；
- **积压清理**：季度自评统计"观察窗未确认"改动占比——占比高说明 S1 断供或验证设计系统性不足，触发流程改进（追问话术/O3）而非继续堆积；
- **口径纪律**：观察窗未确认（仅 S2 佐证）不计入"现场 validated"统计（execution §6 的 validated 计数与回滚率口径不含未确认项，避免稀释"真验证"统计）。

### 5.2 观察窗按变更类分（不是所有验证都等现场反馈）

| 变更类 | 验证数据 | 观察窗 | 判定基准 |
|---|---|---|---|
| 检索/路由（triage、case quickly_check、_index） | S2 issue-replay 校准集 | 即时（replay 不等现场） | 命中率 / 路由准确率 before/after |
| skill 流程（diagnose/groom 步骤、脚本） | S2 + golden 回放 | 即时～数周 | 组件 mis 率、错例复测、golden 无回归 |
| content（新 case/reference 沉淀） | 后续真实诊断 + S2 | 数周～数月（等场景出现） | predicted_value vs 实际命中/resolve（第 4 节） |
| fix 有效类（改 fix 内容、severity） | S1 工程师反馈 | 长（依赖现场回报） | 反馈 resolve；断供即如实等待 |

### 5.3 判定后写回

- 卡：agent 判断后 status 更新 + `decisions` 追加（谁、何时、依据哪份 eval 数据、采纳/不采纳结论）；观察窗结算追加 decision（不改卡状态）；
- 指标：validated → `metrics/timeline.yaml` 记一期效果差（改前基线 vs 改后实测）；观察窗结算"现场退化回滚" → 记录并计入回滚率；
- 台账：validated → 组件记 hit；观察窗结算"退化" → 组件记 mis + 教训摘要（防同类重复提案——组件台账即决策记忆）。

## 6. Metrics 分层：每个指标回答一个决策问题

指标消费方三问（谁决策、答什么问题、不答会怎样）先行，**答不了任何决策问题的指标不采集**（roadmap「指标消费方三问」纪律）。分四层，口径互不混淆：

| 层 | 指标 | 回答的决策问题 | 数据源 |
|---|---|---|---|
| 机制健康（流水线自身） | 候选→采纳率、实验→通过率、信号误报率、抽审发现率、**回滚率** | 流水线是否在做对的事？信号是否误报？auto 授权是否过宽？ | proposals/ideas、decisions、回测记录 |
| 知识质量（库整体） | 命中率、resolve 率（S1）、误诊率、路由准确率、判别力、覆盖缺口 | 知识库整体在变准吗？哪个格子弱？ | trace_metrics + _index 头注 |
| 单次沉淀效果 | 预期 vs 实际命中、first_hit 延迟、选中后 resolve | 每次沉淀是否有效？哪个来源产低质沉淀？ | case 扩展字段 + groom |
| skill 组件质量 | 台账 mis 率、每次 skill 变更前后差 | 哪个组件反复错？这次 skill 改动有效吗？ | component-tally + 回测 |

口径纪律（沿用 docs/metrics.md）：比例带分母；分母 <10 显式标注；`source: live / replay / issue-replay` 必标；无数据如实不写。回滚率是新进指标——它衡量"合入闸门放错了多少"，是授权级别校准（6.3）与季度自评（6.6）的输入。

## 7. Agent 决策点信息供给：执行质量的上限 = 供给完整性

当执行/评审交给 agent 时，每个决策点明确供给什么。**信息契约（2/3 节）不是文档装饰，是 agent 能正确执行的前提。**

| 决策点 | 供给清单 | 缺失后果 |
|---|---|---|
| 执行 skill 优化 | 目标组件当前全文（SKILL.md 相关节 / triage 分支 / script）+ before 反例**原文**（非摘要）+ affected_paths + **历史先例**（该组件在台账/历史卡里被改过吗？结果如何） | 盲改；重复提交失败过的提案 |
| 执行沉淀评估 | 来源 issue/trace 原文（或充分证据）+ 同 ns 现有相似 case 全文（判重复/判别力）+ 覆盖矩阵缺口 | 无法判判别力 → 重复/低质沉淀入库 |
| 评审（reviewer 角色） | 卡 + before/after diff + predicted_effect vs verification 结果（30s 判定） | 评审变橡皮图章或被迫开全文 |
| 季度自评 | 四层指标聚合 + 跨期对比 + 回滚案例 + 抽审发现 | 元层审视无依据 |

**分层供给控预算（原则九）**：决策点先给卡（聚合 + 证据引用），判定前才展开证据原文；只有进入 follow-up 判定的卡才加载完整回测数据。**不追求"把所有信息都给 agent"**，追求"每个决策点恰好给够判定所需"——信息不足与信息过载同样损害执行质量。

**台账即决策记忆**：组件失败台账 + proposals/reviews 历史 = agent 的"这个组件以前怎么改、结果如何"的记忆（对应 SkillOpt 的 reject buffer / meta-skill 思路，但载体是本仓库的词法台账，不是模型内隐状态）。

## 8. 与现有机制的关系

| 本文 | 对接的现有机制 | 关系 |
|---|---|---|
| proposal 契约（2/3 节） | evolution-pipeline.md §7 schema | pipeline.md 定义状态机与最小字段，本文定义执行级完整字段（主从：落地 schema 以本文为准扩展） |
| 沉淀效果度量（4 节） | case confidence、groom R 轮次 | confidence 语义不变，新增 predicted_value/first_hit/expected_window，groom 加"观察窗结算"职责 |
| follow-up 验证（5 节） | M2/M3（replay）、S2 校准集、feedback 结算 | 观察窗的即时判定依赖 M2/S2；S1 类依赖 settle_trace_feedback |
| metrics 分层（6 节） | metrics/timeline.yaml、trace_metrics.py | 新指标进 timeline 须 verify_metrics.py 结构校验扩展（按准入三条件评估） |
| agent 供给（7 节） | 组件台账（metrics/component-tally.yaml，pipeline.md §2） | 台账是供给的"决策记忆"载体 |

## 9. 原则追溯

| 设计元素 | 服务的原则 | 说明 |
|---|---|---|
| proposal 带 baseline/predicted_effect/verification | 八、一 | 无 before/预期/验证不可判定，验证先于交付 |
| 卡 schema 强制字段 | 二 | 不变量写进结构（落地评估 CI 化） |
| follow-up 观察窗 + validated 终态 | 一、七 | 合理性在效果确认时判定，不在合入时；观察窗内可回滚 |
| 沉淀 = 带预期的实验 | 八、十一 | 每次沉淀可评估；数据回流到 issue 筛选假设 |
| 台账即决策记忆 | 八 | 历史先例防重复失败提案 |
| 分层供给控预算 | 九 | 每个决策点恰好给够，不追求全量 |
| 脱敏纪律（引用不含原文） | 十 | 信息完整与隐私冲突时诚实降级 |
| 回滚率指标 | 六、十一 | 合入闸门质量可度量，校准授权级别 |

## 10. 落地顺序（执行契约维度；**整体落地总纲见 pipeline.md §11**，本表是本文所述契约的落地细化，不平行于 §11）

| 步骤 | 内容 | 入口闸门 |
|---|---|---|
| 1 | proposal schema v3 落 `proposals/ideas/` 模板（随 §11 Phase A 同批） | owner 确认 |
| 2 | 沉淀效果字段（predicted_value/first_hit/expected_window）落 case schema + groom 观察窗结算 | 首次真实沉淀批量存在 |
| 3 | follow-up 观察窗常态化 | M2 或 S2 校准集可用（即时判定类） |
| 4 | 回滚率/采纳率等机制健康指标进 timeline | 自演进执行流程试点 ≥1 轮 |
| 5 | agent 供给清单固化为执行 checklist（未来 skill 载体） | 步骤 1–3 有真实执行记录 |
