---
name: diagnose
description: >
  昇腾训练/推理问题的核心诊断循环：收集症状、按 triage-tree 路由、两阶段加载
  并验证 Tier 2 case、命中给 fix（高危 root cause 改提示 halt）或转深度排查。
  Tier-2 未命中但最终解决时起草候选 case。全程写 trace。
  仅在能执行命令的 agent（Claude Code / Codex / pi）中可用。
---

# Diagnose

昇腾问题的核心诊断循环。你是辅助定位工具——**fix 是你给的建议，由人手动应用到客户环境，你不自动改生产**。

> **本文是「可执行脊梁」**：只保留**始终要跑**的骨架与权威规则。步骤的**展开机制**（子步骤/边界/判定细节）见本 skill 的 `references/diagnosis-procedure.md`；**trace 细节**（词表/时间戳/证据落盘完整展开）见 `references/diagnosis-trace.md`，二者**按需加载**。skill 支撑文件一律放本 skill 的 `references/`，**不放仓库根 `references/`**（那是知识库/先验层）。

## 何时用

出现训练或推理问题（中断 / 精度 / 性能），且你在能执行 bash 的 agent 中。被打断后续接 → `/skill:resume-diagnosis`。

**只问思路的咨询不是接单**：工程师问"这类问题怎么定位"、手上没有报错原文或日志、不需要你给出这次的具体结论时，按已有知识直接答方法（可读先验层的流程词条），**不开 session、不写 trace**：trace 要回放的是"看了哪些候选、给了什么修复、结果如何"，没有现场证据的会话记录提供不了这两样。等对方贴出证据、要往下定结论时再开 session。

## 流程选择（开屏一次，决定这次走到多深）

**何时问**：确认这不是"只问思路的咨询"（见上一节）之后、开始收集症状之前。这时工程师已经在场，问一次的成本是十秒；拖到后面再问，等于让他为一条他已经不想要的路径跑完深度排查与报告。

**问什么**（三个口子，按他答的走）：

| 选择 | 走到哪一步为止 | 明确不做 |
|---|---|---|
| **快路**「先给最可能的结论 + 验证命令」 | 候选加载 → 命中即给结论 | 深度排查不在命中后自动展开；步骤 6 只出对话输出 + 一条最短 trace，报告与沉淀候选都不产 |
| **全路**「完整排查到根因」 | 未命中继续深度排查 → 位置报告 → 沉淀候选 | —— |
| **紧急**「生产中断，先恢复」 | 按「紧急情况」一节先 stabilize | 不钻深度排查、不写 postmortem |

**怎么写进过程**：把选择记进 trace 的顶层 `summary` 与首条 user 事件，让续接的人一眼看到这单的目标。路径不同不改变下面骨架的**前四步**（收集、路由、候选加载与验证、探询）——路由质量与证据采集三条路都要，省掉它们会让快路变成瞎猜。真正的分叉在两处：**步骤 5 深度排查**与**步骤 6 产出**。

**别把它做成问卷**：三个选项给编号，工程师回一个数字即可；他一开始就贴了完整的报错与日志、又没说要快速结论时，默认按**全路**走，只在结论交付时问一次要不要再往下（深挖 / 沉淀 / 都不用）。

**改向不重来**：走到一半他说"先给结论就行"或"继续挖"，就切路径——已跑完的步骤不重跑，已写的 trace 不改写，新路径从当前步继续。

## 紧急情况（生产中断）

客户说“紧急 / 生产挂了 / 先恢复”时，诊断目标从“查根因”变成“**先 stabilize**”：

1. **还是先查知识库**——有匹配的 case（比如已知的安全回滚）直接给，这最快。
2. **无快速匹配时**，按已提供的信息一步步给 stabilize 建议：问最近 24-48h 改过什么；`npu-smi info`/`hccl top` 健康；看日志栈尾定位哪层炸；能否先恢复（回滚 checkpoint / 降配 / 重启 daemon）。
3. **不钻深度排查、不写 postmortem**——事后用 `/skill:to-postmortem` 补。

## 流程（骨架）

> 每步只写「做什么 + 何时用」；**子步骤与判定细节**见 `references/diagnosis-procedure.md` 对应「步骤 N」。核心循环 = 收集 →（数据缺口则取采集面）→ 路由 →（键触发：证据里的码/签名/名当场查）→ 两阶段加载+2.5 reference → 验证 → (未命中)深度排查 → 产出。

> **先验 trace 相似检测**（收集症状后、路由前）：扫 `traces/*.yaml`（**全部 status**——进行中+已闭环都留在 `traces/`），按症状里的模型/框架/配置名/category 对每个 state 文件的 `summary`/`detected_framework`/`detected_category` 做**词法 grep 匹配**。
> - **陈述，不提问**：命中就**说一句**——"本地有 `<session_id>`，停在 <哪一步 / 结论一行>"——然后**在同一条消息里继续按本次问题往下走**。工程师回"就是这个"再切 `/skill:resume-diagnosis`。**不要写成"要续接吗？"**：那是把判断推给一个手上没有上下文的人，还把新问题卡在路由之前等答复。
> - **有判据才提**：命中单的 `summary` 为空、或 trace 只有寥寥几步（裸 stub）时不提——念一个没有内容的 session，等于让工程师替你判断哪一单。
> - **一轮最多提一次**，不随步骤重复。
> - **只提同类**：匹配维度是模型/框架/配置名/category，同框架下的无关问题命中就是噪音；已 `resolved`/`escalated`/`archived` 的同类单同样只陈述（给结论一行供参考），不拦路、不泛泛问"有未完成诊断要续接吗"。
> - **不在这里追旧单的反馈**：`feedback.outcome: pending` 是上一单的事，与本次问题无关——它挂在续接启动与面板待办上（口径见 `references/diagnosis-procedure.md` 步骤 6）。开屏先审旧单是审讯，不是诊断。
> - 状态词表见仓库根 `trace-status.yaml`。

1. **收集症状 + 确认框架**（全部来自工程师提供）：本步产出一张**覆盖表**（行固定：错误原文 / 触发位置 / 引擎 / CANN / HDK / 平台 / 必现偶发 / 单机多机 / 已试过什么）——**先提取、再问缺口**：值优先从已提供的日志（栈尾、启动横幅、plog、配置）里提，**提取不到的行留空即待问项**，只问空着的那几行、一次问全，并只报确认行与待补项给他核对（不复述原文）；**信息不全就主动问**；**主动裁剪日志**（失败 rank + 栈尾，绝不灌全量 profiler）。→ 展开见 reference 步骤 1。
2. **分类 → `triage-tree.yaml`（Tier 1）**：症状匹配分支 → 路由 namespace；triage 决策记 trace（**`triage` 事件必须带 `routed`**，没命中就写 `routed: []` 而不是省略字段——省略与「路由没错」在指标上同形）；未命中 → 语义兜底 `triage_semantic`（带 namespace）；无法分类 → Tier 3。**收尾做键触发**：证据里的错误码 / 故障签名 / 环境变量名 / 版本组合当场查先验查表族（**先于候选加载**，每次必留一条 trace，含"没有可查的键"）；**错误码在族表里没有行 → 查 `references/errors/_code-gaps.yaml`（缺行索引，`seen_in` 直接给到有修法的那张表），再报"没有"**。→ 展开见 reference 步骤 2。
3. **两阶段加载 Tier 2**：阶段一读命中 category 分片索引筛候选(≤5)，**排序仍由你按相关性判断**——行内 `sig`（该 case 的报错签名字面量）与 `tok`（其 token 集合）是判断的**证据**：输入里的报错原文若与某条的 `sig` 逐字命中，那条就是强候选；`tok` 交集用于次一级比较；`confidence.score` 只作破平（它 calibrate 的是现场解决率，不是本次相关性——实测按 score 单独排序会把期望 case 压到中位第 20 名）。**不要用机械计数替代你的判断**：历史回放里 agent 的相关性判断把期望 case 放进 top-3 的比例（19/19）高于任何机械排序键。需要机械序做对照时可跑 `python3 scripts/rank_candidates.py`（工具，不是规定动作）；阶段二载全文 + `quickly_check`(primary→fallback) 验证；**阶段 2.5** 候选命中后**必做**——先读候选自带的 `ref_knowledge`（按 role），**再一律 grep 背景 summary 层取 ≤5 行**（两者并列，不是"没有前者才做后者"；只读 `active`）。→ 展开见 reference 步骤 3。
4. **验证 diagnosis checks**：顺序**对照已提供信息**验证；缺信息→追问；mismatch 且有 `fix_on_mismatch`→提示 fix（**先看 severity**）；无 `fix_on_mismatch`→标 `excluded_cases` 试下一个。→ 展开见 reference 步骤 4。
5. **深度排查（未命中）**：**先取流程（方法缺口，见下节）** → Tier 3 grep `postmortems/`；**源码分析**（疑似框架/算子层且 Tier 3 未覆盖）走 `scripts/src_fetch.py`（见源码分析小节）；都没有→诚实说"知识库未覆盖"，建议 `/skill:to-postmortem`。→ 展开见 reference 步骤 5。
6. **产出**（按开屏所选路径决定做到哪）：`resolution` + 顶层 `summary` + **人读定位报告**（`traces/<session_id>.report.md`，结构与行文见 `references/report-template.md`；**全路**产出，**快路**不产；**报告是活件**——后续回报/resume/新证据到达时修订同一份并追加修订记录，不另起）+ **`sediment_candidates`**（结构化沉淀候选，与报告第 8 节同源，全路产出）+ 沉淀状态(`sedimented`) + trace；**给完 fix 立刻写 feedback**（真实 case id 或占位串 `pending-investigation`，并写 `feedback_pending_since`），**不在当场追问结果**，对话里给一条可复制的回报指令，债由续接与面板追。→ 展开见 reference 步骤 6。

## 数据资产探询（「数据缺口」消费点——精度 / 性能类在候选加载后问这一句）

reference 由流程里的**缺口**触发（**不是第四检索层**：不参与候选路由 / 排序，路由与筛排只看 case），**三个缺口对应四个触发点、每个触发点都有确定的时点**——不靠当场自评"我缺不缺先验"：

| 缺口 | 触发点 | 时点 | trace |
|---|---|---|---|
| 数据缺口 | 缺测量数据 → 采集面 | 步骤 3（阶段二加载后、候选加载完才知道缺哪个具体值） | `purpose: collect` |
| 判断缺口（理解侧） | 证据里有错误码 / 故障签名 / 环境变量名 / 版本组合 | **步骤 2 收尾，先于候选加载** | `purpose: signature` |
| 判断缺口（背景侧） | 候选命中 | 步骤 3 阶段 2.5 | `purpose: background\|fix` |
| 方法缺口 | 候选全未命中、需要"这类问题怎么查" | 步骤 5 | `purpose: procedure` |

**每个触发点都留 `outcome: hit|miss|skipped` 三态**（`skipped` 必须写理由）——不查不留痕时，"查了没有"与"根本没查"在数据上同形，消费率无法归因。

本节只管数据缺口：命中精度或性能类问题、候选加载完发现**缺一个具体测量值**才能往下走时，**先探询对方手上的资产，再决定给「分析」还是给「采集指导」**——别默认对方不会采，也别默认对方已有数据。一句话的成本，换掉一整段可能没人需要的接入说明（原则九：上下文与注意力都是预算）。

**绑定落在数据上，不写在散文里**：category → 探询问句 → 分支 → 词条 的绑定见 `references/collect-gates.yaml`（本 skill 支撑文件；每个 id 由 `verify_references.py` 校验存在且 `active`——散文里硬编码 ref-id 会静默腐化，已有先例）。本节只给交互形态（问什么、何时问）：

| category | 探询问句 | 闸门形态 |
|---|---|---|
| **precision** | 「你已经有 dump 数据 / 分析结果了吗？还是要我给到代码级接入步骤？」 | 探询型：按回答分支（有数据 → 比对 / 分析路径，无数据 → 接入步骤） |
| **performance** | 「你已经有 profiling 数据了吗（采集产物）？还是要我给采集指引？」 | 探询型：按回答分支（同上） |
| **interrupt** | —（不预先问） | 条件型：日志不足以定位（缺层 / 缺栈 / 内核级事件）**或**已定位到层但缺源码级手段（竞争 / 越界 / 多机网络）时才展开 |

**探询型闸门的两半都要走完**：对方答"有数据"不等于这一步结束——闸表里"有数据"那半挂的是**读法**（看哪一份产物、按什么顺序看、哪些是定位面哪些只是现象）。只给"那你去分析吧"等于把这一步留空；那半的 `refs` 与"无数据"半同样要给。

**分支动作与词条不在此重复**（改一处即生效，避免散文与数据双源漂移）：走闸表的 `branches[].action` / `refs`。每条声明了 category 的工具词条都必须被某个闸门绑定（CI 校验"有入口"），所以"这个工具我该什么时候用"的答案**只在闸表里**——不要凭记忆给命令。

**探询锚点**：问句要带这条 case 具体要确认的字段或产物（例：「这条 case 要确认 X，你手上有 dump 吗？」），而不是开放式地问「你有没有数据」——后者逼工程师先猜类别再猜产物，答错了还得第二轮；加载后问的才是事实。

三条纪律：

- **探询只问一次、只问一句**——问完按对方回答走，不要"顺便把步骤也讲了"。
- **给接入步骤时必须区分改谁**：改**用户业务代码**（加 `PrecisionDebugger` 等）风险低；改**框架源码**（vLLM/verl 的 runner 等）属"改被测系统"，必须标注临时性 + 给回滚方式。
- **命令以客户环境为准 + 先排除采集副作用**：具体命令以客户环境的工具版本为准（版本差异以实际输出为准，不照搬示例）；采集行为本身可能让问题消失（工具介入的副作用），先排除再下结论——判据词条见闸表 `caveat_refs`。

> 展开细节见 `references/diagnosis-procedure.md` 步骤 1。

**始终要避的坑（内联，不必读 reference 就知道）**：
- **两种缺信息，两个时机**：①路由信息（症状/框架/版本/平台/部署形态）不全 → 步骤 1 问，**按步骤 1 那张固定行覆盖表逐行核，"提取不到"就是待问项**（不靠当场自评"我是不是漏问了什么"——平台、触发位置、已试过什么这三行的漏问都发生在自评上）；②验证候选所需的精确配置值（某 `--additional-config` 字段/量化档/硬件型号）→ 本步按需问。别混、别让用户全量倒；**别在确认该字段前把 provisional 结论写成 `hit`**（先给低置信假设 + 明确要什么来验证）。
- **版本软匹配**：compat 不符只降 confidence、不硬排除（soft match）；没填的维度跳过。
- **category 决定 quickly_check 形态**：interrupt→grep 签名；precision→数值阈值；performance→profiler 指标；**别混**。
- **活锁 ≠ 组件故障**：同一请求/实体以固定节奏（~1s）重复打同一条日志、且计数冻结 → 判"控制循环活锁"（调度/接纳/抢占在反复重试却无法推进），**向控制循环上游走**——别把"发日志的组件"当故障组件（load/传输后端常只是表象，真实支点在调度/接纳/抢占层）。
- **判别优先追问**：多假设并存时，先问能二分命中的那个问题（如"PD prefill 节点是否禁用了抢占？"这类**控制/调度**维度，而非数据流细节），再补数据流/传输细节——一刀命中，避免在错误维度上堆证据。
- **类别冲突不得二选一（但有先后）**：日志/报错签名指向的方向与**症状性质**冲突时（例：症状是"输出乱码"→ precision，日志却是 store/BM 初始化失败 → interrupt 味），**按症状的性质定 category——症状是工程师手上那个现象，日志签名只是线索**；自动单选先走症状那条线，**在同一屏里说明另一条线的存在**（它需要哪些信息才走得通）。给一句覆盖点：「若你更关心 X，说一声我就切过去」——**不要停下来问他"你觉得这是哪类问题"**：他答不了这个判断，那正是要找你的原因。日志签名一侧的证据不丢：它作为备选线写明换向条件，不因为当前没走就删掉。
- **反馈要挂账，不靠记性**：给完 fix **不在这里反问结果**（他还没应用）；立即写 `feedback`（`feedback_pending_since` 一并写）并给一条可复制的回报指令。反馈捕获是学习环的吞吐上限，而它原先只有一个**人在新会话里想起来**的入口。
- **连续失败 ≤2（只计 fix 未解决）**：同一个问题给过两次 fix、客户应用后都未解决 → 转人工，不试第三个。**候选被 quickly_check 排除不计入**（那是候选穷尽，不是失败）。
- **跨机比时间先核时钟**：拿多机日志排先后（"哪个 rank 先挂""哪台先断"）之前，取各机都会记的**同一个事件**（任务启动 / HCCL 初始化 / 集群心跳）比时间差——秒级以内可直接排序，明显漂移或先后颠倒就把顺序结论**降级为不确定**并写明。时钟漂移不报错，它只是让"最早的那个"换成另一个节点。时间戳整体差整数小时多是单机时区配置，不是漂移（展开与留痕见 `references/diagnosis-procedure.md` 步骤 5）。

## 方法缺口（流程加载——候选全部未命中时才走这一步）

**何时**：所有 Tier 2 候选都未命中、进入步骤 5 深度排查时——**此时这一步是必走的**（已有候选命中才不走；
跳过它等于把方法面留空）。**不在候选之前加载**——候选命中时流程用不上，
提前加载只是多花注意力预算（原则九）；这是**成本论断**，不是"早加载更危险"
（第四轮对照：流程先行 11/11 未致偏离命中 case，故"会锚定"未获支持，强度如实标为设计判断）。

**怎么做**（绑定在**本 skill 的** `references/procedure-gates.yaml` 的 `kind: procedure` 闸门，id 由 `verify_references.py` 校验）：

1. 读**仓库根先验层的** `references/_procedure-index.yaml`（**选择器**，只有几十行：总条数 + `category → 分片文件 + 条数 + 成本`；注意与上面那句的
   `references/` 不是同一个目录——skill 支撑文件在 `skills/diagnose/references/`，先验层在仓库根 `references/`）：从中找**本轮 category 那一行**，按 `shard` 打开**该分片**；选择器里若另有 `_cross` 片（不限定类别），任何 category 都要一并打开。**本 category 没有对应分片** → 打开选择器列出的**全部分片**再选，并在 trace 写明"本 category 无专用分片"——空手去深度排查与"库中没有可用流程"是两件事，不能让前者冒充后者。**不要为了省事整读全部分片**：选择器分片的意义就是本轮只付自己那一片的成本。
2. 在分片里用 `title`/`summary` 选**一条**最贴合的流程（分片行是完整的选择器行，不截断）——**默认一条**。若该流程的前提与现场证据**明确矛盾**（如它要求的数据形态在你手上根本不成立），可换一条：同样受"连续失败 ≤2"约束，并在 trace 记冲突理由；
3. 按该行的 `file` 打开词条，读 **`content.flow[]` 全文**（step / action / check / when_to_use）——**摘要行不算加载**：实测只读摘要与不读等效，流程的反直觉判据会被摘要截断（例：摘要写"同步比例 > 0.2 则存在慢卡"，漏掉"慢卡 = WTR 最小的卡"）；
4. 按流程执行：用每步的 `check` 当判定口径（阈值、分流条件），**跳步要说明理由**；
5. 某步所需数据不在手上（流程要看"逐卡计算耗时"而导出里没有）→ 如实记 `gap`，**不臆断分支结论**；
6. 记 trace：`{action: reference_lookup, ref_id, purpose: procedure}` + `{action: procedure_follow, ref_id, steps_executed, branch_taken, gap}`（字段见 `references/diagnosis-trace.md`）。

> **流程是参考，不是判词**：流程给的是"这类问题怎么查"，不是"这次就是这个"。**它与现场证据冲突时以证据为准**（记 `conflict` 字段），
> 分支结论仍需数据支撑才进结论；
> 且流程走通并解决了问题**不免除 case 沉淀**（方法解决一次不等于这次事故不值得成为 case）。
>
> **流程错了也要能被发现**：跟随流程给出 fix、但工程师回报没解决时，在 `attribution` 事件里写
> `component: reference:<ref-id>`——这样"被跟随后仍失败"的流程能进组件失败簇聚合（`component_tally.py`），
> 否则流程层只有加载率、没有失败率，错流程会被稳定注入而无人察觉。

## severity 闸门（命中后先看这个）

读候选 case 的 `severity` 字段，决定输出策略：

- `benign` → 直接给 fix
- `service-affecting` → 给 fix，但标注 `fix_side_effects`（如 requires-restart），让人协调窗口
- `data-loss-risk`（如"checkpoint 可能被污染"）→ **不直接给 fix**，输出"先停训练、保留现场、通知 owner"。高危 root cause 的正确动作是 halt 不是 patch

每个 `fix_on_mismatch` 都带 `rollback`——人应用失败时能回退。

## 命中时的输出格式（4 段必需 + 2 个按需块）

> **判读口径**：输出的段数与长度应与**问题复杂度相关**。根因明确、fix 是单个开关时，四段写完即可。
> **一件事只说一遍**——同一信息在"结论先行"与后续分节各写一次就是冗余（盲评对照里这是最被诟病的一点）。

**行文**：对话输出是给人读的，按 `docs/spec/writing-norms.md` 写（可选论证层，不影响本 skill 执行）；本面的定制条款见该文件 §3 的「诊断对话输出」一行。写 trace 的字段时另见 `references/diagnosis-trace.md` 的「行文口径」。

**必需四段**（顺序即优先级）：

1. **结论先行**——一句话：现象 + 根因 + 改哪个开关（无内部词表）。
2. **依据链**——每条结论 → 支撑它的证据/检查结果，**逐条标强度**：`已验证`（本轮实际执行过）/`推测`（依赖推断、未直接验证）/`数据`（历史积累，非本轮判断）。
   命中 case 时，把「命中 case / 路由依据 / 排除链 / 匹配症状 / 版本匹配 / 历史表现」作为**本段的子清单**列出，不另起一段：
   - **命中 case 的 id 与统计必写**：`<CASE-ID>`（confidence `<score>`，历史命中 `<hits>` / 误诊 `<misdiagnoses>`）——它是工程师回溯知识库、以及反馈闭环回写 confidence 的锚点，**不要省**；
   - 排除链要给出检查明细；材料没给的如实标"未提供"，**不写"已验证"**；
   - 版本匹配按软匹配口径（compat 不符只降 confidence）；历史表现标为「数据」。
3. **修复方案**——精确命令或 diff 要点 + `rollback` + side-effect（需重启 / 需升级驱动等）+ **应用后如何验证生效**。
   `fix_type` 决定呈现：`env-var` / `config-change` 直接给可执行命令；`code-patch` 给改动文件 + diff 要点（**不可直接执行**）；`pending-investigation` 给排查建议。
   **前提未验证时把核验写成修复的第 0 步**（例：case 的 compat 是 `hdk <26.1` 而客户没报 HDK 版本 → 第 0 步先 `npu-smi info` 核版本，前提不成立就转 plan B），不要带着未验证的前提直接开方。
4. **可靠度与残余风险**——**confidence 分档讲明**：`>0.8` 高可信直接应用、`0.5–0.8` 中可信（应用同时备 plan B）、`<0.5` 仅作提示重点靠手动排查。
   另给：哪些是推测、**触发/不触发面**（什么条件用得上这条结论）、follow-up。

**两个按需块**（不要默认展开）：

- **机制原理**——源码/流程层面的因果链。**展开就讲完整**（触发前置条件 → 每步的"为什么" → 因→果闭环），不得压成一句；命中且根因已由依据链说清时不展开。
  去 AI 味 ≠ 删机制：机制与可核对性必须保留，只把内部词表/交叉引用翻译成因果白话。
- **时间线**——按日志时间排列的可观察事实，只放可观察项、不夹判断；仅当排查跨多轮、或时间先后本身是判据时展开。

## 每步必写 trace（硬要求）

每个 step 后往 `traces/<session_id>.yaml`（每个并发诊断一文件；模板见 `diagnosis_state.yaml.example`）的 `trace` 数组追加一条。**trace 是完整交互轨迹（trajectory）**——统一 `{role, ...}` 结构：

- **先解析 trace 目录（一次，之后全程用它）**：`python3 scripts/shared_dir.py traces` 打印的绝对路径就是本次要读写的 `traces/`——它锚在**主检出**（同一克隆的所有 worktree 共读共写），所以从 worktree 干活也不会把记录写进一个主检出看不到、清理 worktree 就消失的地方。**本 skill 里所有 `traces/…` 的读写（含最前面的trace 相似检测）都以这个路径为准**，别写相对 `traces/`。

- **agent 事件**：`{role: agent, step, action: triage|load_index|quickly_check|load_full|run_check|hit|miss|tier3|feedback|reference_lookup|triage_semantic|source_analysis|attribution|resume|procedure_follow|report, output, reason, ...}`。`output` 给用户（可精简）、`reason` 记决策依据（**关键决策必写**）；`triage` 必带 `routed`（未命中写 `[]`）；`source_analysis` 必记 `tool_calls`；`attribution` 执行错可加 `component`；`report` 记 `report_file`（人读报告产出，**全路**步骤 6 必写一条；快路不产报告、也不写这条，但证据落盘与 `reason` 照旧必写）；`reference_lookup` 记 `purpose`（collect / signature / fix / background / procedure）与 **`outcome`（hit / miss / skipped，`skipped` 必写理由）**——三态缺一，"没查"就与"查了没命中"同形。
- **user 事件**：`{role: user, step, content, evidence}`——`content` 摘要（短）+ `evidence` 完整证据（`inline` 原文 / `files` 相对路径 / `sources` URL / `missing` 缺口）。
- **证据落盘铁律（必走，无例外）**：短原文 → `inline` 存完整原文；长命令/配置/日志块/附件 → **先写 `traces/evidence/<session_id>/<名>.txt`** 完整原文、`evidence.files` 用相对路径引用、`inline` 只留一行"完整原文见 evidence.files" + 关键指纹。**禁止**只写摘要、或把原文压成指纹塞 `inline`。
- **写前自检**：问"用户贴的原文现在在哪？"——答不出"已存在文件"的相对路径或完整 `inline` → 证据未落，先落盘再写 trace。
- **原件引文要核（有原件时）**：工程师交来**原件**（日志文件 / 日志包 / 交接包）时，引用原文另落 `evidence.quotes: [{file, line, quote}]`，并在写报告前跑 `python3 scripts/verify_evidence.py <trace> --root <原件根>`；报不一致 / 找不到 / 行号越界的引文不能支撑结论——对应结论**降级为推测**，或回步骤 4 重新取证（核不过是"这条引文不能用"，不是"结论错"）。对话里**粘贴**的片段没有原件：不填 `quotes`、不因此降级，写一句"无原件可核"即可。字段与判定见 `references/diagnosis-trace.md`。
- **时间戳**：建 session 写顶层 `created_at`；**每次写 trace 刷新顶层 `updated_at`**（含 resume 续接——置顶诊断面板）。
- **知识库版本**：建 session 时写顶层 `kb_rev`（`python3 scripts/kb_rev.py` 的末行 = 检出 HEAD 短 sha），**一次写定、之后不改**。它记的是"这一单跑在哪一版 `knowledge/` 上"：跨机接手时接手方要拿它比对本机版本（不一致意味着候选集与 case id 可能对不上，接手侧会看到提示），事后误诊归因也要它（"当时为什么没命中"取决于当时库里有什么）。拿不到 git 就写 `unknown`，别编值。
- **trace 边界（只记诊断轨迹 + 误诊归因，别混自演进）**：用户中途提出的**流程改进/设计讨论**不是本诊断输入（自演进信号）——走 `traces/evidence/<session_id>/<session_id>_evnote.md`（渐进式披露，正常定位不披露，真要改 SKILL/脚本时才升级为 EV 卡）；`attribution` 执行错归因**仅限"确实影响本次结论"**，纯流程改进走 EV 卡。**别把改进讨论写成 trace 的 user/agent 事件**，也别用 `source_analysis` 记 skill 编辑。

> 完整细节（`KNOWN_ACTIONS` 词表、外部事实获取落盘、agent 事件两层、反馈闭环格式、词表同步纪律）见 `references/diagnosis-trace.md`。trace 是误诊归因的唯一依据：误诊先读 trace 断 **case 错**（改库）还是**执行错**（改 skill）。不写 trace → 无法归因 → 可能改坏正确的 case。

## 源码分析（深度排查的子步骤，入口在步骤 5）

报错签名指向框架代码/算子名/量化描述表（如 `fault kernel_name=QuantBatchMatMulV3`、`modelslim_config.py` 相关 KeyError）且 Tier 3 未覆盖时：

1. **按报错背景确定是哪个源码仓，再向其确认版本**（`scripts/src_fetch.py --list` 看已支持仓库：如 vllm-ascend / torch-npu / CANN / mindspeed-* / verl 等，取决于报错签名指向哪——源码分析依赖对应版本，不要猜）。
2. **获取源码（统一走 `scripts/src_fetch.py` 确定性入口——按版本取，不是"本地有什么用什么"）**：`python3 scripts/src_fetch.py <repo> --ref <tag>`（`--list` 看已知仓库与 host：vllm-ascend=GitHub、mindspeed-*=GitCode、torch-npu=GitCode、verl=GitHub；未知/私有 → `--url`；`--list-versions` 看本地已有版本）。缓存**按版本平铺**在 `src-code/<org>/<repo>/<tag>/`（缓存根在主检出、跨 worktree 共读；各版本目录互不干扰，并发诊断各读各版本），命中即复用、该版本缺失即按已知 host 拉取。
   **退出码就是契约，别只看输出里的路径**：`0` = 该版本已在本地产出**并核对通过**（stdout 末行 = 路径）；`3` = tag 解析不了（多半 tag 名不同，输出里有可用 tag 示例）；`4` = 拉取失败（网络/私网）；`5` = 本地该版本目录核对不通过（确认要它才 `--force` 重拉）。**非零退出 = 没拿到这个版本的源码**——不要拿本地其他版本的目录去读（那是错版本的证据），也不要拿 web 搜索结果当源码（搜上游 issue/PR 状态是步骤 5 的事，不是源码来源）。
   **「不落库」= 源码不随仓库提交、也不写进知识库**；分析仍要保留源码（`src-code/` 本地缓存），知识库只记 `source_ref` 代码指针。
3. **grep 定位**：搜报错签名/算子名/函数名（如 `grep -rn "QuantBatchMatMulV3" vllm_ascend/`）→ 读相关文件片段 → 分析根因。
4. **追问用户验证**：对照预期/复现/补环境信息，验证根因假设。
5. **follow-up**：查知识库是否已覆盖；`gh search issues/prs` 看上游是否已修复——**「已修复」不是结论、是待验证的假设**：上游有 PR / issue 已 closed 都不等于**你的部署版本里有这个修复**（PR 可能只进主干未 backport；镜像 / fork / 定制构建不能按版本号推断）。给「升级即可」之前必须做**落地实证**：从修复 PR 提取修复特征行 → 在你部署的那份代码里确认它在（做法、反证规则与结论分档见 `references/diagnosis-procedure.md` 步骤 5 的「上游修复的落地实证」）。未修复→根因+workaround；联网不可达→诚实说明无法查证。
6. **多层级**：根因指向更底层开源仓（torch-npu）→ 同样流程分析其源码（`source_ref` 指向该仓）；CANN 等未开源 → **承认局限**，给方向 + 建议联系华为。
7. **沉淀**：根因清楚且知识库未覆盖 → `/skill:to-postmortem` 记 `source_ref: {repo, ref, file, line}`；**顺手**沉淀跨事故稳定的结构事实 → `/skill:to-reference`（software-fact / env-var-table / compat-matrix，判据："6 个月后/跨版本是否仍成立"）。

## 不要做

- 不要替人决定 root cause——给结构化清单，人执行后贴回结果
- 不要连续尝试第三个 case——**两次 fix 未解决**即转人工（误诊保护的串联保护；候选被排除不计入）
- 不要把全量 profiler 灌进 context——裁剪到相关 rank + 栈尾
- 不要用 interrupt 的 grep 思路建 precision 的 quickly_check（category 形态不同）
- **不要直接改本 skill / triage / reference 等会进诊断上下文的资产——改进动作必须先产 EV 卡**（`scripts/ev_proposal.py --new`）再涉及。诊断中发现的流程改进（执行错/摩擦）走 `attribution`（执行错归因喂 component_tally）或 EV 卡（主动设计改进），**不混入本诊断 trace**。
- 被打断 → `/skill:resume-diagnosis`
