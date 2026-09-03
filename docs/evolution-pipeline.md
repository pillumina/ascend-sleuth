# 演进流水线（v2）：三层自演进闭环与自演进执行流程

> 本文回答一个问题：**系统如何闭环地改进自己的三层资产——知识内容、流程/skill、以及工作流本身——并把"人的参与"从逐条执行上移到流程审视。**
> v1（本文件旧版）只覆盖知识内容层的候选 idea 闭环；v2 扩展为三层模型（L1 知识内容 / L2 流程与 skill / L3 工作流与编排），并新增第 6 节「自演进执行流程」——一个降低人工参与度、但每次改动可追溯、每次合入必须由实验数据驱动的专门流程。**执行级信息契约（proposal 要记录什么、验证如何区分合入前可判与合入后需真实反馈、沉淀效果怎么度量、agent 拿到什么）见 [evolution-execution.md](evolution-execution.md)；编排与治理层（会话如何启动、目标函数与停止条件、token 预算、自我指涉治理）见 [evolution-orchestration.md](evolution-orchestration.md)；从一条指令到持续运行的运行视图（长期任务、issue 评测循环、执行记录、可视化）见 [evolution-run.md](evolution-run.md)；面向使用者的指令/报告/干预语言见 [evolution-user-guide.md](evolution-user-guide.md)。**
> **实现分级声明**：本文是**完整设计蓝图**，非全部待办。落地时只实现 §11.1「必需」列的机制；「蓝图」列（超时降级态、stale、策略记忆、稳态降频等）是预测性设计，**触发条件（数据/用户诉求）出现才激活**——不为未发生的问题预建全量机制（防过度设计，仓库原则十一）。
> 对象层闭环（case 越用越准）已在 [evolution.md](evolution.md) 落地；理论推导见 [design-theory.md](design-theory.md) §4.2–4.4（元层信念、自演进闭环、演化即假设检验）；原则依据见 [design-principles.md](design-principles.md)。**本文自身的修订走 methodology PR + 体系维护人审（它属于 L3 结构，受本文第 5.2 节管辖）。**

## 1. 三层模型

| 层 | 对象 | 闭环的完成定义 | 当前状态 | 自动化边界 |
|---|---|---|---|---|
| **L1 知识内容** | case、reference、triage-tree 内容 | 知识随使用变准：命中率升、误诊率降 | ✅ 已闭环（evolution.md 五机制） | groom 预分诊自动、人审转正；E4 auto-promotion 在 v2 池 |
| **L2 流程与 skill** | diagnose/groom/to-* 实现、triage 分支、scripts、新 skill | 流程随误诊变对：执行错率（按组件）下降 | ⚠️ 半闭环（归因事件入 trace、按需聚合脚本已就绪；无真实归因事件积累、验证门有设计无常态数据、无回测） | 归因自动、修复建议自动、合入人审（本文 4 节设计补全） |
| **L3 工作流与编排** | 流水线、groom 节奏、roadmap 机制、本文档 | 流程本身不腐化且参数被数据校准 | ❌ 未闭环（人季度回顾，参数不回流） | 参数级自校准半自动；结构级演进留人（本文 5 节） |

一条流水线服务三层：信号源相同（trace / metrics / 容量 / 回放），候选 idea 标注所属层，各层走各自的验证与授权路径。**L1 的闭环是 L2/L3 的数据前提**——但"反馈数据"不只有工程师回报一种形态，见第 2 节评分源分级：对已闭环 issue 的 diagnose replay 校准（以 issue 实际 resolution 为 ground truth）是不依赖人的自动评分源，可部分替代工程师反馈支撑检索/路由类演进。

## 2. 三层共用观测基座：归因事件入 trace，按需聚合（无预建台账）

现状的误诊归因是二分：`case 错（改知识）/ 执行错（改 skill）`。二分对 L2 不够——"执行错"内部没有结构，改 skill 仍靠人工定位。**2026-09 selfevolve-loop 重构**：原"组件失败台账（metrics/component-tally.yaml 常驻表）"形态是过度设计——0 归因事件建表空转、无 hit 侧 score 恒 0、把 diagnose 输出与 expected 不符一律硬归因 triage 不精确。第一性替代：**归因事件本身就是数据，入 trace；报告按需生成，不预建表**（原则十一：数据触发演进）。

- **组件 = 可寻址的执行单元**：skill 的某个步骤（编号）、triage 的某个分支、某条 quickly_check、某个 script、某段提示词。每个组件有稳定 ID（skill 步骤号 / triage 分支名 / check id / 脚本文件名），归因事件才能指向它。
- **trace 归因事件（数据本体）**：diagnose 在反馈 not_resolved/partial 后现场写 attribution 事件，verdict ∈ {case_error, execution_error}；判 execution_error 时可选加 `component: <组件ID>`（可寻址执行单元，判定不了如实不填——不编造）。trace 同时记录"命中了哪些组件"的 evidence（hit 侧，自然产生）。
- **按需聚合（无常驻表）**：深度轮/季度自评需要时跑 `scripts/component_tally.py`，从 traces 的 attribution 事件 + `.s2-replay/attributions.yaml`（S2 路由 miss 候选）现聚合失败簇——有簇才考虑沉淀成 L2 修复候选（修订该组件所在 skill 步骤 / triage 分支），无数据如实空转。脚本不写任何常驻状态文件（天然幂等）。
- **S2 归因诚实化**：s2_replay `--collect` 只报"路由 miss 事实"（对照人工预标 `expected.namespace/category`），verdict=candidate——route miss 可能是 triage 正则错 / agent 推理错 / 优雅退化，S2 无法区分，组件归因需人/trace 确认后才可指向修复，不冒充 execution_error（那是 diagnose S1 侧职权）。

**L2/L3 指标（全部从已有 trace/metrics 派生，不新增采集面）**：按组件执行错率（按需聚合时算）、skill 变更前后回测差、idea 采纳率/回测通过率、信号误报率（触发了却被否决的候选占比）。这些是**系统自身行为的观测**，不是对人或协作的观测——与 roadmap「明确不做 KPI/身份/使用观测」的边界相容性见 5.3 与 9 节。

### 2.1 评分源分级（"反馈数据"不只有工程师回报）

演进闭环需要"这次改动是变好还是变坏"的判定信号。按**反馈对象**分（不是按"谁给的"分级）——S1 与 S2 度量不同对象，都该结算，各管各的：

| 源 | 反馈对象 | 判定什么 | 结算落点 | 可得性 |
|---|---|---|---|---|
| S1 工程师回报 fix 结果 | **现场有效性**：fix 在**这个用户环境**是否解决 | case 的 confidence.hits/mis（resolve 口径，唯一依据） | `case.confidence` | 依赖人，当前捕获率≈0 |
| **S2** Issue-replay 对照 | **内容正确性**：case 的 symptom→rc→fix 描述是否与外部 ground truth 一致 | 命中且结论一致 → `validation_record.consistent`（内容被外部验证，排序优先）；命中但结论不符 → `validation_record.inconsistent`（**复审信号**） | `case.validation_record`（settle_s2_feedback 结算） | 全自动，无人工；数据源 = 上游已闭环 issue |
| S3 golden 回放 | **回归防护**：改动后不倒退 | 不改 case 数据，只作验证门 | 无 | 全自动，套件人工维护 |

**S2 是补 S1 空缺的关键机制**（对应"仅根据用户的现象 replay diagnose、再按已知根因思考校准"的构想）：它对已闭环 issue 批量做 diagnose replay，产出**与 issue resolution 的对照评分**，不依赖任何工程师回报。issue 本身的 resolution（fix PR 合入 / committer 确认 / issue 内用户反馈）就是 feedback——S2 只是把它系统化。四条用途：

- **验证门数据**：L2 skill 演进的 golden 验证可换成/补充 S2 对照（改 skill 前后在同一批 issue 上命中率是否提升）；
- **case 内容验证回流（2026-09 新增，此前 S2 结果躺在 result 文件不回流）**：hit + 一致 → `validation_record.consistent`（内容被外部验证）；hit + 结论不符 → `inconsistent`（复审候选——内容错/过时/判别力不足的合法证据）。由 `settle_s2_feedback.py` 结算进 case；
- **错例提取**：路由 miss、未命中 case 从 S2 的 miss 自动累积（E2/E5 数据源，不等人回报）；
- **覆盖缺口**：tier2 miss（无 case 命中）→ "该现象族未覆盖（缺 case 候选）"信号。

**S2 miss 的归因边界（保留，防越权）**：一次 S2 **miss（未命中）**有三种可能——(a) 路由错、(b) 缺 case、(c) case 内容错。**S2 无法区分三者**（它只看到"没命中"）。因此：S2 miss 只能产**检索层候选**（查路由 / 查覆盖缺口），**不得据此判定 case 内容错**。但 **hit-with-wrong-conclusion（命中了 case A、结论却与 resolution 不符）不是 miss——它有区分力**：说明 A 的内容/判别力有问题，是 case 复审的合法证据（settle_s2_feedback 的 inconsistent 通道，2026-09 新增）。区分检索有效与现场有效：**consistent = 内容与外部 resolution 一致（检索+归因正确）；现场 resolve 仍只认 S1**（confience 口径不变）。

**S2 的边界（诚实标注，防过度承诺）**：它以 issue 的 resolution 为基准，校准的是系统**检索与内容**是否正确；现场 fix 有效性（severity 语义、环境特异性）仍只能靠 S1。S2 分数进入指标时标注 `source: issue-replay`，不与 S1 混淆（口径见 docs/metrics.md）。若某 issue 的 resolution 仅是 workaround 而非根因修复，标记后降权或剔除（issue 池筛选规则：优先 state_reason=completed + 维护者 closed + fix commit 可溯的）。

**S2 校准集：selection/test 分离是规模闸门，当前单池运行**（2026-09 降级）：原设计分 selection（gate 用）/ test（validated 终判用，防对校准集过拟合，对应 SkillOpt held-out）。**当前池子（9 条）撑不起两半**——test 半要求"从未被本系统沉淀过的历史 issue"，而沉淀会消耗池子，9 条下 test 半无法成立还自相矛盾。降级规则：**池子 ≥30 条且沉淀/评测解耦成熟后再分两半**；当前单池运行，replay 分数标注 `source: issue-replay`，validated 终判诚实标注"无 held-out test（池小），依赖 selection 对照 + 人工抽审"。**self-referential 隔离（任何规模都执行）**：case 的 validation_record 结算时检查 replay issue 是否正是该 case 的沉淀来源（references 含该 issue URL）——是则记 `self_consistent`（自证，如实标注不虚增外部验证权重）。"先评测后沉淀"的纪律（run §3）持续执行：新 closed issue 先过 S2 评测再允许沉淀为 case。

## 3. L1 知识内容层（已闭环，简述）

evolution.md 五机制 + roadmap A/E 系列已覆盖：confidence 回写、groom 维护、误诊归因改 case、容量治理。本流水线对 L1 只做两件事：

- **承接**：L1 的维护动作（groom 信号表）升级为带 trajectory 的候选 idea 卡（本文 7 节 schema），让"容量告警/路由错例/覆盖缺口"不再止步于动作而进入提案闭环；
- **校正**：误诊归因（case 错 vs 执行错）的判决依据落在 trace attribution 事件上，误改正确 case 的风险下降（evolution.md 机制 3 的直接增强）。

## 4. L2 流程/skill 层（半闭环 → 全闭环设计）

补全四件事（2026-09 重构后：无常驻台账表，归因事件按需聚合驱动）：

### 4.1 归因事件（前提，见第 2 节）

误诊归因写 trace attribution 事件（case_error / execution_error + 可选 component）；S2 路由 miss 记 candidate 归因。没有这些事件，下面三件事都无数据。

### 4.2 归因事件按需聚合 → L2 修复候选

深度轮/季度需要时，`scripts/component_tally.py` 从 traces + .s2-replay 归因事件现聚合失败簇——簇浮出反复失败的组件 → 自动生成候选修复 idea（trajectory = 归因事件 + 对应 trace 引用），建议修复方向（改该组件所在 skill 步骤 / triage 分支 / check / script）。**只产出建议与证据，修复方案与合入留人/分级授权**（原则五）。无失败簇如实空转，不预建表。

### 4.3 skill 变更验证门（强制）

任何 skill/流程改动合入前必须过 **golden 前后对照**（eval/golden + M2 半自动化；容忍 LLM 非确定性用 top-3 断言）。golden 断供或套件不足以区分时，用 **S2 issue-replay 校准**（2.1）替代或补充：改 skill 前后在同一批已闭环 issue 上跑 diagnose，对照 issue resolution 的命中率是否提升。这是 L2 与 L1 的关键差异：改 case 只影响一条知识，改 skill 影响所有下游——验证门不可省，对应原则六（闸门硬度与错误代价匹配）。

### 4.4 新 skill 沉淀触发（弱信号，防过度设计）

只有两类信号可触发"可能需要新 skill/reference"的候选：
- 同一执行错类别反复出现且无归属组件（按需聚合时出现"未归因"簇）；
- 多轮诊断反复走同一 Tier 3 兜底且最终 resolved（说明缺 Tier 2 覆盖，可能补 case 而非新 skill）。

**信号采集内嵌内容流程收尾（evolve-check）**：上述信号 + 更广的伴随信号（沉淀 ≥3 条同
根因 case → 可归纳 reference；同流程重复手动动作 → 可固化脚本/skill 步骤）由
`/skill:evolve-check` 在内容流程（issue-ingest / to-reference / to-postmortem /
knowledge-groom）收尾自动采集——有信号产卡、无信号即止，**不需要用户为"沉淀新 skill"
单独立目标**（演进 = 内容执行的默认收尾，非独立目标轮）。diagnose 不强制收尾跑
evolve-check（高频 + 已有内建 evolving），其 L2/L3 缺口信号由 S2 replay 与深度轮按需聚合
覆盖。候选进**待定池**（不自动立项），
标注"新 skill 立项 = 高风险结构变更，需 proposal 论证与双签"。不做 embedding 相似度
推荐（ADR-0002 锁死）。

### 4.5 效果回测（闭环收口）

L2 变更合入后观测连续 N 期（组件执行错率是否回落、S2 对照命中率、golden 是否保持）；回测不达预期 → 回滚或开再迭代卡。无回测的 L2 变更 = 未闭环，标注"变更已合入、效果待观测"而非假装完成（诚实退化）。

## 5. L3 工作流/编排层（有界闭环）

L3 的闭环不是"流程自动改流程"（递归陷阱），而是**参数级自校准 + 结构级留人**的混合：

### 5.1 参数级自校准（半自动）

流水线自身的执行参数——触发阈值、候选批量、抽审率、授权升级门槛——作为**数据**存配置（如 `evolution/config.yaml`），由季度自评数据校准：某信号长期误报 → 下调触发权重；auto 级抽审发现率高 → 收紧 auto 条件。参数变更是低风险、可逆的（diff 一行），可走快速通道。**参数本身服从原则十一：是假设的量化形态，接受实测修正。**

### 5.2 结构级演进留人

改变流程结构本身——groom 的 R 轮次增减、本流水线的阶段设计、roadmap 机制部分、skill 骨架——一律 methodology PR + 体系维护人审（kb/high-risk 双签）。理由：结构变更是不可逆性最高的变更（影响全部下游与全部后续轮次），没有数据能预证其正确，只能由人基于使用检验裁决（原则五、六、七）。

### 5.3 与「明确不做」的相容性论证

roadmap 不做的是 **KPI / 身份 / 使用观测**（对象是人：工程师 ID、协作时长、每人产出）；本流水线观测的是**系统自身行为**（归因事件簇、信号误报率、idea 生命周期），对象是 trace/卡，不涉人、不引入灌水激励。若未来出现首个集中式多用户部署，再评估是否引入协作维度（roadmap 触发条件不变）。

## 6. 自演进执行流程（专门流程）

### 6.1 定位

一个**受约束的自治循环**：周期性把"系统自身的观测数据"转成"系统自身的变更"，每笔变更可追溯、可回滚、由实验数据放行。它不是无人在环——而是**人的角色从逐条执行上移到两级审视**：内容级抽审（抽查已自动合入的变更）+ 元层级季度自评（审视流程本身是否在做对的事）。**触发方式：内容流程收尾自动（evolve-check）+ 深度轮显式**——内容流程（issue-ingest /
to-reference / to-postmortem / knowledge-groom）完成主体目标后，收尾自动执行伴随评估
（/skill:evolve-check：有信号产卡、agent 自验证、进攒批，无信号即止；diagnose 不强制，
其缺口由 S2 replay 与深度轮覆盖）；用户说"跑一轮自演进/看看有什么可改进"时启动
**深度轮**（全库观测：归因事件聚合/容量/S2 校准集/指标）。两者共用 §6.2 之后的产卡/授权/攒批链，产物同一批池。**防自发批量改库的纪律不变**：evolve-check 只在用户已触发的内容流程收尾运行（不是 agent 自发启动新任务），深度轮保留 disable-model-invocation 语义——评估自动，批量改库仍走攒批 + 人审。

### 6.2 流程总览

```
① 观测    ② 候选      ③ 分级授权        ④ 实验           ⑤ 合入          ⑥ 回测        ⑦ 季度自评
───►      ───►        ───►              ───►             ───►            ───►          ───►
跑信号脚本  起草 idea 卡  按风险/证据分级      golden 前后对照    auto: CI+抽审   观测 N 期      人审视流程本身
汇总聚合值  (带 trajectory)  auto/review/dual  或归因事件复测  review: 人审     指标变化      信号误报率/抽审发现率/
                                                  dual: 双签      不达标→回滚     授权级别合理性/产出质量
   （观测 agent 串行，唯一读写共享状态者 —— git-workflow 纪律）
```

### 6.3 三级授权（降低人工参与的核心机制）

**论证**：原则五"采纳、调整和驳回永远是人"与降低人工并不矛盾——人的决定可以是**预先授权（pre-authorization）**：在特定可机械验证的条件下，把重复性低风险的决定委托给带审计的执行器。仓库先例即 roadmap E4（trusted auto-promotion：近重复 + quickly_check 通过 + 连续 N 次兄弟命中未误诊 → 自动升格 + 月度抽审）。三级授权是把 E4 从 L1 case 推广到全部三层：

| 级别 | 适用 | 条件 | 合入方式 | 兜底 |
|---|---|---|---|---|
| **auto** | 低风险、可逆、机械可验证（content 补 case、reference 修 typo、参数校准、脚本 bugfix） | golden 通过 / 归因事件复测通过 + 变更集可整体 revert + 卡内 decisions 完整 | 自动合入（仍产生完整 PR/commit，CI 硬门） | **月度抽审**：抽审发现错误 → 回滚 + 撤销该类别 auto 授权 |
| **review** | 判断性、中风险（新 case 转正、reference 修订、低风险 skill 步骤调整） | 同上 + 人审 30s/条 | 人审合入 | 随机审序（已有纪律） |
| **dual** | 高风险、结构、不可逆（triage-tree、skill 骨架、新 skill 立项、L3 结构、改 active reference） | 4.3 验证门 + kb/high-risk 双签 | 双签合入 | CODEOWNERS 双组路径 |

**升级门槛（数据触发）**：某类 review 变更连续 N 次回测通过且抽审零发现 → 可申请降级为 auto（记入 config，可随时撤销）；auto 变更抽审发现 ≥1 错误 → 该类别立即退回 review，并在季度自评里复核（原则六：闸门硬度与实测错误代价匹配）。

### 6.3a 运行模式与批提交（人审粒度 = 批；介入度 = 用户启动时选择）

**用户诉求**：agent 应连续工作到目标完成、一次性提一个聚合 PR——每卡一个 PR 等人审会打断自动化流程。设计对齐仓库 knowledge-groom 先例（攒整个 inbox 出一份"变更摘要 + 待审项"给人一次审，不逐条 PR）。

**运行模式（approval_policy，会话启动时在对齐步③确认）**——介入度由用户选，不是系统替他定：

| 模式 | 用户语义 | 各授权级别怎么处理 | 人审时机 |
|---|---|---|---|
| **hands-off（完全自动化）** | "我信这个 scope 的判断，全自动跑，做完给我 PR 审" | auto/review/dual 卡都按**预授权**连续执行，不事中打断；结构级（dual）也自动——**但前提是每张卡有 proposal 记录 + 独立验证门 + 独立 commit**（见下"hands-off 的硬前提"） | 目标完成/批边界 → **一个聚合 PR 人审**（含所有卡，dual 标注高风险）→ 合入 |
| **default（关键人审）** | "自动跑，但关键改动攒批给我审" | auto 即时合入；review/dual 攒批（§6.3a 批提交） | 轮末/批边界 → 聚合 PR 人审 |

**hands-off 的硬前提（用户明确要求，防"自动 = 失控"）**：
1. **每个改动都源于一张 proposal idea 卡**（`proposals/ideas/`，含 trajectory/hypothesis/predicted_effect）——没有 idea 卡记录的改动不允许自动执行，结构级改动尤其如此；
2. **每个改动过独立验证门**（§6.5：无实验证据不合入——hands-off 不豁免，每卡 golden/S2 通过才 commit）；
3. **每个改动独立 commit**（git 全程跟踪，可逐卡 revert）；
4. **验证先于合入——eval 检查改动是否真解决问题在合入前完成**（§6.5 无实验证据不合入）：即时判定类（检索/路由/skill 流程）合入前 eval 通过即 validated（目标态），PR 呈现的是已验证改动；真实反馈类（content/fix）合入前完成实现 + S2 佐证，合入后观察窗等真实场景/S1 才结算其现场有效性（validated/unconfirmed 如实标注）——**不是"合入即算完"：每类改动都有对应的验证确认步骤，只是即时类验证在合入前、反馈类在合入后**；
5. **指标口径红线永保留**（§4：系统不得改评分定义——任何模式）。

**批的定义**：一批 = 一段时间/一段目标内产出的多张卡的改动，攒到批边界合成**一个聚合 PR** 送审。人审的单位是批不是卡。批边界（任一触发即提聚合 PR，防无限攒批）：
- 轮次停止条件触发（§6.2/orchestration §2.2：预算耗尽/产出达标/收敛/人中断）——default 模式的默认批边界 = 一轮；
- 攒批数量达上限（默认 10 卡，参数落地校准）——防单 PR 过大难审；
- **任务级攒批**（hands-off 的默认形态）：用户明确说"做到目标完成再提 PR"时，批边界延伸到长期任务的目标完成点（run §2 任务级）——agent 跨多轮攒批，期间所有卡在"待审"态不进 main，面板显示积压；**风险**：攒批越久，待审改动越晚合入、观察窗越晚开始、冲突风险越大，故任务级攒批须配"批内卡数/时间上限"双保险（上限触发即提前提批，不等目标完成）；**稳态/收敛同样提前触发提批**——某 scope 达 steady（orchestration §2.3）说明该方向已收敛，继续攒批只会积压无意义改动，应结算提批而非无限等目标。**任务级攒批 ≠ 无限攒批**：任何上限（卡数/时间/稳态）都强制提批，用户可续开新任务继续。

**聚合 PR 的结构与可追溯性**：
- 批内每卡**独立 commit**（保卡级回滚粒度）；PR body 按卡列出 EV id、实验记录引用、授权级别、验证结果；
- 人审时**可整体合入，也可按卡打回**（打回的卡 revert 其 commit，其余照常）——打回不阻塞批内其他卡；
- 聚合 PR 的模板按批内最高风险选（批内含 structure 改动 → structure 模板；否则按主要变更类型选），`kb/high-risk` 标在 dual 卡对应 commit；
- 可追溯链不变：卡 → 实验 → 批 PR → 合入 → 观察窗 → 回测（§6.4）。批不削弱追溯，只是把多卡的追溯打包在一个 PR 里。

**批提交不改变验证门与观察窗的分工**：每卡合入前仍需独立验证门（§6.5 无实验证据不合入——批内每卡都有各自验证记录，不是"批级一个验证覆盖所有"）；即时判定类进批时已 validated（合入前验证完成）；真实反馈类批合入后每卡独立进观察窗（execution §5，等真实场景结算）。批只改变"送审粒度"，不放松"验证强度"，也不把验证推迟到合入后。

**升级门槛的 S1 依赖（防 auto 扩权死锁）**："回测通过"的信号来源决定哪些类能升级：
- **S2/golden 可即时判定的类**（检索/路由/skill 流程/脚本——观察窗即时，不依赖 S1）→ 回测通过可正常累积，**可升级 auto**；
- **依赖 S1 的类**（content 沉淀效果 / fix 有效——观察窗要等现场反馈）→ S1 断供时全部走降级态（unconfirmed_valid/unconfirmed，execution §5.1a），**永不"回测通过" → 无法升级 auto**。这不是 bug 而是诚实边界：**没有现场证据就不该给"自动合入知识"的信任**——auto 合入意味着无人逐条审，而 content/fix 的正确性最终只能由现场验证。S1 恢复后（反馈捕获率回升）这类自动恢复升级通道；季度自评应监控"因 S1 断供被锁在 review 的类别"并如实报告（不是流程故障，是数据前提缺失的显式化）。

### 6.4 可追溯契约（每笔改动可追溯）

- 每个候选 = 一张 idea 卡（`proposals/ideas/<EV-YYYY-NNN>.yaml`）：layer、trajectory（触发信号 + 证据出处）、hypothesis、validation、授权级别、decisions 追加式留痕（谁/何时/依据/结论）；
- 每次合入（含 auto）产生完整 PR/commit，PR body 引用实验报告与 idea 卡；变更集整体可 revert；
- 实验记录（`proposals/experiments/`）：golden 前后对照数据、归因事件复测结果，随 PR 归档；
- **追溯链闭合成环**：卡 → 实验 → PR → 合入后回测 → 季度自评 → （若参数校准）回到卡。人随时可从任一合入点沿链回看"为什么改、依据什么数据、谁放行的"。

### 6.5 合入硬规则（数据/效果驱动）

- **无实验证据不合入**：任何层级的任何变更（含 auto），合入前必须有 validation 记录——golden 无回归 / 归因事件复测通过 / metrics 前后对比。这是**硬规则**（reviewer 看到无记录的 PR 必须打回；auto 合入器缺记录即拒绝）；"PR 是否带实验记录引用"能否 CI 化按检查准入三条件（机械可查 / 确定性后果 / 复发 ≥2 次）在落地时评估，先跑流程纪律强度；
- **实验失败不推进状态**：idea 卡停留在 in_experiment 或转 rejected（留结论），不因"方案合理"跳过数据；
- **反馈断供即停（分级）**：依赖 S1（工程师回报）的实验——fix 现场有效性判定——断供即停，如实降级为"运营等待期"（诚实退化）。但依赖 **S2（issue-replay 校准）** 的实验——检索/路由/根因类演进——不受 S1 断供影响，可继续跑。S1 断供时，L2/L3 的检索/路由类候选仍由 S2 提供验证依据，不假装演进但也不空转。

### 6.6 季度自评（人的元层审视——"审视整个流程，判断合理性"）

人（owner + 体系维护人）每季度审的不是单条变更，而是**流程本身**：

| 审视项 | 看什么数据 | 合理性判据 |
|---|---|---|
| 信号质量 | 信号误报率（候选被否决占比） | 误报高的信号下调权重或停用 |
| 授权合理性 | auto 抽审发现率、review 通过率 | 发现率高 → 收紧 auto；长期零发现 → 评估可否扩 auto |
| 产出质量 | idea 采纳率、回测通过率、rejected 理由分布 | 采纳率持续走低 → 候选源头（信号/起草）有问题而非继续堆候选 |
| 腐化检查 | 产出是否灌水（低质卡增多）、是否重复 | 流水线自身退化为"为产出而产出"时修正流程 |
| 参数校准 | timeline 趋势 + 闸门数值 | 按实测修正 config（5.1） |
| 流程自身 | 本轮自评结论、跨期自评对比 | 流程结构性问题 → 走 5.2 结构级演进（双签） |

自评报告（`proposals/reviews/<YYYY-Qn>.md`）是 L3 闭环的写回载体：结论要么落到 config（参数校准）、要么落到结构级提案（走 5.2）、要么落"维持现状 + 依据"。

### 6.7 角色与多 agent 编排（2026-09 压缩：单人场景是现状，多 agent 载体触发才展开）

机制与载体解耦：A–E 角色（观测/起草/实验/PR/人闸）不绑定具体实现。**当前单人/单会话运行**——观测、起草、实验由同一 agent 依协议完成，共享状态（ingest-state / timeline / ideas 队列）串行操作，遵守 git-workflow「多 agent 并行」节（独立 worktree、分支名全局唯一、合流显式 merge）。

**多 agent 载体是蓝图（触发条件到才启用）**：若出现真实的多 agent 并行场景（如 DSH Agent Teams 或 dsh-agent-teams 插件驱动长期任务轮间调度），再按下列约束展开，不为预言的多 agent 场景预建编排细节（原则十一）：

- 角色分工：观测 agent（串行，唯一读写共享状态者）→ 起草 agent（可并行，只读聚合与卡）→ 实验 agent（每 idea 独立 worktree）→ PR agent（按模板开 PR → CI → 按授权合入/送审）→ 人闸（6.3 级别人审 + 6.6 季度自评）；
- **共享状态"单一写入口"**（写冲突的结构保障）：对 ingest-state / timeline / ideas 队列 / session state 的写入收敛到一个持锁写服务（本地文件锁或单写者队列），不依赖 agent 自觉——这是"唯一写者"从纪律变结构（原则二）。worktree 隔离照旧，成员间经消息/任务结果间接协作；
- DSH 执行载体选项（continuable subagent / 内置 Agent Teams / dsh-agent-teams 插件）与质量门映射见 git 历史中的早期版本，启用时按当时文档核对，不在此常驻展开。

## 7. Idea 卡 schema（v2）与状态机

```yaml
id: EV-2026-XXX                 # 示例占位（真实卡号由 ev_proposal --new 分配）
layer: L2                        # L1 | L2 | L3（本卡示例：流程层）
title: triage 分支 vllm-ascend 启动参数族执行错率 0.6 → 修订该分支
status: in_experiment             # EV 卡状态词表（agent 决策档案——无人的合入语义）：
                                  #   产卡即执行：识别信号 + 方案成形 → 产卡（状态 in_experiment，
                                  #   开始 action + eval）——**没有 candidate 待办态**（agent 自主
                                  #   决策、全自动推进，方案成形就该做，不做就不产卡）
                                  #   in_experiment → 终态（agent 决策结果）：
                                  #     validated   采纳：eval 验证 solid，改动保留（进流程层攒批/PR）
                                  #     rejected    不采纳：试了不行/评估不成立（诚实记录，改动不保留）
                                  #     superseded  换方向：被新 proposal 替代（supersede 链指过去）
                                  # 注：EV 卡是 agent 自演进行为的决策档案——识别改进点→执行→
                                  #   验证→判断采纳/不采纳。**不含 git 协作状态**（攒批/PR/合入是流程层
                                  #   session 的事，不进卡词表）；人审发生在目标态完成提 PR 时，
                                  #   审视的是整个自演进过程是否 solid（含 rejected 卡——诚实实验记录）
                                  #   信号但数据前提未满足/方案未成形 → 不产卡（记 session 报告，
                                  #   条件到再产）——信号不是提案，提案是已准备执行的方案
authorization: review            # auto | review | dual（改动合入的知识层分级，按风险+证据预判）
                                 # ——注意：authorization 指改动合入的知识层分级，EV 决策本身 agent 做
dimension: evolvability          # architecture | evolvability | maintainability | observability | process
supersedes: []                   # 本卡替代的旧卡 id 列表（run §5：新 idea 替换旧实现时填）
superseded_by: null              # 被哪张卡替代（旧卡被替代后标 superseded，非 rejected）
created_at: 2026-09-01
source_signals:
  - signal: component_error      # 归因事件簇（trace attribution / s2 候选，按需聚合见 §2）
    evidence: "组件 triage:vllm-ascend-startup execution_error 归因 6 条（按需聚合）"
    trajectory: ["traces/*.yaml#attribution 2026-W37 聚合", "traces/2026-08-30-xxxx.yaml#attribution"]
hypothesis: 修订该分支的症状匹配逻辑后，执行错率降至 <0.3
predicted_effect: {metric: "组件执行错率", from: 0.6, to: "<0.3"}   # 可测预期（execution §2 follow-up 判定基准）
validation:
  method: golden_replay          # golden_replay | metrics_compare | issue_replay（S2 校准）
  baseline: 现 triage-tree + 现有 golden 套件
  success_criteria: golden 无回归 且 该组件归因簇不再增长
  rollback: 分支合入前可整体丢弃；合入后 git revert（原则七）
gate:
  condition: "该组件 execution_error 归因 ≥5 且 最近 2 期无下降"
risk: high                       # high → dual；中 → review；低且可逆 → auto
actual_cost: null                # 执行/验证后写回 actual_cost.tokens（缺失即审计缺口）；
                                 # source 标注口径：estimate（无记账环境估算）| measured
                                 # （DSH 经 tokenMeter.measure(session) 查真实值后写回）
                                 # （2026-09：删 estimated_cost——无 tokenMeter 时双字段纯文书，
                                 #   实际成本由 actual_cost 在 validated 时写回，一次即可）
principle_refs: [5, 6, 8, 11]    # 设计原则编号（1-11 整数，对应 design-principles 一~十一）
decisions: []                    # 审计链：谁在何时依据哪份证据判断什么（只追加不修改）
                                 # 每条含 who/when/conclusion；type 标注生命周期阶段：
                                 #   proposal（提案：识别改进点+假设）| action（执行：改动/实验/沉淀）
                                 #   | eval（验证：S2/golden 数据、通过与否）| decision（采纳/不采纳/换方向）
                                 # 卡 = agent 决策档案：proposal→action→eval→decision，
                                 #   decision 是卡终点；采纳与否由 agent 依据 eval 判断（无需人逐卡审批）
                                 #   status 推进随 decisions 走（见下"生命周期完整性规则"）
```

**生命周期完整性规则（每张卡是一个 proposal→action→eval→decision 的完整档案，不是想法清单）**：

1. **产卡即执行（没有 candidate 待办态）**：识别信号 + **方案成形**才产卡——产卡状态
   in_experiment（记 proposal + action decision）→ 验证（记 eval decision）→ agent 判断
   （validated 采纳 / rejected 不采纳 / superseded 换方向，记 decision decision）。agent
   自主决策、全自动推进：方案成形就该做，不做就不产卡。**执行或验证完成而卡停在
   in_experiment = 卡不完整**（机制推进，不是靠 agent 记得改状态）。
2. **终态卡必须有 decision 记录**：validated/rejected/superseded 的卡，decisions 中必须有 agent 的对应判断结论（依据哪份 eval 数据）——无结论的终态卡 = 审计缺口（verify_proposals 校验）。
3. **validated 后 actual_cost 必填**：成本审计（orchestration §3.2：无实际成本记录不可审计）——validated 卡 actual_cost 仍 null = 缺口。
4. **信号 vs 提案的边界**：仅"观察到的信号"（容量超了/族够了/数据前提未满足，但无**准备执行**
   的具体方案）**不产卡**——信号记 session 报告/任务状态，条件到（方案成形/数据齐）才产卡
   （防想法清单污染提案账本；跨轮待做的改进点在任务状态里追踪，不是卡状态）。

状态机（v5：EV 卡 = agent 决策档案——不含 git 协作状态与待办态；产卡即执行，终态是 agent 依据 eval 的判断）：

```
产卡（方案成形）──► in_experiment（action + eval 执行中）
    │                ├─ eval solid → validated（采纳：改动保留，进流程层攒批/PR）
    │                ├─ eval 不成立 → rejected（不采纳：试了不行，诚实记录，改动不保留）
    │                └─ 发现更好方向 → superseded（换方向：新 proposal 卡 supersede 指过来）
    │
    └──（信号但方案未成形/数据未齐 → 不产卡，记报告，条件到再产）
```

**EV 卡与 git/PR 的边界（关键，v4 修正）**：卡的终态是 **agent 的判断**（采纳/不采纳/换方向），
**不含 pending_merge/adopted 等合入语义**——攒批、提 PR、人审合入是**流程层**（session state /
批边界，§6.3a）的事，不进卡词表。人审发生在目标态完成（或降级完成，如"要沉淀 100 条实际
只有 60 条"）时提的聚合 PR：审的是**整个自演进过程是否 solid**（agent 的 proposal→action→
eval→decision 链是否合理、验证是否充分），不是逐卡审批合入。**rejected 卡同样进 PR 供审**——
agent 提了个 EV、改了、实验发现不行、不采纳，这是诚实的实验记录，人审时应接受（证明机制
在真实评估而非自欺）。采纳的改动随 PR 合入后，卡的 decision 可追加"PR #N 合入"作为追溯
（仅追加记录，不改变卡状态——卡状态是 agent 判断的终态）。

**validated 与观察窗**：agent 判 validated 是基于**合入前可得的验证**（S2/golden/归因事件复测）。
真实反馈类（content/fix 现场有效性）agent 只能做到"实现 + S2 佐证 + 判 validated"，现场确认
（S1）在合入后观察窗发生——观察窗结果（confirmed/rolled_back）作为**追加 decision 记录**
到卡，不改变卡状态机（卡的 agent 决策已完成；观察窗是效果结算层）。

规则：`status`/`authorization` 由机制推进不靠自觉（落地时 schema 校验可机械执行则进 CI，
准入判据三条件）；`decisions` 只追加不修改；`supersedes/superseded_by` 构成替换追溯链
（run §5），回滚粒度 = 被替代版本的合入点。

## 8. 自动化边界（v2）

| 环节 | 可自动 | 必须人闸 |
|---|---|---|
| 信号计算、归因事件聚合、指标汇总 | ✅ 全自动（脚本） | — |
| 候选起草、proposal 起草、PR 起草 | ✅ 全自动（agent 读聚合，不读全文） | — |
| 实验执行 + 报告 | ✅ 全自动（worktree 内） | — |
| 低风险合入 | ✅ auto（带抽审，可撤销） | 抽审 + 撤销权 |
| 判断性合入 / 高风险合入 | ❌ | review 30s / dual 双签 |
| 反馈回报 | ❌ | 只有工程师能回报 fix 结果 |
| 结构级演进（5.2）/ 季度自评裁决 | ❌ | 体系维护人 / owner |

**"人审 PR 是否终止闭环"（v1 已答，重申）**：不终止。合入后的效果进入回测与下一轮观测，继续触发新候选；auto 级别只是把低风险重复决定委托给带审计的执行器，抽审与撤销权保证决定权仍在人。

## 9. 明确不做（防过度设计）

- **不做"无人全自动"——hands-off 模式不是无人**：§6.3a 的 hands-off（完全自动化）指**事中不打断**（agent 连续工作到目标完成），但**最终仍有一个聚合 PR 人审 + 指标口径红线 + 每卡验证门 + 可回滚**——人审是合入闸点不是被移除。真正的"无任何人在环、无最终审、无红线"的模式不存在：auto 级也有月度抽审 + 可撤销授权；没有"完全信任模式"；
- **不采集 KPI / 身份 / 使用观测**：只观测系统自身行为（归因事件簇、idea 生命周期、信号误报），对象不是人（5.3 论证）；
- **候选 idea 不做 embedding 相似度推荐**（E3 推迟，ADR-0002 锁死）；
- **新 skill 不自动立项**：弱信号只进待定池，立项 = dual 双签；
- **不为流水线单开 CI 全量校验**：schema/实验引用校验按检查准入三条件在落地时评估，先跑约定强度。

## 10. 原则追溯

| 设计元素 | 服务的原则 | 说明 |
|---|---|---|
| 归因事件入 trace、按需聚合 | 八（可观测先于改进） | 流程质量从不可度量变可度量 |
| 三级授权 + 抽审 + 可撤销 | 五（建议与决定分离，预授权形态）、六（闸门硬度与错误代价匹配） | 决定权在人的预先授权 + 带审计执行 |
| skill 变更验证门（golden 强制） | 六、二（不变量写进结构） | 改流程影响全部下游，验证不可省 |
| 无实验证据不合入、失败不推进 | 一（验证先于交付）、十一 | 数据/效果驱动合入的硬规则 |
| 实验 worktree + 整体 revert | 七（变更可逆） | 错误半衰期 ≤ 一轮实验/回测 |
| 参数级自校准 vs 结构级留人 | 十一、五 | 参数是假设可实测修正；结构不可逆留人裁决 |
| 卡内证据自包含、~30s/条 | 九（注意力预算） | 人审轻量才不会被跳过 |
| 季度自评审视流程本身 | 十（诚实退化） | 防流水线自身腐化与"为产出而产出" |

## 11. 落地节奏（闸门衔接，不按日历）

| 阶段 | 内容 | 入口闸门 |
|---|---|---|
| Phase A | v2 文档采纳 + 归因事件字段落地（trace attribution + component，见 §2——**2026-09 已完成**） | 本文采纳（owner 确认） |
| Phase B | 归因事件按需聚合跑通 + L2 首条候选卡 | 聚合脚本可用（已就绪）+ 真实归因事件 ≥3 条 |
| Phase C | golden 验证门常态化（M2 落地） | M2 半自动化可用 |
| **Phase C2** | **S2 issue-replay 校准集建立**（复用 issue-ingest 已拉 issue 池，先小批量 ≤20 条验证对照评分可行性，再扩池；**2026-09 已建 9 条单池，selection/test 分离为规模闸门见 §2.1**） | 已闭环 issue 池可批量取 + 对照评分规则定稿 |
| Phase D | 自演进执行流程试点一轮（含分级授权 pilot） | C/C2 任一落地 + trace ≥20 可归因 session |
| Phase E | auto 级扩权/参数校准常态化 | 连续 2 轮试点抽审零发现 |
| 常设 | 季度自评（6.6） | 自 D 起每季度 |

与 roadmap 现有事项的关系：本文是机制层文档；roadmap 的 A2/E2/E5/O3/O4/M2/M5 是流水线的下游执行项，闸门不变。若采纳，建议 roadmap「常设检查点」加一行「自演进季度自评」（载体 proposals/reviews/）。

### 11.1 实现分级：第一批落地 vs 蓝图（防过度设计——机制由数据触发，不为未发生的问题预建全量）

本文及整套 evolution 文档是**完整设计蓝图**，但落地必须分级——这套机制**尚未真实运行过**（feedback≈0、S2 集未建、无真实 EV 卡），设计对错只有真实数据流过才能验证（原则八）。因此先建**第一批落地（最小可运行闭环）**——让机制第一次真实跑起来的最小组件集，用 1-2 轮真实 issue 验证设计；其余为**蓝图**（预测性设计，触发条件出现才实现）。仓库 rollout-assessment 的"数据/运维层未就绪，需第一个团队跑起来"与此一致——在此之上预建全部机制（13 态状态机、9+ 载体、多级降级）即为过度设计。按**触发条件到才实现**原则分级：

| 分级 | 机制 | 何时实现 |
|---|---|---|
| **第一批落地（最小可运行闭环）** | 会话协议（目标→对齐→计划→执行）、批提交核心（攒批 + 聚合 PR）、验证先于交付的双路径、S2 issue-replay 校准、知识层分级（auto/review/dual——合入门，EV 决策本身 agent 做）、EV 状态机（in_experiment/validated/rejected/superseded——产卡即执行，v5 已去 candidate） | Phase A–D 第一批 |
| **蓝图（触发后实现）** | 观察窗超时降级态（unconfirmed_valid/unconfirmed） | S1 断供真实持续 ≥2 期后（先用"标存疑 + 提醒"轻量处理，不进正式状态机） |
| **蓝图** | stale 候选过期态 | 候选积压真实发生（>20 在池）后（先用 inbox 式标红） |
| **蓝图** | 策略记忆独立文件（strategy-memory.yaml） | 季度自评跑通 ≥1 轮后（此前并入 session context） |
| **蓝图** | reviews/experiments 独立目录 | 有真实归档需求后（此前并入 session state，运行时载体） |
| **蓝图** | 稳态降频（steady）、候选积压治理水位 | scope 真实收敛或积压出现后 |
| **蓝图** | 运行模式细化（任务级攒批跨轮） | 用户真实要求"跨多轮攒批"后（默认批边界 = 一轮已够） |

**分级原则**：机制分为"解决已发生问题的第一批落地件"与"解决预测问题的蓝图件"。蓝图件**保留设计但不实现**，触发条件（数据/用户诉求）出现才激活——这正是仓库原则十一（数据触发演进）与 roadmap「明确不做（触发条件到再评估）」的形态。**全套文档是蓝图库，不是全部待办清单**：第一批落地只需上表"第一批落地"列的组件，跑通后再按数据触发逐步激活蓝图。

**落地顺序的主从关系（防多源冲突）**：**本文 §11 是唯一权威落地总纲**。execution §10 与 run §9 是各自维度的落地细化，不是平行计划——落地时以本表 Phase 推进，execution/run 的表只回答"本层内部先做什么"：

| 其他文档的落地项 | 归属本表哪一 Phase |
|---|---|
| execution §10：proposal schema v3 落模板 | Phase A（已完成：schema + verify_proposals） |
| execution §10：沉淀效果字段（predicted_value/first_hit） | Phase B（归因事件/首条 L2 卡后，随首批沉淀） |
| execution §10：follow-up 观察窗常态化 | Phase C（依赖 M2/S2 的即时判定） |
| execution §10：回滚率等机制指标进 timeline | Phase D 试点 ≥1 轮后 |
| run §9：统一执行记录（机制 C） | 第一批已完成（schema+脚本+3 内容 skill 收尾接入）；**2026-09 收敛：只覆盖内容 skill 收尾，diagnose 走 trace 不重复落**（见 run §4） |
| run §9：supersede 字段 + 回滚语义 | Phase D（出现首个替代场景时，schema 已含字段） |
| run §9：长期任务层试点 | Phase D（试点即含轮间调度） |
| run §9：可视化 | Phase E 后 / 常设（任务层跑通 ≥1 轮） |

## 12. 外部参考：与 SkillOpt 的关系（借鉴什么、不取什么）

[SkillOpt](https://github.com/microsoft/SkillOpt)（微软开源，MIT）是文本空间优化器：把单个自然语言 skill 文档当可训练参数，用 optimizer 模型产 add/delete/replace 编辑，validation gate（held-out 分数严格提升才接受）控制合入。评估结论：**不能直接安装使用**（优化对象/验证信号/数据边界/自家原则四重不匹配），**但设计有多处可借鉴**。本流水线不依赖它，下述借鉴均为设计语义的对照吸收，不引入其代码或运行时。

| SkillOpt 机制 | 与本设计的关系 | 采纳动作 |
|---|---|---|
| validation gate：held-out 严格提升才接受 + `gate_no_regression`（每任务持平或提升，缺结果即拦） | 与本流水线 6.5「数据/效果驱动合入」同构 | 语义吸收进 6.5（已含）；无回归 → 严格提升/持平 的验收口径与 gate_no_regression 一致 |
| 编辑需 bounded（learning-rate 限制每步编辑数） | 与本设计"变更集小步、可整体 revert"（原则七）同构 | 已含：单轮候选批量上限、单 skill 单轮编辑数上限 |
| reflect 从失败轨迹生成编辑建议 | 与本设计 trace 归因 → 候选 idea 同构 | 已含（第 2、4 节） |
| reject buffer / slow update（防跨轮遗忘） | 与本设计 rejected 留痕、季度自评跨期对比同构 | 已含（6.4 decisions 追加、6.6 自评） |
| **held-out 验证需要自动评分集** | 这正是本设计 2.1 的 S2 issue-replay 校准的用武之地：SkillOpt 式 gate 的分数来源 | 已含（2.1、4.3、6.5） |
| **held-out 防过拟合（selection vs test 分离）** | SkillOpt 在 selection 上做 gate 决策、在 held-out test 上做最终验收，防对校准集过拟合 | 已含：2.1 S2 校准集 selection/test 分离（gate 只看 selection，validated 终判只看 test） |
| judge 区分 shape ops vs outcome ops（防格式化作弊） | 与我们"避免把约定当硬门"一致 | 校验设计准则参考：凡是可被"形式上满足"的检查不算验收 |
| harvest 本地 transcript 送 provider | 数据边界冲突（traces 含客户信息） | **不取** |
| 单文档 best_skill.md 自由文本编辑 | 违反原则三/五/九 + skill 自包含 | **不取** |
| 全自动接受（无抽审形态） | 违反原则五 | **不取**（我们保留 auto+抽审+可撤销） |

一句话结论：SkillOpt 的**验证门语义与自动评分集思路**与本设计一致并互相印证；它的**执行形态**（自由编辑单文档、transcript 外送、无抽审）与本仓库规范冲突，不引入。若未来要跑类 SkillOpt 实验，其作用域仅限于 L2 的某个可自动评分的子组件（如 triage 分支文本），且必须先有 S2 校准集与 golden 验证门。
