# 持续运行：长期任务、issue 评测循环、执行记录与可视化

> 四份文档的分工：**[evolution-pipeline.md](evolution-pipeline.md)** 机制总览；**[evolution-execution.md](evolution-execution.md)** 单卡执行契约；**[evolution-orchestration.md](evolution-orchestration.md)** 单轮会话编排；**本文是运行视图**——回答"我下一条指令后，系统作为**持续自演进系统**怎么跑、跑到什么时候停、我怎么看到它在跑"。它把前三份的单轮/单卡机制装配成用户可下指令、可观察、可干预的长期运行形态。使用者侧的一句话指令/报告/干预语言见 **[evolution-user-guide.md](evolution-user-guide.md)**（UX 规格）。
> 推导依据：原则一/五/七/八/九/十/十一；理论见 design-theory §4.2–4.4 与 §6。**本文自身修订 = L3 结构（methodology PR + 体系维护人审）。**

## 1. 从一条指令到持续自演进（愿景总览）

**自演进是隐形执行策略**：用户不需要说"要记录观测数据、走 feedback loop、按 self-evolving 制定计划"——这些是系统的默认行为，就像让"跑一次诊断"不需要复述三层加载流程。用户指令的典型形态是一句话目标：

> "持续改进 vllm-ascend 的诊断命中率" / "这周有哪些值得沉淀的 verl issue？" / "自演进最近变贵了，查一下"

系统在入口做四件事（对齐协议见 orchestration §1.2）：

1. **装载默认策略**（隐形）：观测信号集、S2 评测、feedback loop、proposal→action→eval、授权分级、停止条件、预算分层——全部自动带出，用户零复述；
2. **对齐目标**：回显理解 + 澄清歧义（范围哪层？数据前提够不够？目标是否冲突？），**没对齐不执行**；
3. **开一个长期任务**（第 2 节）：goal + scope + 预算策略 + 每轮循环（拉取 → 评测 → 沉淀 → 候选 → 实验 → 合入 → 报告）；
4. **全程留痕 + 可观察**（第 4/5/6 节）：每次 skill 调用记录执行数据；任务/卡/指标渲染给人看。

> 反例（不要把机制塞进指令）："持续基于 vllm-ascend 的 closed 与 open issue（先拉 200 个）做沉淀迭代，之后持续分批拉取，按 self-evolving 制定计划与角色任务，每次调用 skill 都记录 trace/metrics 供 feedback loop 与 proposal→action→eval 闭环……"——这段里除了"vllm-ascend + 持续改进"是目标，其余全是实现细节，应由默认策略承接。要求用户说这些 = 把系统内部机制暴露成用户负担。

## 2. 长期任务层（机制 A）：多轮循环，不是单轮会话

orchestration §1 的会话是**单轮**（目标 → 装载默认策略 → 对齐 → 计划 → 确认 → 执行/报告 → 停）。用户的指令是一个**长期任务**——一轮做完不结束，而是按数据增量继续下一轮。

```
长期任务（goal_id + scope + issue 源配置 + 预算策略 + 停止条件 + approval_policy 运行模式）
  ├─ 每轮 = 一次 orchestration 会话（复用 §1 协议）
  │    拉新批次 → S2 评测 + 沉淀评估 → 候选 → 授权 → 实验 → 攒批 → 报告
  │    运行模式（pipeline §6.3a）：hands-off（默认，全部攒批到任务完成一次 PR）
  │    或 default（auto 即时 + review/dual 攒批轮末 PR）
  ├─ 轮间调度器决定下一轮范围：
  │    新 closed issue？→ 评测/沉淀轮
  │    待观察窗结算的 adopted？→ 回测轮
  │    open issue 转 closed？→ 自动评测（见第 3 节——无需延迟等待，增量拉取自然捕获）
  │    metrics 漂移？→ 诊断式候选轮
  └─ 状态：active → paused（预算/人中断）→ steady（收敛降频）→ stopped（人终止）
```

任务状态落 `proposals/tasks/<TASK-ID>.yaml`（goal、scope、来源配置、每轮引用、预算账本、停止原因），**运行时状态，本地留存、gitignore**（稳态结果以报告/采纳卡入 git）。任务是容器，会话是任务的一次执行——session state 与 task state 分离（task 记得目标与历史，session 记得本轮进度）。

**DSH 载体映射**：任务轮间调度（拉新批次 → 决定下一轮范围 → 分派轮内角色）可落到 DSH 的 **Agent Teams**（experimental：持久 roster + 共享任务 DAG + 持久 mailbox，含 blockedBy 依赖边——天然表达"回测轮依赖评测轮完成"）；轮内单步用 continuable subagent 即可。载体选项与启用条件见 evolution-pipeline.md §6.7，机制与载体解耦——无 DSH 环境时任务状态文件 + 手动/定时触发同样成立。

## 3. Issue 的三重角色与 S2 即时对照（机制 B 修正）

**修正**：早期讨论把 open issue 设计成"预诊断 → 等 closed → 对照"的延迟机制——**这是错的绕路**。高质量 issue（closed、maintainer 确认 resolution）本身就是"现象 → 根因"的带标注样本：拉取时**答案已在手上**，diagnose 评测 = 输入现象、对照维护者结论，**即时出分**，不需要等任何未来事件。issue 数据同时承担三重角色：

| 角色 | 用途 | 说明 |
|---|---|---|
| **评测数据集** | S2 即时对照（pipeline §2.1）：系统输出 vs issue resolution | 每批 closed issue = 一次可自动评分的诊断考试；分数进 feedback loop。**与沉淀素材解耦：先评测后沉淀**（见下"解耦"段） |
| **沉淀素材** | to-postmortem / to-reference 的案例来源 | 评测完成后的 issue 才允许沉淀为 case/reference（issue-ingest 已做）；已沉淀 issue 不进 S2 test 半 |
| **覆盖缺口信号** | open issue：系统对某 open issue 现象无法诊断/无 case 候选 → 缺覆盖 | open issue **无答案，只能作弱信号**（诚实退化：不做"诊断确诊"，只记"未覆盖"） |

**open issue 的正确处理**（替代"延迟对照"）：open 池只做**覆盖探测**——现象喂 diagnose，无命中/低置信 → 记"该现象族未覆盖"候选（进待定池），**不做结论判定**（无 resolution 可对照）。issue 转 closed 后自动进入评测池（增量拉取游标天然捕获 open→closed 转换），从那一刻起才有答案、才参与 S2。

**S2 校准集的 selection/test 分离（审查可补点 1）**：S2 池分两半——`selection`（gate 决策用，改 skill 前后对照打分）与 `test`（validated 终判用，防对校准集过拟合）。规则：**gate 决策只看 selection，validated 终判只看 test**；test 半不参与任何中间对照（对应 SkillOpt 的 held-out test，防系统"记住"校准集）。

**S2 评测集与沉淀来源必须解耦（防自我参照污染，方案级关键）**：S2 评测的 issue 若已被沉淀成 case（issue→to-postmortem→case 是同一循环），系统会"命中自己刚沉淀的答案"——S2 高分只证明"记住了自己写的题"，不证明对**未见现象**的诊断能力。解耦规则：

- **先评测后沉淀**：一批新 closed issue 先全部过 S2 评测（对照 resolution 打分，此时知识库还没有这批 issue 的 case），**评测完才允许沉淀**——评测分数反映"用旧知识解新题"；
- **沉淀过的 issue 不进 test 半**：test 半只放"从未被本系统沉淀过的历史 issue"（或沉淀前的历史快照期），保证 validated 终判是对未见题的检验；
- **诚实标注**：若某期 test 半被迫混入已沉淀 issue（池子小），指标标注 `test 含已沉淀源` 并降权，不伪装纯净。

这一条与 selection/test 分离正交：分离防"过拟合校准集"，解耦防"用自己沉淀的答案考自己"——两者都缺则 S2 分数虚高。落地时 S2 池管理（issue-ingest 的 processed 排除）需按此扩展：processed 同时记"已评测"与"已沉淀"，两集合分离。

## 4. 统一执行记录（机制 C）：每次 diagnose / skill 调用都留数据

现状：**只有 diagnose 写 trace**；to-postmortem / to-reference / issue-ingest / knowledge-groom / 自演进各 agent 动作不落执行数据——feedback loop 的数据源只有诊断一侧。扩展为**统一 skill 执行日志**：

```
每次 skill 调用写一条执行记录（traces/ 或 metrics/skill-exec-log.yaml）：
- 调用：skill 名 + 版本 + 时间 + 触发者（任务 id / 会话 id / 人）
- 输入摘要（脱敏纪律同 execution §2：原文留本地，日志只记引用与聚合）
- 产出：case/reference/卡 id、状态流转
- 命中与成本：命中组件、耗时、token
- decision reason：关键决策的一句话依据（agent 的 reason 字段）
```

用途：metrics 有全链路数据源（不只诊断命中率）；归因能定位到"沉淀环节"还是"诊断环节"错；token 账本能精确到每次调用（第 3.3 节 orchestration 的预算治理才有数据）。**边界**：记录对象是 skill 与动作、产物 id——**不是人**（不引入身份维度，roadmap「不做 KPI/身份/使用观测」红线不变，见 pipeline §5.3）。

## 5. 替换与回滚（机制 D）：新 idea 替换旧实现

当前 schema 只有单卡生命周期（rejected = 终态）。用户场景"发现 proposal 没效果、或有了更好的 idea 可回滚之前的"需要**卡间关系**：

- idea 卡加 `supersedes: [EV-xxx]` / `superseded_by: EV-yyy` 字段；
- **替代卡可在旧卡任意阶段提出**（包括旧卡还在 adopted 观察窗内——这正是"新 idea 更好"的典型场景），但旧卡状态按其在位阶段流转：
  - 旧卡仍 candidate/proposed/in_experiment → 新卡提出即旧卡标 `superseded`（未合入，无回滚负担），`superseded_by` 指向新卡；
  - 旧卡 **pending_merge（批提交模式 §6.3a 攒批待审）** → 新卡提出即旧卡标 superseded 并**从批中撤出**（不再进聚合 PR）——它还未合入，没有观察窗证据要保留，撤出避免把已被替代的改动送审浪费人注意力；
  - 旧卡已 adopted（观察窗内）→ 新卡进入实验，**旧卡观察窗继续结算到终点**（若旧卡先 validated 再被新卡 validated 顶替 → 旧卡 superseded；若旧卡先 rolled_back → 新卡自动成为唯一实现）。**避免"新卡还没验证就废弃观察窗中的旧卡"**——观察窗是旧卡效果的唯一证据，中途废弃等于丢失对照；
  - 旧卡已 validated → 新卡 validated 后旧卡 superseded（原表述，最常见路径）。
- 回滚语义升级：rolled_back 时若该卡 supersedes 某旧卡 → **回滚到被替代版本**（git revert 到旧卡合入点），而不是回滚到空白。**链式 supersede 的处理（A→B→C 链回滚 C）**：沿 `superseded_by` 链回溯，回滚到**链上最近一张 validated 的实现**——若 B 已 superseded（在 A 之上被替代、非 validated 终态），则跳过 B 回到 A（或链上更早的 validated 卡）；若链上没有 validated 卡（全是降级态/未验证），回滚到链首的初始实现并标注"链上无 validated 版本"。**回滚目标 = 最近的有效实现，不是机械的紧邻旧卡**——这保证回滚后系统处于"曾被验证过"的状态，而非中间试验态；
- 追溯链：卡 → supersedes 链 → decisions → 实验记录 → 合入 commit，任何一点可回看"现在的实现是谁、替代了谁、为什么"。**一条不变式：同一时刻每个 target_component 至多一张 validated/在位卡**——supersede 链保证实现可追溯回单一版本。

## 6. 可视化（机制 E）：让"看到系统自演进"成为可能

数据**已经存在**（session state、trace、decisions、token 账本），缺的是渲染层。视图分四层：

| 视图 | 内容 | 数据源 |
|---|---|---|
| 任务总览 | 任务列表/状态（active/paused/steady）、每轮结果摘要、token 总账 | proposals/tasks/ |
| 会话直播 | 当前轮进度：进行到哪一步、在跑哪个 agent、下一步计划 | session state + 执行日志 |
| 卡流转 | 每卡状态机（candidate→…→validated/rolled_back/superseded）+ decisions 链 + 实验结论 | proposals/ideas/ |
| 指标 | 四层指标（execution §6）+ 回滚率 + 每 validated 卡 token | timeline + 台账 |

载体三档，按落地成本排序：

1. **dsh-agent-teams 插件活动面板**（[NanmiCoder/dsh-agent-teams](https://github.com/NanmiCoder/dsh-agent-teams)，已装 0.1.14）：自带成员树 + 任务 DAG + 实时状态 + 会话跟随 + 历史归档。**覆盖边界要诚实**：它可视化的是 **agent team 的协作运行态**（哪个成员在跑哪个任务、依赖进度、模型标注），数据源是 `<workspace>/.agent-teams/<teamId>/`——**不含**本设计的领域状态：EV 卡状态机、timeline 指标、token 账本、跨轮任务历史（这些在 proposals/tasks|ideas/ + metrics/）。所以它只能覆盖上面"会话直播"视图的 agent 执行部分；"卡流转""指标""任务总览"仍需自建。**结论：它是执行载体的一部分可视化，不是自演进系统可视化本身**——只对"让 agent 协作过程可见"有用；
2. **DSH 面板扩展**（仓库已有 ascend-panel 先例，诊断/指标 tab 加"自演进"tab）：补领域视图（任务总览/卡流转/指标/token），与 proposals/ + timeline + trace/decisions 数据直连。**这才是"看到系统自演进"的正确载体**；
3. **HTML 报告**（health_report 同款，离线生成）：无 DSH 环境或需分享时的兜底。

诚实标注同 O7：〔中心全量〕或〔本地视角〕。agent 的操作序列与决策 reason 已随 trace 记录，渲染即"看到系统在自演进"。

## 7. 停止条件汇总（"跑到什么样停止"）

**每轮**（orchestration §2.2）：预算耗尽 / 产出达 N validated / 连续 M 否决（信号误报）/ 收敛（无新信号）/ 人中断——任一即停，出报告。

**任务级**（本层新增）：达到稳态（连续两轮无新信号且 validated 效果达标）→ `steady` 降频（orchestration §2.3）；人随时 `paused`/`stopped`；预算策略（如每周 token 上限）耗尽 → `paused` 等下一周期。

**批边界（pipeline §6.3a，任务级攒批启用后仍强制；任务级攒批本身是蓝图态，见 pipeline §11.1）**：任务级攒批（"做到目标完成再提 PR"）下，批不无限等——攒批卡数上限 / 时间上限 / 稳态收敛任一触发即提聚合 PR 结算，不等目标完成；用户可续开新任务继续。**攒批是体验优化（少打断），不是无限延迟合入**。

**长期安全阀**：回滚率或抽审发现率超阈值 → 任务自动降授权级别（auto→review）并通知人（自我指涉治理，orchestration §4）。

### 7.1 报告的用户语言规范（UX 规格见 evolution-user-guide.md §4）

报告**首行回答用户的原始目标**，机制细节折叠——用户下的是"命中率低"，要看到的是"解决了吗、提升多少"，不是内部状态（validated X 卡 / token Y）：

> 目标：提升 vllm-ascend interrupt 命中率。
> 本轮：新增 case 2 条覆盖此前未命中的启动参数类问题；在 20 条历史 issue 上回测 3/7 → 5/7。
> 验证依据：真实 issue 对照（非系统自评）。[展开] 卡明细 / token / 待审改动

每条结论标注**证据强度来源**（pipeline §2.1 评分源分级渲染成用户可读的信任信号）：真实 issue 对照验证（S2，可点开看是哪几条）/ 工程师反馈确认（S1，最高但稀缺）/ 仅回放无回归（S3，下限保障）/ 系统推断（最低）。validated 结论必须可**点开证据**（issue、diff、前后指标）——用户不必只信系统自评。

### 7.2 中途干预的用户话术（UX 规格见 evolution-user-guide.md §5）

三种干预写进用户指南，执行语义在此定义：**"停一下"** = 本轮停止 + 出中间报告 + 状态保留；**"方向不对，改重点看 X"** = 当前方向终止、未完成项保留、按新方向继续（resume 时先对齐新目标，不原样硬跑）；**"这条改动有问题，回滚"** = 该卡 rolled_back（用户侧触发，记录留痕）。需要人的决策点（dual 审批/抽审）**入队为待办并通知人**，不阻塞能自动的部分。

## 8. 落地工程形态：不是单个 skill，是四层装配

回答"最后落地的工程是 skill 吗"——**不是单一 skill**。对照仓库现有载体（skills/ = 流程定义、scripts/ = 确定性逻辑、dsh-plugins/ = DSH 运行时、docs/ = 机制），这套自演进体系按仓库的既有分工落地为四层，每层选对应载体：

| 层 | 工程形态 | 载体 | 对应用例 |
|---|---|---|---|
| **流程协议** | 新的 skill（如 `self-evolve`） | `skills/self-evolve/SKILL.md` | 描述"跑一轮自演进"的会话协议（orchestration §1.2）：目标 → 默认策略装载 → 对齐 → 计划 → 观察窗执行 → 报告。**skill = agent 可加载的执行协议**，类似 knowledge-groom 的地位，但触发语义同 groom（disable-model-invocation，人显式触发，防自发批量改库） |
| **确定性逻辑** | 一批脚本 | `scripts/` | S2 评测打分（issue→replay→对照）、component-tally 累积、token 记账、执行日志汇总——凡机械可判的环节脚本化，agent 只读聚合输出（原则二/九） |
| **领域状态** | 数据文件 | `proposals/` + `metrics/component-tally.yaml` | **git 归属分层（对齐仓库 .gitignore 哲学：运行时状态不进 git，稳态资产才进）**：`proposals/ideas/` 是资产（卡含最终状态与 decisions，随 PR 进出，同 knowledge/ 纪律，脱敏后入 git）；`proposals/tasks|sessions|reviews|experiments/` 是**运行时状态**（进度、token 账本、逐轮变化，类比 traces/ 与 inbox 草稿）——本地留存、gitignore，稳态结果以报告/采纳项投影入 git。台账是词法数据可 diff（原则三），CI 校验 schema（ideas/ 与台账 schema） |
| **可视化** | DSH Cordis 插件 | `dsh-plugins/self-evolve-panel/`（host/client）+ 加载 skill（preload-panel 先例） | run §6 领域视图（任务总览/卡流转/指标）——**不是** dsh-agent-teams 的活动面板（那只是 agent 协作态视图） |

**为什么不能只做一个 skill**：skill 定义"agent 怎么做"，但它不承载确定性校验（脚本）、不承载可 diff 状态（数据文件）、不承载运行时渲染（插件）。四类能力在仓库里本就是四种载体，自演进横跨全部四类——单 skill 会把校验/状态/可视化塞进 prompt 协议，违反原则二（不变量写进结构）。dsh-agent-teams 插件属于"执行载体"层（§6.7），不在上述四层内——它提供多 agent 运行底座，可被 self-evolve skill 调用，但不是自演进工程本身。

**落地时先做哪层**：按 pipeline.md §11 总纲（非本表）——先确定性逻辑（S2 评测脚本）与领域状态（proposals/ 骨架，ideas 入 git、运行时状态 gitignore），再流程协议（self-evolve skill 包裹已跑通的脚本与状态机），最后可视化（面板）。skill 是"装配说明书"，把脚本+状态+协议串成可重复执行的一轮；面板让过程可见。

## 9. 落地顺序（运行层视图；**整体落地总纲见 pipeline.md §11**，本表从"一条用户指令"视角排序，不平行于 §11）

| 步骤 | 内容 | 入口闸门 |
|---|---|---|
| 1 | S2 校准集建立 + selection/test 划分（先 20 条验证，再扩 200，对应 §11 Phase C2） | issue 池可批量取（已具备） |
| 2 | 统一执行记录（先 diagnose + issue-ingest，再扩展到全部 skill，对应 §11 Phase A–B） | 记录 schema 定稿 |
| 3 | 长期任务层试点一轮（手动触发，任务状态机 + 轮间调度跑通，对应 §11 Phase D） | 步骤 1–2 有真实数据 |
| 4 | supersede 字段 + 回滚语义落地（schema 已含字段，出现首个替代场景时激活，对应 §11 Phase D） | 出现首个"新 idea 替代旧实现"场景 |
| 5 | 可视化（DSH 面板扩展或 HTML 报告，对应 §11 Phase E 后） | 任务层跑通 ≥1 轮 |

与用户指令的对应：这条指令即第一个长期任务——**先拉 200 个 issue（步骤 1 的扩池），前几轮的真实产出是"通电"（建 S2、接执行日志、跑通任务循环），之后才进入持续的沉淀与演进**。诚实边界不变：内容层（补 case/沉淀）可高度自动，结构层（triage/skill/指标口径）永远人审。

## 10. 原则追溯

| 设计元素 | 服务的原则 | 说明 |
|---|---|---|
| issue 即带标注评测集、即时对照 | 八（可观测先于改进）、十 | 答案随拉取可得，无需延迟机制；open 只作弱信号不冒充结论 |
| selection/test 分离 | 一（验证先于交付） | 防对校准集过拟合，validated 终判用未见过的 test |
| 统一执行记录（对象是 skill 非人） | 八、九 | feedback loop 全链路数据；不碰身份红线 |
| supersede 关系与回滚到被替代版本 | 七（变更可逆） | 替换可追溯，回滚粒度到"上一个有效实现" |
| 可视化四层视图 | 八、十 | 让"人在看系统演进"成为可能而非宣称 |
| 任务级稳态降频与安全阀 | 九、十一 | 持续运行必须有资源与质量边界 |
| 四层工程装配（skill/脚本/数据/面板） | 二、三 | 校验进脚本、状态进词法文件、协议进 skill、渲染进插件——单 skill 会违反原则二 |
