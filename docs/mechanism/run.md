# 持续运行：长期任务、issue 评测循环、执行记录与可视化

> 本文是持续运行的设计文档，回答三件事：长期任务怎么排、执行记录怎么留、面板看什么。要改长期任务、统一执行记录或可视化时读它；读完能说清执行记录的读写口径，以及它供哪些视图使用。论证层，日常不必读；执行规则与机制地图见 [rsi-mechanism.md](rsi-mechanism.md)。
>
> 本文与另外三份文档的分工：[pipeline.md](pipeline.md) 是机制总览，[execution.md](execution.md) 是单卡执行契约，[orchestration.md](orchestration.md) 是单轮会话编排。本文把前三份的单轮与单卡机制装配成用户可下指令、可观察、可干预的长期运行形态。使用者侧的指令、报告与干预语言见 [evolution-user-guide.md](../guide/evolution-user-guide.md)。
> 设计依据是 [design-principles.md](../spec/design-principles.md) 的原则一、五、七、八、九、十、十一，理论推导见 [design-theory.md](../spec/design-theory.md) §4.2–4.4 与 §6。本文自身的修订属于 L3（工作流与编排层，分层定义见 [pipeline.md](pipeline.md) §1）结构变更，走 methodology PR 并经体系维护人审。

## 1. 从一条指令到持续自演进

自演进的默认策略由系统承接，用户不必说出要记录观测数据、要跑反馈回路、要按自演进制定计划。用户指令的典型形态是一句话目标：

> 持续改进 vllm-ascend 的诊断命中率。
> 这周有哪些值得沉淀的 verl issue？
> 自演进最近变贵了，查一下。

系统在入口做四件事，对齐协议见 [orchestration.md](orchestration.md) §1.2：

1. 装载默认策略。观测信号集、S2 评测、反馈回路、改进项从提出到验证的流程、授权分级、停止条件与预算分层全部自动带出，用户不需要复述。
2. 对齐目标。系统回显自己的理解并澄清歧义：范围落在哪一层、数据前提够不够、目标之间是否冲突。没有对齐就不执行。
3. 开一个长期任务，见第 2 节。任务是目标、范围、预算策略与每轮循环（拉取 → 评测 → 沉淀 → 候选 → 实验 → 合入 → 报告）。
4. 全程留痕并可观察，见第 4、5、6 节。内容 skill 在收尾时落一条执行记录（诊断侧已有 trace，见第 4 节），任务、卡与指标渲染给人看。

反例是把机制写进指令：

> 持续基于 vllm-ascend 的 closed 与 open issue（先拉 200 个）做沉淀迭代，之后持续分批拉取，按 self-evolving 制定计划与角色任务，每次调用 skill 都记录 trace/metrics 供 feedback loop 与 proposal→action→eval 闭环……

这段里只有 vllm-ascend 与持续改进是目标，其余都是实现细节，应当由默认策略承接。要求用户说出这些细节，等于把系统内部机制变成用户负担。

## 2. 长期任务层：多轮循环

[orchestration.md](orchestration.md) §1 的会话是单轮的：目标 → 装载默认策略 → 对齐 → 计划 → 确认 → 执行并报告 → 停止。用户的指令对应一个长期任务，一轮做完不结束，下一轮按数据增量继续。

长期任务由六个字段定义：`goal_id`、`scope`、issue 源配置、预算策略、停止条件与运行模式 `approval_policy`。

每轮是一次 orchestration 会话，复用 §1 的协议，顺序为：拉新批次 → S2 评测与沉淀评估 → 候选 → 授权 → 实验 → 批提交 → 报告。运行模式见 [pipeline.md](pipeline.md) §6.3a，有两种取值：

- `default`（关键人审，默认）：`auto` 级改动即时合入，`review` 与 `dual` 级留到轮末提一个批提交；
- `hands-off`（完全自动化，需要用户明确要求）：全部改动留到任务完成时提一个批提交。

轮间调度器按上一轮的产出决定下一轮范围：

| 上一轮的产出 | 下一轮 |
|---|---|
| 新 closed issue | 评测与沉淀轮 |
| 待观察窗结算的 validated 卡 | 回测轮 |
| open issue 转 closed | 自动评测，见第 3 节。增量拉取会自然捕获这一转换，不需要延迟等待 |
| 指标漂移 | 诊断式候选轮 |

任务状态有四个取值：

- `active`：任务在跑，默认取值；
- `paused`：预算耗尽或人中断；
- `steady`：收敛后降频（降频本身是蓝图，见第 7 节）；
- `stopped`：人终止。

任务状态写在 `proposals/tasks/<TASK-ID>.yaml`，含目标、范围、来源配置、每轮引用、预算账本与停止原因。它是运行时状态，本地留存、不进 git；稳态结果以报告与采纳卡入 git。任务状态与会话状态分开：任务记得目标与历史，会话记得本轮进度。

轮间调度（拉新批次 → 决定下一轮范围 → 分派轮内角色）在 DSH 上由 Agent Teams 承载。它是实验性载体，提供持久成员表（roster）、共享任务图（DAG）与持久信箱（mailbox），任务图带 `blockedBy` 依赖边，可以直接表达回测轮依赖评测轮完成这一关系；轮内单步用可续接的 subagent 即可。载体选项与启用条件见 [pipeline.md](pipeline.md) §6.7。机制与载体解耦：没有 DSH 环境时，任务状态文件加手动或定时触发同样成立。

## 3. Issue 的三重角色与 S2 即时对照

issue 的 resolution（fix PR 合入、committer 确认或 issue 内的用户反馈）本身就是反馈，不只是评测数据。S2 replay 把它系统化：以 issue 现象作为 diagnose 的输入，对照维护者结论评分。issue 数据因此承担三重角色：

| 角色 | 用途 | 说明 |
|---|---|---|
| 反馈源（内容验证） | S2 对照，见 [pipeline.md](pipeline.md) §2.1。命中且结论一致记 case 的 `validation_record.consistent`，即内容被外部验证；命中但结论不符记 `inconsistent`，是复审信号 | 2026-09 起由 `scripts/settle_s2_feedback.py` 结算进 case，不再只留在 result 文件里。与沉淀素材解耦：先评测后沉淀 |
| 沉淀素材 | to-postmortem 与 to-reference 的案例来源 | 评测完成后的 issue 才允许沉淀为 case 或 reference（issue-ingest 已按此执行） |
| 覆盖缺口信号 | open issue：系统对某个现象无法诊断，也没有 case 候选，就是缺覆盖 | open issue 没有答案，只能作弱信号：不做诊断确诊，只记该现象族未覆盖 |

open issue 不参与对照评分，只做覆盖探测：把现象交给 diagnose，若没有命中或置信度低，就记一条该现象族未覆盖的候选（进待定池）；此时没有 resolution 可对照，不做结论判定。issue 转 closed 后自动进入评测池，增量拉取的游标会捕获这一转换，从那一刻起它才有答案、才参与 S2。

S2 校准集的 selection 与 test 分离是规模闸门。原设计分 selection（供闸门决策）与 test（供 validated 终判，防对校准集过拟合，对应 SkillOpt 的 held-out，即留出、不参与调参的样本，见 [pipeline.md](pipeline.md) §12）两半，但池子小，撑不起两半：test 半要求从未被本系统沉淀过的历史 issue，而沉淀会消耗池子，小池下 test 半自相矛盾。降级后的规则是单池运行，直到出现真实的 held-out 需求。原「≥30」是参数估计，不是硬门槛；[design-theory.md](../spec/design-theory.md) §7 说明常数接受实测重校。扩池是 issue 流自然流入的持续动作，单池加自我指涉隔离（self-referential 隔离：评测样本不得由本系统自己沉淀，见本节末尾三条）已经覆盖防过拟合的主要威胁。当前单池 19 条，其中 11 条的 resolution 信号强度为 high（由 fix commit 或 PR 指认；分级见 [pipeline.md](pipeline.md) §2.1；复算：\`grep -c "^    confidence: high" eval/s2/vllm-ascend.yaml\`）。replay 分数标 `source: issue-replay`；validated 终判标注无 held-out test（池小），依赖 selection 对照与人工抽审。

S2 评测集与沉淀来源解耦这条规则保留，self-referential 隔离在任何规模都执行。评测用的 issue 如果已经被沉淀成 case（issue → to-postmortem → case 是同一个循环），重放命中的只是系统自己写下的答案，高分不构成外部验证。隔离有三条：

- 先评测后沉淀。一批新 closed issue 先全部过 S2 评测（对照 resolution 打分，此时知识库还没有这批 issue 的 case），评测完成才允许沉淀。这样分数反映的是用旧知识解新题。
- 结算隔离。`scripts/settle_s2_feedback.py` 结算时检查两件事：replay 的 issue 是否正是该 case 的沉淀来源（`references`、`sources` 或 `urls` 字段含该 issue 的 URL），以及该 case 的正文是否引用过这个 issue（`issues/<n>`、`pull/<n>`、`#<n>`）。命中任一条就记 `self_consistent`，不计入 `consistent`，也不计为外部验证。
- 混入已沉淀源时标注。池子小的时候某一期可能混入已沉淀源，指标要标 `test 含已沉淀源` 并降权。这是 S2 单池日常评测的标注口径；门控台另有做法：吸收样本整体拆进回归池、不进判定池（[eval-arena.md](eval-arena.md) §2）。

S2 池管理还需要扩展（issue-ingest 的 `processed` 排除）：`processed` 要同时记已评测与已沉淀，两个集合分开。

## 4. 统一执行记录：内容 skill 收尾留数据

diagnose 写 trace，不再重复落 exec-log。内容 skill（issue-ingest、to-postmortem、to-reference、knowledge-groom）在收尾 evolve-check 之前落一条 exec-log；evolve-check 自己也落一条，包括没有演进信号的情况，否则跑了无信号与根本没跑在数据上无法区分。schema 见 `metrics/skill-exec-log.yaml`，只追加；`scripts/log_skill_exec.py` 负责写，`scripts/verify_exec_log.py` 校验 seq 唯一与字段。evolve-check 第 1 步用 `scripts/tail_exec_log.py` 读执行记录，不依赖 agent 记忆。`scripts/verify_exec_log.py` 不进 CI（CI 环境没有这个运行时文件），由 evolve-check 第 4 步自查。

exec-log 只记录内容流程收尾时的现场情况，不做每次 skill 调用的全量记录。diagnose 已有 trace，信息更全、含完整轨迹，再落一份 exec-log 是重复劳动；高频调用全记录会让记录负担超过观测价值（[design-principles.md](../spec/design-principles.md) 原则九）。记录对象是 skill、动作与产物 id，不涉及人，不引入身份维度：roadmap 不做 KPI、身份与使用观测这条红线不变，见 [pipeline.md](pipeline.md) §5.3 的相容性论证与 §9 的明确不做。每条记录包含：

```
- 调用：skill 名 + 版本 + 时间 + 来源（触发者：任务 id / 会话 id / 上游 skill）
- 产出：case/reference/卡 id、状态流转
- decision reason：关键决策的一句话依据（agent 的 reason 字段）
- cost：token（无记账环境用估算，并标 source: estimate）
```

用途有三个：指标在内容流程侧有数据源（沉淀量、采纳、`process_friction`）；归因能区分沉淀环节与诊断环节（诊断侧看 trace，沉淀侧看 exec-log）；evolve-check 收尾读它拿本轮现场，不靠 agent 记忆。

读法一律走 `scripts/tail_exec_log.py`：人读尾巴，`--summary` 聚合，`--json` 给面板。不要在别处重新实现解析：datetime 归一、路径解析与缺失退化只应有一份实现，路径解析在 `scripts/exec_log_path.py`。执行记录经 `scripts/exec_log_path.py` 解析到主检出，同一克隆内所有 worktree 共写共读，写侧持 flock；无锁的并发实测里 16 次写入只剩 3 条。文件缺失或空表按正常退化处理，退出码 0。

边界是同一克隆内共享，跨克隆与跨机不聚合。跨机的数据走聚合值进 timeline 这条路，且已经接线：`scripts/metrics_snapshot.py` 组装每期快照时，把 `tail_exec_log --summary` 的聚合（`content_flow_runs`、`evolve_check_runs`、`evolve_check_no_signal`）作为内容流程侧写进当期的指标源文件 `metrics/timeline.d/<期号>.yaml`。聚合文件 `metrics/timeline.yaml` 由 `scripts/build_timeline.py` 重建，是生成物，不要手写。执行记录本身不进 git。

## 5. 替换与回滚：新改进项替换旧实现

现有 schema 只描述单张卡的生命周期，`rejected` 是终态，表达不了发现某项改动没效果、或者有了更好的想法要回滚到之前实现这样的场景。卡之间因此需要关系字段：

- 改进项加两个字段：`supersedes` 列出本卡替代的旧卡 id，`superseded_by` 指向替代它的新卡 id。不替代时 `supersedes` 为空列表，`superseded_by` 为 `null`。
- 替代卡可以在旧卡的任意阶段提出。卡状态只有四个取值：`in_experiment`、`validated`、`rejected`、`superseded`，不包括 `candidate`、`pending_merge`、`adopted` 这类 git 协作状态与待办状态；卡状态只是 agent 的决策档案，批提交与合入在流程层完成。旧卡按它在位的阶段流转：
  - 旧卡处于 `in_experiment`（执行中、未终判）：新卡提出时旧卡标 `superseded`，`superseded_by` 指向新卡。旧卡还没有终判，没有回滚负担；它的改动如果已经进入批提交，就从批里撤出，因为尚未合入，不需要保留观察窗证据。
  - 旧卡已经 `validated`（已采纳，合入后还在观察窗内）：新卡进入实验，旧卡的观察窗继续结算到终点。若旧卡先在观察窗内确认有效、之后被新卡替代，旧卡标 `superseded`；若旧卡先因现场退化被回滚（观察窗判定为 `rolled_back`，按本节「回滚粒度到被替代版本」一条执行 `git revert`），旧卡的合入已被撤销，新卡成为该组件上唯一的在跑实现，不需要额外动作。不要在新卡还没有验证时就废弃观察窗中的旧卡：观察窗是旧卡效果的证据，中途废弃会丢失对照。
  - 旧卡 `validated` 且观察窗已经结算：新卡 validated 之后旧卡标 `superseded`，这是最常见的路径。
- 回滚粒度到被替代版本。观察窗判定为 `rolled_back` 时，如果该卡 `supersedes` 某张旧卡，就回滚到被替代版本，用 `git revert` 回到旧卡的合入点，而不是回滚到空白。链式替代（A → B → C 的链回滚 C）沿 `supersedes` 链向前驱回溯（`superseded_by` 指向替代它的新卡，走不到前驱），回滚到链上最近一张 `validated` 的实现：若 B 已在 A 之上被替代、不是 `validated` 终态，就跳过 B 回到 A 或链上更早的 `validated` 卡；若链上没有 `validated` 卡，回滚到链首的初始实现，并标注链上无 validated 版本。回滚目标是最近的有效实现，不是紧邻的旧卡，这样系统回到的是曾经验证过的状态，不是中间试验态。
- 追溯链是：卡 → `supersedes` 链 → `decisions` → 实验记录 → 合入 commit。这条链回答两个问题：现在的实现是谁、替代了谁，看卡与 `supersedes`/`superseded_by` 链；为什么替代，看 `decisions` 里逐条追加的判断（`supersedes` 链本身不含原因），再往下追到实验记录与合入 commit。有一条不变式：同一时刻每个 `target_component` 至多一张 `validated` 卡。

## 6. 可视化

需要的数据已经存在（任务状态、trace、`decisions`、token 账本），缺的是渲染层。视图分四层（按展示对象划分，与第 8 节的工程载体分层是两套划分）：

| 视图 | 内容 | 数据源 |
|---|---|---|
| 任务总览 | 任务列表与状态（`active`、`paused`、`steady`、`stopped`）、每轮结果摘要、token 总账 | `proposals/tasks/` |
| 会话直播 | 当前轮进度：进行到哪一步、在跑哪个 agent、下一步计划 | 会话状态与执行记录 |
| 卡流转 | 每卡状态机（`in_experiment` → `validated` / `rejected` / `superseded`）、`decisions` 链与实验结论 | `proposals/ideas/` |
| 指标 | 四层指标（见 [execution.md](execution.md) §6）、回滚率、每张 validated 卡的 token | timeline 与归因事件聚合 |

载体三档，按落地成本排序：

1. dsh-agent-teams 插件的活动面板（[NanmiCoder/dsh-agent-teams](https://github.com/NanmiCoder/dsh-agent-teams)，已装 0.1.14）：自带成员树、任务图、实时状态、会话跟随与历史归档。它可视化的是多 agent 协作的运行状态（哪个成员在跑哪个任务、依赖进度、模型标注），数据源是 `<workspace>/.agent-teams/<teamId>/`，不含本设计的领域状态：改进项状态机、timeline 指标、token 账本与跨轮任务历史都在 `proposals/` 与 `metrics/` 里。因此它只覆盖会话直播视图中的 agent 执行部分，卡流转、指标与任务总览仍需自建。
2. DSH 面板扩展（仓库已有 ascend-panel 先例，在诊断与指标 tab 之外加自演进 tab）：补齐领域视图（任务总览、卡流转、指标、token），直接读 `proposals/`、timeline 与 trace/decisions 的数据，是看到系统自演进的主要载体。
3. HTML 报告（与 health_report 同款，离线生成）：没有 DSH 环境或需要分享时使用。

视图要按数据来源标注〔中心全量〕或〔本地视角〕：〔中心全量〕是中心侧汇总的全部会话，〔本地视角〕是本机克隆内读到的会话；同一指令在不同环境执行时数据范围不同，两种读数不得混用（出处见 [roadmap.md](../plan/roadmap.md) 的健康报表事项）。agent 的操作序列与决策原因已经随 trace 记录，渲染出来就能看到系统在自演进。

## 7. 停止条件汇总

每轮（[orchestration.md](orchestration.md) §2.2）遇到任一条件即停，停止后出报告：

- 预算耗尽；
- 产出的 validated 卡达到设定张数（默认 3）；
- 连续被否决的候选达到设定个数（默认 3）；
- 收敛：本轮没有新候选，或全部卡进入 `rejected`/`validated`；
- 人中断。

任务级停止条件（本层新增）：达到稳态（连续两轮没有新信号，且 validated 的效果达标）后转 `steady` 降频（[orchestration.md](orchestration.md) §2.3；稳态降频目前是蓝图，见 [pipeline.md](pipeline.md) §11.1）；人可以随时置 `paused` 或 `stopped`；预算策略（例如每周 token 上限）耗尽时转 `paused`，等下一个周期。

批边界（[pipeline.md](pipeline.md) §6.3a）：任务级批提交是做到目标完成再提 PR，批不会无限等待。任务级批提交本身是蓝图（见 [pipeline.md](pipeline.md) §11.1），但启用后本边界仍然强制。批内卡数上限、时间上限或稳态收敛任一触发就提前提批结算，不等目标完成，用户可以再开新任务继续。批提交是为了少打断，不是无限延迟合入。

长期保护措施：判据文件 `proposals/gates.yaml` 里的越界项触发时，任务按人的处置降低授权级别（`auto` → `review`），并把待处置项通知人（自我指涉治理，见 [orchestration.md](orchestration.md) §4）。回滚率与抽审发现率是这项保护计划接入的读数，尚未落成判据。

### 7.1 报告的用户语言规范

使用者侧的规格见 [evolution-user-guide.md](../guide/evolution-user-guide.md) §4。

报告首行回答用户的原始目标，机制细节折叠在后面。用户报的是命中率低，关心的是问题解决没有、提升了多少，而不是内部状态。报告示例：

> 目标：提升 vllm-ascend interrupt 命中率。
> 本轮：新增 case 2 条覆盖此前未命中的启动参数类问题；在 20 条历史 issue 上回测 3/7 → 5/7。
> 验证依据：真实 issue 对照（非系统自评）。[展开] 卡明细 / token / 待审改动

每条结论标注证据强度来源，即 [pipeline.md](pipeline.md) §2.1 的评分源分级渲染成用户可读的信任信号。五种来源（分级见 [evolution-user-guide.md](../guide/evolution-user-guide.md) §4）：真实 issue 对照验证（S2，可以点开看是哪几条）、工程师反馈确认（S1，强度最高但稀少）、只有回放无回归（S3，下限保障）、观察窗超时降级（没等到现场反馈，按现有证据降级结算；蓝图）、系统推断（强度最低）。validated 的结论要能点开证据（issue、diff、前后指标），用户不必只信系统自评。

### 7.2 中途干预的用户话术

使用者侧的规格见 [evolution-user-guide.md](../guide/evolution-user-guide.md) §5。三种干预的执行语义在这里定义：

- 「停一下」：本轮停止，出中间报告，保留状态。
- 「方向不对，改重点看 X」：当前方向终止，未完成项保留，按新方向继续；恢复时先对齐新目标，不按原方向硬跑。
- 「这条改动有问题，回滚」：该卡在观察窗判定为 `rolled_back`，由用户侧触发，结果作为追加 decision 记录留痕。

需要人决策的点（`dual` 双签或 `auto` 抽审）进入批 PR 的待审项（面板上显示为积压），由 reviewer 或双签人消费；它们不阻塞能自动的部分。

## 8. 落地工程形态：四层装配

仓库的载体分工是：`skills/` 放流程定义，`scripts/` 放确定性逻辑，`dsh-plugins/` 放 DSH 运行时，`docs/` 放机制说明。自演进体系按这套分工落地为四层载体（按工程形态划分，与第 6 节的视图分层不是一套），每层选择对应载体：

| 层 | 工程形态 | 载体 | 对应用例 |
|---|---|---|---|
| 流程协议 | 新的 skill（如 `self-evolve`） | `skills/self-evolve/SKILL.md` | 描述跑一轮自演进的会话协议（[orchestration.md](orchestration.md) §1.2）：目标 → 默认策略装载 → 对齐 → 计划 → 观察窗执行 → 报告。skill 是 agent 可加载的执行协议，地位类似 knowledge-groom，但触发语义同 groom：`disable-model-invocation`，由人显式触发，防自发批量改库 |
| 确定性逻辑 | 一批脚本 | `scripts/` | S2 评测打分（issue → replay → 对照）、`settle_s2_feedback` 结算、归因事件按需聚合（`component_tally`）、执行日志（`log_skill_exec`）。机械可判的环节脚本化，agent 只读聚合输出（[design-principles.md](../spec/design-principles.md) 原则二、九） |
| 领域状态 | 数据文件 | `proposals/` | 按是否进 git 分层：运行时状态不进 git，稳态资产才进。`proposals/ideas/` 是资产（卡含最终状态与 `decisions`，随 PR 进出，同 knowledge/ 的纪律，脱敏后入 git）；`proposals/tasks/`、`proposals/sessions/`、`proposals/reviews/`、`proposals/experiments/` 是运行时状态（进度、token 账本、逐轮变化，类比 `traces/` 与 inbox 草稿），本地留存、不进 git，稳态结果以报告或采纳项进入 git。归因事件在 `traces/`（运行时），按需聚合，不建常驻表；`ideas/` 的结构由 `scripts/verify_proposals.py --check` 在 CI 校验 |
| 可视化 | DSH Cordis 插件 | `dsh-plugins/self-evolve-panel/`（host/client）加加载 skill（先例见 preload-panel） | 第 6 节的领域视图（任务总览、卡流转、指标），不是 dsh-agent-teams 的活动面板（那只是 agent 协作状态视图） |

自演进体系不能只做成一个 skill：skill 定义 agent 怎么做，但不承载确定性校验（脚本）、可 diff 的状态（数据文件）与运行时渲染（插件）。这四类能力在仓库里本来就是四种载体，自演进横跨全部四类；只做成 skill 会把校验、状态与可视化塞进 prompt 协议，违反 [design-principles.md](../spec/design-principles.md) 原则二（不变量写进结构）。dsh-agent-teams 插件属于执行载体层（[pipeline.md](pipeline.md) §6.7），不在上述四层内：它提供多 agent 运行底座，可以被 self-evolve skill 调用，但不是自演进工程本身。

先做哪一层按 [pipeline.md](pipeline.md) §11 的总纲排，不看本表：先确定性逻辑（S2 评测脚本）与领域状态（`proposals/` 骨架，`ideas/` 入 git，运行时状态不进 git），再流程协议（self-evolve skill 把已跑通的脚本与状态机包起来），最后可视化（面板）。skill 把脚本、状态与协议装配成可重复执行的一轮，面板让过程可见。

## 9. 落地顺序

本节从一条用户指令的视角排列落地步骤，整体落地总纲见 [pipeline.md](pipeline.md) §11。

| 步骤 | 内容 | 入口闸门 |
|---|---|---|
| 1 | S2 校准集建立（单池；实时条数见 `eval/s2/vllm-ascend.yaml`；selection/test 分离按判定池中未吸收样本的条数触发，见 [eval-arena.md](eval-arena.md) §1） | issue 池可批量取（已具备） |
| 2 | 统一执行记录：内容 skill 收尾落 exec-log，evolve-check 读现场 | 已落地。schema、脚本、4 个内容 skill 的收尾（含 groom）、evolve-check 自落记录、`scripts/tail_exec_log.py` 取数入口、`scripts/exec_log_path.py` 共享路径都已就位，`ideas/` 卡结构由 `scripts/verify_proposals.py --check` 在 CI 校验。diagnose 走 trace，不重复落（§4 的边界）。执行记录在同一克隆内共享（跨 worktree 共写共读，写侧持锁）；跨克隆与跨机的数据已经接线：`scripts/metrics_snapshot.py` 把 exec-log 聚合写进当期指标源文件 `metrics/timeline.d/<期号>.yaml`（§4） |
| 2b | S2 feedback 结算（`settle_s2_feedback` → `case.validation_record`） | 已落地；真实 S2 result 积累到一批后结算首轮 |
| 3 | 长期任务层试点一轮（手动触发，任务状态机与轮间调度跑通，对应 [pipeline.md](pipeline.md) §11 的自演进执行流程试点阶段） | 步骤 1–2b 有真实数据 |
| 4 | `supersedes` 字段与回滚语义落地（schema 已含字段，出现首个替代场景时激活，对应 [pipeline.md](pipeline.md) §11 的自演进执行流程试点阶段） | 出现首个新改进项替代旧实现的场景 |
| 5 | 可视化（DSH 面板扩展或 HTML 报告，对应 [pipeline.md](pipeline.md) §11 的扩权与参数校准常态化阶段之后） | 任务层跑通一轮以上 |

对应用户指令：持续改进这类指令就是第一个长期任务，先拉 200 个 issue 扩池（步骤 1）。前几轮的真实产出是第一批落地：建 S2、接执行记录、跑通任务循环，让机制第一次真实运行；之后才进入持续的沉淀与演进。边界不变：内容层（补 case、沉淀）可以高度自动，结构层（triage、skill、指标口径）永远由人审。

## 10. 原则追溯

下表的设计元素对应 [design-principles.md](../spec/design-principles.md) 的条文。

| 设计元素 | 服务的原则 | 说明 |
|---|---|---|
| issue 即带标注的评测集与即时对照 | 八（可观测先于改进）、十 | 答案随拉取可得，不需要延迟机制；open issue 只作弱信号，不冒充结论 |
| selection/test 分离（规模闸门） | 一（验证先于交付） | 按判定池中未吸收样本的条数触发（原「≥30」是参数估计，已按实测重校，见 [eval-arena.md](eval-arena.md) §1）：够支撑判定后再分两半防过拟合；当前单池，配合 self-referential 隔离（`self_consistent`） |
| 统一执行记录（对象是 skill 而非人，内容流程收尾时落） | 八、九 | 覆盖内容流程全链路的数据；不碰身份红线；diagnose 走 trace，不重复落 |
| `supersedes` 关系与回滚到被替代版本 | 七（变更可逆） | 替换可追溯，回滚粒度到上一个有效实现 |
| 可视化四层视图 | 八、十 | 把系统演进渲染给人看，不再只靠文字宣称 |
| 任务级稳态降频与阈值保护 | 九、十一 | 持续运行必须有资源与质量边界 |
| 四层工程装配（skill、脚本、数据、面板） | 二、三 | 校验进脚本、状态进词法文件、协议进 skill、渲染进插件；只做成 skill 会违反原则二 |

## 11. 名词对照

正文用白话。改脚本、查数据文件时，用这张表换成代码与文件里的实际名字。

| 正文里说 | 代码与文件里的名字 |
|---|---|
| 长期任务 | `proposals/tasks/<TASK-ID>.yaml` |
| 改进项、卡 | `proposals/ideas/` 下的卡 |
| 卡状态 | `in_experiment`、`validated`、`rejected`、`superseded` |
| 观察窗判定 | `rolled_back`，作为追加 decision 记录留痕 |
| 执行记录 | `metrics/skill-exec-log.yaml`（运行时文件） |
| 运行模式 | `hands-off`、`default` |
| 授权分级 | `auto`、`review`、`dual`，见 [pipeline.md](pipeline.md) §6.3a |
| 运行模式字段 | `approval_policy` |
| 内容流程收尾 | `evolve-check` |
| 自指隔离样本 | `self_consistent` |
| 轮间调度载体 | DSH Agent Teams（实验性），见 [pipeline.md](pipeline.md) §6.7 |
| 四层视图 | 面板视图，数据源为 `proposals/`、`metrics/timeline.yaml` 与 `traces/` |

