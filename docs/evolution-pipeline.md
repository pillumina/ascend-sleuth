# 演进流水线（v2）：三层自演进闭环与自演进执行流程

> 本文回答一个问题：**系统如何闭环地改进自己的三层资产——知识内容、流程/skill、以及工作流本身——并把"人的参与"从逐条执行上移到流程审视。**
> v1（本文件旧版）只覆盖知识内容层的候选 idea 闭环；v2 扩展为三层模型（L1 知识内容 / L2 流程与 skill / L3 工作流与编排），并新增第 6 节「自演进执行流程」——一个降低人工参与度、但每次改动可追溯、每次合入必须由实验数据驱动的专门流程。**执行级信息契约（proposal 要记录什么、follow-up 怎么验证、沉淀效果怎么度量、agent 拿到什么）见 [evolution-execution.md](evolution-execution.md)；编排与治理层（会话如何启动、目标函数与停止条件、token 预算、自我指涉治理）见 [evolution-orchestration.md](evolution-orchestration.md)；从一条指令到持续运行的运行视图（长期任务、issue 评测循环、执行记录、可视化）见 [evolution-run.md](evolution-run.md)；面向使用者的指令/报告/干预语言见 [evolution-user-guide.md](evolution-user-guide.md)。**
> 对象层闭环（case 越用越准）已在 [evolution.md](evolution.md) 落地；理论推导见 [design-theory.md](design-theory.md) §4.2–4.4（元层信念、自演进闭环、演化即假设检验）；原则依据见 [design-principles.md](design-principles.md)。**本文自身的修订走 methodology PR + 体系维护人审（它属于 L3 结构，受本文第 5.2 节管辖）。**

## 1. 三层模型

| 层 | 对象 | 闭环的完成定义 | 当前状态 | 自动化边界 |
|---|---|---|---|---|
| **L1 知识内容** | case、reference、triage-tree 内容 | 知识随使用变准：命中率升、误诊率降 | ✅ 已闭环（evolution.md 五机制） | groom 预分诊自动、人审转正；E4 auto-promotion 在 v2 池 |
| **L2 流程与 skill** | diagnose/groom/to-* 实现、triage 分支、scripts、新 skill | 流程随误诊变对：执行错率（按组件）下降 | ⚠️ 半闭环（有归因分流，无组件台账、无验证门、无回测） | 归因自动、修复建议自动、合入人审（本文 4 节设计补全） |
| **L3 工作流与编排** | 流水线、groom 节奏、roadmap 机制、本文档 | 流程本身不腐化且参数被数据校准 | ❌ 未闭环（人季度回顾，参数不回流） | 参数级自校准半自动；结构级演进留人（本文 5 节） |

一条流水线服务三层：信号源相同（trace / metrics / 容量 / 回放），候选 idea 标注所属层，各层走各自的验证与授权路径。**L1 的闭环是 L2/L3 的数据前提**——但"反馈数据"不只有工程师回报一种形态，见第 2 节评分源分级：对已闭环 issue 的 diagnose replay 校准（以 issue 实际 resolution 为 ground truth）是不依赖人的自动评分源，可部分替代工程师反馈支撑检索/路由类演进。

## 2. 三层共用观测基座：归因下沉到组件

现状的误诊归因是二分：`case 错（改知识）/ 执行错（改 skill）`。二分对 L2 不够——"执行错"内部没有结构，改 skill 仍靠人工定位。下沉方案：

- **组件 = 可寻址的执行单元**：skill 的某个步骤（编号）、triage 的某个分支、某条 quickly_check、某个 script、某段提示词。每个组件有稳定 ID（skill 步骤号 / triage 分支名 / check id / 脚本文件名），台账才能累积。
- **trace 扩展**：归因事件从 `execution_error` 细化到 `component_error: <组件ID>`；诊断 agent 每次实际执行都记录"命中了哪些组件"（hit 侧），反馈 not_resolved 且归因执行错时记录"哪个组件错"（mis 侧）。**落地依赖（文档先行声明，改动在 PR 合入后执行）**：① diagnose SKILL.md 的 attribution 事件增加可选 `component` 字段（现有 verdict 词表 case_error|execution_error 不变，component 是执行错时的细分定位）；② trace_metrics.py 词表与统计同步识别 component 字段——两处都是对既有 skill/脚本的增量改动，需 golden 回归与 methodology PR（本文不直接改 skill）。
- **流程组件失败台账（新载体 `metrics/component-tally.yaml`）**：每个组件的 hit/mis/score，语义与 case confidence 相同（只按已回报结果回写、时间衰减、低分浮出）。台账是 L2 的"知识库"——它把"流程执行质量"变成可度量（roadmap「沉淀环观测」已指出产出无观测是盲区，触发条件未到前不记人/不按人；台账观测对象是组件，同样不引入身份/KPI 维度）。

**L2/L3 指标（全部从已有 trace/metrics 派生，不新增采集面）**：按组件执行错率、skill 变更前后回测差、idea 采纳率/回测通过率、信号误报率（触发了却被否决的候选占比）。这些是**系统自身行为的观测**，不是对人或协作的观测——与 roadmap「明确不做 KPI/身份/使用观测」的边界相容性见 5.3 与 9 节。

### 2.1 评分源分级（"反馈数据"不只有工程师回报）

演进闭环需要"这次改动是变好还是变坏"的判定信号。按可信度与可得性分三级，**工程师反馈不是唯一来源**：

| 级 | 评分源 | 判定什么 | 可得性 | 局限 |
|---|---|---|---|---|
| S1 | 工程师回报 fix 结果 | fix 在真实环境是否解决（confidence 回写的唯一依据） | 依赖人，当前捕获率≈0 | 反馈断供时不可用 |
| **S2** | **Issue-replay 校准**：取已闭环高价值 issue（有维护者确认的 resolution/root cause），以其**现象为 diagnose 输入 replay**，把系统输出（路由 namespace、命中 case、给出的 root cause/fix）与 **issue 实际 resolution 对照**自动评分 | 检索/路由/根因指向是否正确 | **全自动，无人工**；数据源 = 上游已闭环 issue（仓库 issue-ingest 已在拉） | 只能校准"找得对不对"，**不能校准 fix 在现场是否有效**；issue 的 resolution 本身可能有错（用 resolved/维护者确认的池降低） |
| S3 | golden 回放（eval/golden fixture，期望 = 构造或历史命中的 case） | 回归防护（改动后不倒退） | 全自动，但套件人工维护 | 期望来自历史命中（自我参照），不是外部 ground truth |

**S2 是补 S1 空缺的关键机制**（对应"仅根据用户的现象 replay diagnose、再按已知根因思考校准"的构想）：它对已闭环 issue 批量做 diagnose replay，产出**与 issue resolution 的对照评分**（hit/miss、路由对错、root cause 是否一致），不依赖任何工程师回报。三条用途：

- **验证门数据**：L2 skill 演进的 golden 验证可换成/补充 S2 对照（改 skill 前后在同一批 issue 上命中率是否提升）；
- **错例提取**：路由错例、未命中 case 从 S2 的 miss 自动累积（E2/E5 数据源，不等人回报）；
- **L1 校准**：S2 的 miss 定位"缺 case"或"case 错"，产出候选 idea 卡。

**S2 的边界（诚实标注，防过度承诺）**：它以 issue 的 resolution 为基准，校准的是系统**检索与归因**是否正确；现场 fix 有效性（severity 语义、环境特异性）仍只能靠 S1。S2 分数进入指标时标注 `source: issue-replay`，不与 S1 混淆（口径见 docs/metrics.md）。若某 issue 的 resolution 仅是 workaround 而非根因修复，标记后降权或剔除（issue 池筛选规则：优先 state_reason=completed + 维护者 closed + fix commit 可溯的）。

**S2 校准集的 selection/test 分离**：S2 池分两半——`selection` 用于 gate 决策（改 skill 前后对照打分），`test` 用于 validated 终判。规则：**gate 只看 selection，终判只看 test，test 半不参与任何中间对照**——防系统对校准集过拟合（对应 SkillOpt held-out test 语义，运行视图见 evolution-run.md §3）。

## 3. L1 知识内容层（已闭环，简述）

evolution.md 五机制 + roadmap A/E 系列已覆盖：confidence 回写、groom 维护、误诊归因改 case、容量治理。本流水线对 L1 只做两件事：

- **承接**：L1 的维护动作（groom 信号表）升级为带 trajectory 的候选 idea 卡（本文 7 节 schema），让"容量告警/路由错例/覆盖缺口"不再止步于动作而进入提案闭环；
- **校正**：归因从二分下沉到组件后，case 错与执行错的判决依据更细，误改正确 case 的风险下降（evolution.md 机制 3 的直接增强）。

## 4. L2 流程/skill 层（半闭环 → 全闭环设计）

补全四件事，顺序即依赖：

### 4.1 归因下沉（前提，见第 2 节）

没有组件级归因，下面三件事都无数据。

### 4.2 流程组件失败台账

台账浮出反复失败的组件 → 自动生成候选修复 idea（trajectory = 台账条目 + 对应 trace 引用），建议修复方向（改该组件所在 skill 步骤 / triage 分支 / check / script）。**只产出建议与证据，修复方案与合入留人/分级授权**（原则五）。

### 4.3 skill 变更验证门（强制）

任何 skill/流程改动合入前必须过 **golden 前后对照**（eval/golden + M2 半自动化；容忍 LLM 非确定性用 top-3 断言）。golden 断供或套件不足以区分时，用 **S2 issue-replay 校准**（2.1）替代或补充：改 skill 前后在同一批已闭环 issue 上跑 diagnose，对照 issue resolution 的命中率是否提升。这是 L2 与 L1 的关键差异：改 case 只影响一条知识，改 skill 影响所有下游——验证门不可省，对应原则六（闸门硬度与错误代价匹配）。

### 4.4 新 skill 沉淀触发（弱信号，防过度设计）

只有两类信号可触发"可能需要新 skill/reference"的候选：
- 同一执行错类别反复出现且无归属组件（台账里出现"未归因"簇）；
- 多轮诊断反复走同一 Tier 3 兜底且最终 resolved（说明缺 Tier 2 覆盖，可能补 case 而非新 skill）。
候选进**待定池**（不自动立项），标注"新 skill 立项 = 高风险结构变更，需 proposal 论证与双签"。不做 embedding 相似度推荐（ADR-0002 锁死）。

### 4.5 效果回测（闭环收口）

L2 变更合入后观测连续 N 期（组件 mis 是否下降、执行错率是否回落、golden 是否保持）；回测不达预期 → 回滚或开再迭代卡。无回测的 L2 变更 = 未闭环，标注"变更已合入、效果待观测"而非假装完成（诚实退化）。

## 5. L3 工作流/编排层（有界闭环）

L3 的闭环不是"流程自动改流程"（递归陷阱），而是**参数级自校准 + 结构级留人**的混合：

### 5.1 参数级自校准（半自动）

流水线自身的执行参数——触发阈值、候选批量、抽审率、授权升级门槛——作为**数据**存配置（如 `evolution/config.yaml`），由季度自评数据校准：某信号长期误报 → 下调触发权重；auto 级抽审发现率高 → 收紧 auto 条件。参数变更是低风险、可逆的（diff 一行），可走快速通道。**参数本身服从原则十一：是假设的量化形态，接受实测修正。**

### 5.2 结构级演进留人

改变流程结构本身——groom 的 R 轮次增减、本流水线的阶段设计、roadmap 机制部分、skill 骨架——一律 methodology PR + 体系维护人审（kb/high-risk 双签）。理由：结构变更是不可逆性最高的变更（影响全部下游与全部后续轮次），没有数据能预证其正确，只能由人基于使用检验裁决（原则五、六、七）。

### 5.3 与「明确不做」的相容性论证

roadmap 不做的是 **KPI / 身份 / 使用观测**（对象是人：工程师 ID、协作时长、每人产出）；本流水线观测的是**系统自身行为**（组件 mis、信号误报率、idea 生命周期），对象是 trace/台账/卡，不涉人、不引入灌水激励。若未来出现首个集中式多用户部署，再评估是否引入协作维度（roadmap 触发条件不变）。

## 6. 自演进执行流程（专门流程）

### 6.1 定位

一个**受约束的自治循环**：周期性把"系统自身的观测数据"转成"系统自身的变更"，每笔变更可追溯、可回滚、由实验数据放行。它不是无人在环——而是**人的角色从逐条执行上移到两级审视**：内容级抽审（抽查已自动合入的变更）+ 元层级季度自评（审视流程本身是否在做对的事）。**触发方式：显式触发为主**（owner 启动一轮，或数据闸门达标后由 owner 批准启动），不设自发 schedule——防自发批量改库（knowledge-groom 保留 disable-model-invocation 的同一纪律）。

### 6.2 流程总览

```
① 观测    ② 候选      ③ 分级授权        ④ 实验           ⑤ 合入          ⑥ 回测        ⑦ 季度自评
───►      ───►        ───►              ───►             ───►            ───►          ───►
跑信号脚本  起草 idea 卡  按风险/证据分级      golden 前后对照    auto: CI+抽审   观测 N 期      人审视流程本身
汇总聚合值  (带 trajectory)  auto/review/dual  或台账复测        review: 人审     指标变化      信号误报率/抽审发现率/
                                                  dual: 双签      不达标→回滚     授权级别合理性/产出质量
   （观测 agent 串行，唯一读写共享状态者 —— git-workflow 纪律）
```

### 6.3 三级授权（降低人工参与的核心机制）

**论证**：原则五"采纳、调整和驳回永远是人"与降低人工并不矛盾——人的决定可以是**预先授权（pre-authorization）**：在特定可机械验证的条件下，把重复性低风险的决定委托给带审计的执行器。仓库先例即 roadmap E4（trusted auto-promotion：近重复 + quickly_check 通过 + 连续 N 次兄弟命中未误诊 → 自动升格 + 月度抽审）。三级授权是把 E4 从 L1 case 推广到全部三层：

| 级别 | 适用 | 条件 | 合入方式 | 兜底 |
|---|---|---|---|---|
| **auto** | 低风险、可逆、机械可验证（content 补 case、reference 修 typo、参数校准、脚本 bugfix） | golden 通过 / 台账复测通过 + 变更集可整体 revert + 卡内 decisions 完整 | 自动合入（仍产生完整 PR/commit，CI 硬门） | **月度抽审**：抽审发现错误 → 回滚 + 撤销该类别 auto 授权 |
| **review** | 判断性、中风险（新 case 转正、reference 修订、低风险 skill 步骤调整） | 同上 + 人审 30s/条 | 人审合入 | 随机审序（已有纪律） |
| **dual** | 高风险、结构、不可逆（triage-tree、skill 骨架、新 skill 立项、L3 结构、改 active reference） | 4.3 验证门 + kb/high-risk 双签 | 双签合入 | CODEOWNERS 双组路径 |

**升级门槛（数据触发）**：某类 review 变更连续 N 次回测通过且抽审零发现 → 可申请降级为 auto（记入 config，可随时撤销）；auto 变更抽审发现 ≥1 错误 → 该类别立即退回 review，并在季度自评里复核（原则六：闸门硬度与实测错误代价匹配）。

### 6.4 可追溯契约（每笔改动可追溯）

- 每个候选 = 一张 idea 卡（`proposals/ideas/<EV-YYYY-NNN>.yaml`）：layer、trajectory（触发信号 + 证据出处）、hypothesis、validation、授权级别、decisions 追加式留痕（谁/何时/依据/结论）；
- 每次合入（含 auto）产生完整 PR/commit，PR body 引用实验报告与 idea 卡；变更集整体可 revert；
- 实验记录（`proposals/experiments/`）：golden 前后对照数据、台账复测结果，随 PR 归档；
- **追溯链闭合成环**：卡 → 实验 → PR → 合入后回测 → 季度自评 → （若参数校准）回到卡。人随时可从任一合入点沿链回看"为什么改、依据什么数据、谁放行的"。

### 6.5 合入硬规则（数据/效果驱动）

- **无实验证据不合入**：任何层级的任何变更（含 auto），合入前必须有 validation 记录——golden 无回归 / 台账复测通过 / metrics 前后对比。这是**硬规则**（reviewer 看到无记录的 PR 必须打回；auto 合入器缺记录即拒绝）；"PR 是否带实验记录引用"能否 CI 化按检查准入三条件（机械可查 / 确定性后果 / 复发 ≥2 次）在落地时评估，先跑流程纪律强度；
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

### 6.7 角色与多 agent 编排

```
A. 观测 agent（串行，唯一读写共享状态者）：跑信号脚本 → 汇总聚合 → 产候选卡
B. 起草 agent（可并行）：按卡起草 proposal / 实验设计（只读聚合与卡，不读 case 全文——token 预算）
C. 实验 agent（每 idea 独立 worktree）：执行 validation → 报告写回
D. PR agent：按 5 类模板开 PR（body 带实验引用）→ CI → 按授权级别合入/送审
E. 抽审人 / reviewer / 体系维护人：6.3 级别人闸 + 6.6 季度自评
```

共享状态（ingest-state / timeline / component-tally / ideas 队列）**串行**操作，遵守 git-workflow「多 agent 并行」节：每 agent 独立 worktree，分支名全局唯一，合流显式 merge。

**执行载体选项（DSH 环境）**——机制与载体解耦，角色 A–E 不绑定具体实现。DSH 提供三种多 agent 载体，落地时按需选用：

| 载体 | 能力 | 启用条件 | 适用 |
|---|---|---|---|
| **continuable subagent**（当前会话所用：subagent/subagent_fork/list_agents/send_message） | 后台子 agent、可续对话、可 fork 继承上下文 | 默认可用 | 观测/起草/实验 agent 的轻量编排 |
| **Agent Teams**（内置 experimental：`ctx.agentTeams` + spawn_teammate / team_task_create/get/list/update / 持久 mailbox / 共享任务 DAG，含 blockedBy 依赖与 writeScopes 提示性路径前缀） | 具名持久 teammate、peer mailbox、共享任务板 | **dsh-base 默认禁用**，需 profile patch 启用；启用后禁用旧 continuable-child 同名控制工具 | 任务板 + 依赖 DAG 适合长期任务的轮间调度（run.md §2） |
| **dsh-agent-teams 插件**（[NanmiCoder/dsh-agent-teams](https://github.com/NanmiCoder/dsh-agent-teams)，独立第三方实现，不依赖内置 experimental） | 11 个 `agent_teams_*` 工具（create/add_member/create_task/claim/update/send_message/status/resume…）+ 质量门（requirements→implementation→verification→review→integration 结构化任务合同，attempt_id 拒绝迟到写入）+ **自带 Web UI 活动面板**（成员树 + 任务 DAG + 实时状态，shell overlay） | `dsh plugin --profile <name> add @nanmicoder/dsh-agent-teams@<版本>`；**版本须匹配宿主**（0.1.14 ↔ harness 0.1.0-rc.8；0.1.15 ↔ 0.1.2-alpha.2） | 队长制自然语言协作 + 现成可视化面板（run.md §6 的可视化可先复用其活动面板，不必从零写）；质量门语义与本仓库 execution §5 follow-up 验证同构 |

共享状态串行纪律在三种载体下同样适用——team 的 `writeScopes` 是提示性路径前缀不是锁（内置 agent-team 文档原话），不能替代"唯一读写共享状态者"的执行约束；dsh-agent-teams 的质量任务合同（verdict=pass 才 completed、failed 不解锁下游、自动 repair/review 链）与本设计"实验失败不推进 / review 级授权 / 自动修复"同构，可直接映射为授权级别的执行层实现。

## 7. Idea 卡 schema（v2）与状态机

```yaml
id: EV-2026-001
layer: L2                        # L1 | L2 | L3（本卡示例：流程层）
title: triage 分支 vllm-ascend 启动参数族执行错率 0.6 → 修订该分支
status: candidate                # 完整词表（v3，与 execution §5.1 一致）：
                                 #   candidate → proposed → in_experiment → adopted
                                 #   adopted → validated | rolled_back | superseded（观察窗终态）
                                 #   in_experiment 实验失败 → rejected；回测不达标 → re-iterate（回 proposed）
                                 # 注：本卡（EV proposal）status 无 awaiting_validation——
                                 #   那是沉淀对象（case）的观察窗状态（见 execution §4.2/4.3），
                                 #   属 case YAML 扩展字段，不并入 EV 卡词表
authorization: review            # auto | review | dual（6.3 分级；candidate 时由风险+证据预判）
dimension: evolvability          # architecture | evolvability | maintainability | observability | process
supersedes: []                   # 本卡替代的旧卡 id 列表（run §5：新 idea 替换旧实现时填）
superseded_by: null              # 被哪张卡替代（旧卡被替代后标 superseded，非 rejected）
created_at: 2026-09-01
source_signals:
  - signal: component_error      # 来自组件台账（metrics/component-tally.yaml）
    evidence: "组件 triage:vllm-ascend-startup mis=6/hit=4，score 0.4"
    trajectory: ["metrics/component-tally.yaml 2026-W37", "traces/2026-08-30-xxxx.yaml#attribution"]
hypothesis: 修订该分支的症状匹配逻辑后，执行错率降至 <0.3
predicted_effect: {metric: "组件执行错率", from: 0.6, to: "<0.3"}   # 可测预期（execution §2 follow-up 判定基准）
validation:
  method: golden_replay          # golden_replay | tally_recheck | metrics_compare | issue_replay（S2 校准）
  baseline: 现 triage-tree + 现有 golden 套件
  success_criteria: golden 无回归 且 台账该组件 mis 不再增长
  rollback: 分支合入前可整体丢弃；合入后 git revert（原则七）
gate:
  condition: "该组件 mis ≥5 且 最近 2 期无下降"
risk: high                       # high → dual；中 → review；低且可逆 → auto
estimated_cost: {tokens: 8000}   # 成本侧（orchestration §3.2：预计 token，起草时填）
actual_cost: null                # 合入/回测后写回 actual_cost.tokens（缺失即审计缺口）
principle_refs: [五, 六, 八, 十一]
decisions: []                    # 审计链：谁在何时依据哪份证据决定什么（只追加不修改）
```

状态机（v3：与 execution §5.1 follow-up 观察窗一致；否决/回滚 = 终态态，留理由，不删除；`adopted` 是待回测的合入，不是完成）：

```
candidate ──分级授权──► proposed ──实验启动──► in_experiment
    │                          │                   ├─ 数据通过 → adopted（合入，进入观察窗）
    │                          │                   │      ├─ 观察窗达标 → validated（闭环终态：效果入 metrics、台账记 hit）
    │                          │                   │      ├─ 未达标无退化 → re-iterate（回 proposed）
    │                          │                   │      └─ 退化/有害 → rolled_back（回滚 + 教训入台账）
    │                          │                   └─ 实验失败 → rejected（留结论）
    └──否决────────────────────┴───────────────────────────────────► rejected（留理由）
```

规则：`status`/`authorization` 由机制推进不靠自觉（落地时 schema 校验可机械执行则进 CI，准入判据三条件）；`decisions` 只追加不修改；`supersedes/superseded_by` 构成替换追溯链（run §5），回滚粒度 = 被替代版本的合入点。

## 8. 自动化边界（v2）

| 环节 | 可自动 | 必须人闸 |
|---|---|---|
| 信号计算、台账累积、指标汇总 | ✅ 全自动（脚本） | — |
| 候选起草、proposal 起草、PR 起草 | ✅ 全自动（agent 读聚合，不读全文） | — |
| 实验执行 + 报告 | ✅ 全自动（worktree 内） | — |
| 低风险合入 | ✅ auto（带抽审，可撤销） | 抽审 + 撤销权 |
| 判断性合入 / 高风险合入 | ❌ | review 30s / dual 双签 |
| 反馈回报 | ❌ | 只有工程师能回报 fix 结果 |
| 结构级演进（5.2）/ 季度自评裁决 | ❌ | 体系维护人 / owner |

**"人审 PR 是否终止闭环"（v1 已答，重申）**：不终止。合入后的效果进入回测与下一轮观测，继续触发新候选；auto 级别只是把低风险重复决定委托给带审计的执行器，抽审与撤销权保证决定权仍在人。

## 9. 明确不做（防过度设计）

- **不做无人的全自动**：auto 级也有月度抽审 + 可撤销授权；没有"完全信任模式"；
- **不采集 KPI / 身份 / 使用观测**：只观测系统自身行为（组件台账、idea 生命周期、信号误报），对象不是人（5.3 论证）；
- **候选 idea 不做 embedding 相似度推荐**（E3 推迟，ADR-0002 锁死）；
- **新 skill 不自动立项**：弱信号只进待定池，立项 = dual 双签；
- **不为流水线单开 CI 全量校验**：schema/实验引用校验按检查准入三条件在落地时评估，先跑约定强度。

## 10. 原则追溯

| 设计元素 | 服务的原则 | 说明 |
|---|---|---|
| 归因下沉到组件、台账累积 | 八（可观测先于改进） | 流程质量从不可度量变可度量 |
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
| Phase A | v2 文档采纳 + 归因下沉字段设计（trace 组件字段、台账 schema） | 本文采纳（owner 确认） |
| Phase B | 组件失败台账跑通 + L2 首条候选卡 | A 落地 + 台账有 ≥1 组件 mis ≥3 |
| Phase C | golden 验证门常态化（M2 落地） | M2 半自动化可用 |
| **Phase C2** | **S2 issue-replay 校准集建立**（复用 issue-ingest 已拉 issue 池，先小批量 ≤20 条验证对照评分可行性，再扩池） | 已闭环 issue 池可批量取 + 对照评分规则定稿 |
| Phase D | 自演进执行流程试点一轮（含分级授权 pilot） | C/C2 任一落地 + trace ≥20 可归因 session |
| Phase E | auto 级扩权/参数校准常态化 | 连续 2 轮试点抽审零发现 |
| 常设 | 季度自评（6.6） | 自 D 起每季度 |

与 roadmap 现有事项的关系：本文是机制层文档；roadmap 的 A2/E2/E5/O3/O4/M2/M5 是流水线的下游执行项，闸门不变。若采纳，建议 roadmap「常设检查点」加一行「自演进季度自评」（载体 proposals/reviews/）。

**落地顺序的主从关系（防多源冲突）**：**本文 §11 是唯一权威落地总纲**。execution §10 与 run §9 是各自维度的落地细化，不是平行计划——落地时以本表 Phase 推进，execution/run 的表只回答"本层内部先做什么"：

| 其他文档的落地项 | 归属本表哪一 Phase |
|---|---|
| execution §10：proposal schema v3 落模板 | Phase A（与归因字段设计同批） |
| execution §10：沉淀效果字段（predicted_value/first_hit） | Phase B（台账跑通后，随首批沉淀） |
| execution §10：follow-up 观察窗常态化 | Phase C（依赖 M2/S2 的即时判定） |
| execution §10：回滚率等机制指标进 timeline | Phase D 试点 ≥1 轮后 |
| run §9：统一执行记录（机制 C） | Phase A–B 之间（记录 schema 定稿即接） |
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
