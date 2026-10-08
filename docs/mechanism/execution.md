# 执行链路：改进项契约、合入后跟踪（follow-up）与效果度量

> 给谁读：要改改进项信息契约或评审判据的人。
> 什么时候读：你要改「一张卡必须记什么、怎么判它该不该合」时。
> 读完能做什么：按契约写出一张卡，并说清它的验证方式与效果度量落在哪。
> 本文属论证层，日常执行不必读。执行规则与机制地图见 [rsi-mechanism.md](rsi-mechanism.md)。

> 本文是 [pipeline.md](pipeline.md) 的执行级规范。机制总览（三层闭环、分级授权、状态机、落地节奏）在那篇。本文回答执行时的四个问题：一张改进项卡要记录什么信息；改动的验证如何区分「合入前可判」与「合入后需真实反馈」；一次知识沉淀的效果怎么度量；agent 在每个决策点拿到什么信息。
> 把一轮自演进作为可审计会话来运行（人怎么下指令、目标函数与停止条件、token 预算、自我指涉治理），见 [orchestration.md](orchestration.md)。把一轮轮会话装配成长期持续运行（长期任务、issue 评测循环、执行记录、可视化），见 [run.md](run.md)。面向使用者的指令与报告语言，见 [evolution-user-guide.md](../guide/evolution-user-guide.md)。
> 推导依据：原则一（验证先于交付）、二（不变量写进结构）、五（建议与决定分离）、七（变更可逆）、八（可观测先于改进）、九（资源预算）、十一（数据触发）。理论见 [design-theory.md](../spec/design-theory.md) §4.2–4.4。本文自身的修订属于 L3 结构，走 methodology PR 加体系维护人审。本文的内容将来落成 skill 时，执行参数要内联进 SKILL.md（skill 自包含纪律），本文退为可选论证层。

## 1. 为什么需要执行级规范

v2 机制把「观测 → 候选 → 授权 → 合入」串了起来，但执行时 agent 与评审人仍会卡在四个空洞：

1. 改进项卡的可执行性没有契约。一张卡写「修订 triage 分支 vllm-ascend 启动参数族」，agent 不知道改哪几行、现状行为是什么、怎么算改完、改完影响谁。
2. 依赖真实场景的改动缺 follow-up 环节。对 content 与 fix 两类改动，旧机制只验证到「合入时 golden 通过」，没有回答这条改动在真实使用里是否真的改善、没改善算谁的责任、何时回滚。即时判定类不在此列，它们在合入前已由 S2（拿已闭环 issue 重跑 diagnose 做对照）与 golden（回归样本回放）验证。
3. 每次沉淀的效果没有定义。知识库整体有命中率，但「这次 to-postmortem 或 to-reference 沉淀的那条 case 是否有效」没有度量口径：沉淀时没有预期，沉淀后没有跟踪。
4. agent 执行时信息供给不足。决策点只有聚合值，没有执行所需的完整证据与历史先例。

统一框架是把每张改进项卡、每次沉淀当成一次带预期的实验：执行前写下可测的 `predicted_effect`，执行后进入 follow-up 观察窗，对照预期判定（达标、再迭代、回滚），判定结果写回卡、指标与归因事件（按需聚合）。合理性不是合入那一刻的静态判断，而是「预期 → 实测」对照的动态闭环。

## 2. 改进项信息契约（skill 与流程优化）

适用对象：skill 步骤、triage 分支、quickly_check、script、提示词。

契约的目标是让 agent 拿到卡就能回答四个问题：改哪、现状是什么、怎么算改完、影响谁。下表列的是契约项，其中一部分今天已经是卡 schema 的字段，另一部分写在卡的正文里：`hypothesis`、`predicted_effect` 与 `validation`（其下含 `method`、`baseline`、`success_criteria`、`rollback`）是卡字段；`baseline_behavior` 记在 `validation.baseline`；`edit_semantics` 记在 `hypothesis` 与 `decisions`；`affected_paths` 目前没有对应字段。卡 schema 的必填字段清单见 `scripts/verify_proposals.py:90` 的 REQUIRED 列表。

| 契约项 | 要写什么 | 缺了会怎样 |
|---|---|---|
| `target_component` | 组件标识。实测取值都是仓库内路径，例如 `scripts/eval_arena.py`、`skills/diagnose/SKILL.md`、`skills/diagnose/references/diagnosis-procedure.md` | 不知道改哪，或改错组件 |
| `baseline_behavior` | 改前快照，加 1 到 3 个具体反例：输入（症状、日志原文或充分证据）与当前的错误输出。反例来自 trace、issue 或 postmortem | 无法验证改完是否真的变了：没有改前读数的改后读数没有意义 |
| `edit_semantics` | 编辑语义：add / delete / modify，加新旧规则对照（可以写成 diff 形态） | 只给方向不给处方，agent 自由发挥改偏 |
| `affected_paths` | 该组件被哪些下游流程引用：谁调它，影响哪些 namespace 与 category | 修好 A 弄坏 B。改 triage 会影响全部诊断 |
| `hypothesis` | 因果链：触发信号 → 归因（组件错）→ 为什么这样改能修好 | 处方与诊断脱节，改了错的地方 |
| `predicted_effect` | 可测预期：误诊率从 X 降到 Y、该类 issue 命中率升 Z、错例复测归位率 | 没有 follow-up 判定的基准，改动无法证伪 |
| `predicted_effect.measure` | 预测的出处（可复现）：一条命令加期望（`expect_exit` 与 `expect_stdout` 至少一项），任何 reviewer 都能跑。确实不可度量时声明 `reason`。它与 `source_signals.trajectory` 对称：问题可回放，预测可复现（`from` 由 trajectory 支撑，`to` 由本条支撑） | 预测退化成散文，reviewer 无法机械判定，只能打开全文或直接批准（第 7 节的橡皮图章） |
| `verification` | 验证数据（S2 校准、golden、归因事件复测）、改前改后的测法、观察窗长度（见第 5 节）。落到卡上分别是 `validation.method` 与 `validation.success_criteria` | 不可证伪的变更不该合入 |
| `rollback` | 回滚方式：revert、分支丢弃或配置开关。落到卡的 `validation.rollback` | 原则七落空 |

脱敏纪律在信息完整性与隐私之间取舍。卡进 git 时只含聚合值与证据引用（trace 路径加事件索引、issue 号加段落号），不含客户现场原文，与 eval fixture 同一纪律（见 .gitignore 注释）。原文留在本地 `traces/evidence/`，同一文件系统内的执行 agent 可以读。跨机器或对外分享时，证据降级为摘要，并在卡上标注缺失的部分，不把摘要写成完整证据。

## 3. 知识沉淀契约（case 与 reference）

适用对象：to-postmortem 与 to-reference 的产出、groom 预分诊三分类（new_pattern / variant_of / covered_by）、Tier 3 转正。

与 skill 优化的区别：这里要回答的不是「改什么」，而是「值不值得沉淀、沉淀后有没有效」。

| 契约项 | 要写什么 | 判定用途 |
|---|---|---|
| `source_evidence` | 来源（issue、trace 或 postmortem id），加现象、日志、根因的证据引用 | 判断证据是否充分；缺证据的沉淀置信度低 |
| `sediment_form` | 新 case、variant 并入（作为已有 case 的一个变体并入，不新建）、reference、Tier 3 转正 | 决定验证方式与审批路径 |
| `evidence_strength` | 症状、根因、fix 三类证据各自的强度：确证、推测或缺失 | 定初始置信度，也是标注的依据 |
| `verification` | 来源验证档位，按来源形态分而不按 issue 分：`upstream-fix-merged`（关联的 fix PR 已合入）、`upstream-official-doc`（上游官方发布的案例或指南文档，含定位链与验证结论）、`upstream-maintainer-confirmed`、`investigation`、`engineer-report` | 定初始 score 的先验档位。它与 `evidence_strength` 分工不同：strength 是调查判断，verification 是外部证据强度。档位表见 groom 的置信度重算规则 |
| `discriminative_power` | quickly_check 能否把这条 case 与同 namespace 的相似 case 区分开，附对比候选 | 防重复沉淀，防低判别力的条目污染候选集 |
| `predicted_value` | 预期命中场景：这条沉淀预计命中哪类未来问题，写成可检验的描述（见第 4 节）。当前是蓝图字段，未进 case schema | 沉淀效果度量的对比基准 |
| `ref_knowledge` | 关联的 active reference，role 必须合法，由 `scripts/verify_references.py` 校验 | 已有机制，沉淀时一并评估 |

这些契约项今天落进 case 文件的只有一部分。`verification` 落 case 的 `verification.source` 与 `verification.detail`，档位定义见 `skills/to-postmortem/SKILL.md:85` 到 `:91`；`ref_knowledge` 落 case 的同名字段（`docs/spec/case-schema.md:21`）；`source_evidence`、`sediment_form`、`evidence_strength`、`discriminative_power` 是沉淀契约要回答的问题项，case 文件里没有同名字段（case 的完整字段清单见 `docs/spec/case-schema.md:11`）。

## 4. 沉淀效果度量：两条通道

### 4.1 两个度量通道

原设计的 `predicted_value`、`first_hit`、`expected_window` 三个字段与随后的观察窗实验都没有落地：字段没有进 case schema，整套设计依赖 S1（工程师回报 fix 结果）现场反馈，而该通道当前的捕获率约为 0。压缩后的做法是用两条现成的通道度量一次沉淀的效果，不再引入中间字段。

| 通道 | 读什么 | 回答的问题 | 数据落点 |
|---|---|---|---|
| 内容正确性 | S2 issue-replay 对照外部 resolution 的结果，加入库时的 `verification` 来源档位 | 这条知识对不对 | `case.validation_record`，由 `scripts/settle_s2_feedback.py` 结算 |
| 现场有效性 | S1 工程师回报 fix 是否解决 | 这条 fix 在用户环境里管不管用 | `case.confidence` |

现场有效（resolve）只认 S1，落 `confidence.hits` 与 `confidence.misdiagnoses`。S2 与 golden 证明的是「内容与外部 ground truth 一致」或「检索命中」，不证明「fix 在现场解决」。两条证据对应不同对象，分别结算，不混算：

- S2 命中且结论与 issue resolution 一致，落 `validation_record.consistent`：内容被外部验证，同等 score 下排序优先；
- S2 命中但样本本身是这条 case 的来源，或这条 case 在正文里引用了该样本，落 `validation_record.self_consistent`：这是非独立命中，同一份证据不能数两次；
- S2 命中但结论不符，落 `validation_record.inconsistent`：这是 case 复审信号，指向内容错、过时或判别力不足；
- 既没被 S2 命中、也没被 S1 确认：做归因，判断是场景没有出现，还是判别力有问题，并标为未验证。

`verification`、`validation_record`、`confidence` 按对象分层，这一分层保留：内容置信不等于现场置信。`verification` 是来源验证（fix PR 已合入等），提高的是内容正确性的先验；`validation_record` 是它的运行期延续，靠持续的外部验证累积；`confidence` 是现场解决率，只由 S1 写入。三者独立：来源为 fix-merged 的 case 初始 score 高，说明内容可信，不等于它在任意客户环境里被验证过；现场确认仍要等 S1 回报。

`predicted_value`、`first_hit`、`expected_window` 三个观察窗跟踪字段都没有落地，标为蓝图（字段没有进 case schema）。等出现第一次真实的沉淀批量，并且 S1 反馈恢复之后，再评估是否需要「预期命中场景对照」这个字段。当前 `validation_record` 与 `confidence` 已经覆盖效果度量的两条通道，这三个字段是预测性设计，触发条件到了才实现（原则十一）。

反馈到源头这条保留。某个 issue 源（如 vllm-ascend 池）的沉淀连续不被验证或从未命中时，调 `scripts/issue_filter.py` 的价值启发式，而不是继续增加沉淀量。这样沉淀质量的考量从 to-postmortem 环节延伸到 issue-ingest 的筛选环节（原则十一：数据回流到假设）。

### 4.2 标注规则

- 只有 S2 佐证、没有 S1 反馈的 case，`validation_record` 标 `source: issue-replay`，与 `confidence` 的 S1 口径分开（见第 6 节）。`consistent` 不等于现场 resolve，报告与指标里不得混称。
- 「从未被验证」不等于「沉淀失败」。若预期场景本身没有出现（该框架版本没有人用），记「场景未出现」，不把预测偏差当成案例错误。

## 5. Follow-up 验证链路：改进项改动后的合理性

### 5.1 状态机：改进项卡（EV 卡）是 agent 的决策档案

权威定义在 [pipeline.md](pipeline.md) 第 7 节，本节只重复关键语义。

关键原则：改进项卡（EV 卡）的终态是 agent 依据 eval 做出的判断，不含「合入」语义。一张卡从执行修改到 eval 检查「改动是否真的解决问题」，都在提 PR 之前做完；agent 依据合入前可得的验证（S2、golden、归因事件复测）判断采纳或是不采纳。即时判定与现场反馈的分界在这里：S2、golden、归因事件复测在合入前完成，现场有效性（S1）只在合入后的观察窗里结算（第 5.1a 节，目前是蓝图，落地前按「标存疑加提醒人」处理）。批提交、提 PR、人审合入属于流程层（会话与批边界）的事，不进卡状态。人审发生在目标态完成或降级完成（目标没做满就收手，例如要沉淀 100 条、实际做出 60 条）时，审视的是整个自演进过程是否站得住，`rejected` 卡同样在审视范围内。

| 变更类型 | 产卡后的状态流转 | 判定依据 | 终态含义 |
|---|---|---|---|
| 即时判定类（检索、路由、skill 流程、脚本） | 产卡即 `in_experiment`（action 加 eval），然后 `validated` 或 `rejected`；发现更好方向时 `superseded` | S2 或 golden，可以即时出结果 | `validated` 是 agent 采纳，改动保留；`rejected` 是 agent 不采纳，结论留在卡上；`superseded` 是被新的改进项卡替代 |
| 真实反馈类（content 沉淀、fix 有效） | 产卡即 `in_experiment`（实现加 S2 佐证），然后 agent 判 `validated` 或 `rejected` | 合入前只能拿到实现与 S2 佐证；现场有效性要等真实场景或 S1 | `validated` 之后现场有效性进入观察窗，由流程层跟踪，不改变卡状态 |

观察窗的结果以追加 `decisions` 的方式写回卡，例如「PR #N 合入」「观察窗 S1 确认现场有效」「现场退化已回滚」。

状态词表与 schema 的唯一事实源在 [pipeline.md](pipeline.md) 第 7 节。EV 卡的 status 词表是 `in_experiment`、`validated`、`rejected`、`superseded`，不含 `candidate` 待办态，也不含 `pending_merge`、`adopted` 这类 git 合入态，产卡即执行。`supersedes` 与 `superseded_by` 构成替换链，`actual_cost` 是成本字段，两处都在那边定义。本文只引用，不重复定义，避免两处状态机再次漂移。

注意区分对象：case 的观察窗跟踪字段与 EV 卡的 status 是两套词表，不混用。第 4 节讲的是 case 的度量通道，本节讲的是 EV 卡的状态。

### 5.1a 观察窗超时降级

这一节的完整机制设计保留，但它是蓝图：[pipeline.md](pipeline.md) §11.1 把它排在「触发后实现」一列，触发条件是 S1 断供真实持续两期以上。在那之前，观察窗到期而没有反馈时，用「标存疑加提醒人」的轻量方式处理，人可以补反馈或回滚。

content 与 fix 两类的观察窗依赖 S1 现场反馈，而反馈可能长期断供（当前捕获率约为 0）。没有超时结算，已采纳改动的现场有效性会一直悬空，follow-up 机制停在等答案上。超时处理按观察窗长度分级：即时类不设超时；content 类按预期观察窗长度的两倍（`expected_window ×2`，该字段尚未落地，见第 4 节的蓝图说明）；fix 类按最长窗的两倍；参数等落地后校准。

到期未结算（没有 S1 反馈）时按对象分列处理：

| 对象 | 情形 | 处理 |
|---|---|---|
| EV 卡（给 `validated` 改动的现场效果结算） | 有 S2 或 golden 的检索命中证据 | 追加 `decisions`「检索有效、现场未确认」（`unconfirmed_valid` 语义），效果按 `source: issue-replay` 入指标，不无限滞留 |
| EV 卡 | 没有任何命中证据 | 追加 `decisions`「观察窗超时无证据」（`unconfirmed` 语义），标为存疑，并触发降权信号（证据不足，进入重审或回滚候选） |
| EV 卡 | 有退化证据（S2 miss 增长） | 追加 `decisions`「现场退化，已回滚改动」（`rolled_back` 语义），不等 S1 |
| 沉淀 case | 持续结算 `validation_record`（`scripts/settle_s2_feedback.py`） | S2 命中一致落 `consistent`；命中不符落 `inconsistent`（复审）；无命中且无 S1 则做归因（场景未出现或判别力问题），标为未验证 |

规则：观察窗不是无限等待，到期必须结算。结算结果作为追加 `decisions` 记到 `validated` 卡上，并写明证据强度（有 S1 记 S1，只有 S2 记检索有效，没有证据记存疑），不改变卡状态：卡状态是 agent 决策的终态，观察窗属于流程层的效果结算。它与轻量提醒的分工是：提醒是提前提示，人还有机会补反馈；超时结算是最终兜底，人不补就标注，不无限等。

观察窗结算为存疑或未确认的改动不悬空，仍可继续参与演进：

- 可以被 supersede。新卡可以在未确认的改动上提出替代：未确认说明原方案缺少现场证据，正是「更好的 idea」适用的场景。supersede 规则见 [run.md](run.md) 第 5 节；
- 可以重新验证。无证据存疑的改动可以开新卡重新设计验证方案，补 S2 证据或改验证设计；
- 积压清理。季度自评统计「观察窗未确认」改动的占比。占比高说明 S1 断供或验证设计存在系统性不足，触发流程改进（例如追问话术与提醒时机，对应 roadmap.md 里的反馈捕获率监测），而不是继续堆积；
- 口径纪律。观察窗未确认、只有 S2 佐证的改动不计入「现场 validated」统计。第 6 节的 validated 计数与回滚率口径都不含未确认项，避免稀释真验证的统计。

### 5.2 观察窗按变更类分

不是所有验证都要等现场反馈。

| 变更类 | 验证数据 | 观察窗 | 判定基准 |
|---|---|---|---|
| 检索与路由（triage、case 的 quickly_check、`knowledge/_index/` 下的读侧视图） | S2 issue-replay 校准集 | 即时，replay 不等现场 | 命中率、路由准确率的改前改后对比 |
| skill 流程（diagnose 与 groom 的步骤、脚本） | S2 加 golden 回放 | 即时到数周 | 组件误诊率、错例复测、golden 无回归 |
| content（新 case 或 reference 沉淀） | 后续真实诊断加 S2 | 数周到数月，等场景出现 | 预期命中场景与实际命中、resolve 的对照（第 4 节） |
| fix 有效类（改 fix 内容、severity） | S1 工程师反馈 | 长，依赖现场回报 | 反馈 resolve；没有回报时停在等待，并做超时结算 |

### 5.3 判定后写回

- 卡：agent 判断后更新 status，并向 `decisions` 追加记录（谁、何时、依据哪份 eval 数据、采纳或不采纳的结论）。观察窗结算同样追加 `decisions`，不改变卡状态。
- 指标：`validated` 时在 `metrics/timeline.yaml` 记一期效果差（改前基线与改后实测的对比）；观察窗结算为「现场退化回滚」时记录并计入回滚率。
- 归因事件：`validated` 后对应归因事件簇减少（组件执行错率回落）；观察窗结算为「退化」时追加归因事件与教训摘要，防同类改进项重复提交。

## 6. Metrics 分层：每个指标回答一个决策问题

指标消费方三问（谁决策、答什么问题、不答会怎样）先行，答不了任何决策问题的指标不采集（roadmap.md 的「指标消费方三问」纪律）。指标分四层，口径互不混淆：

| 层 | 指标 | 回答的决策问题 | 数据源 |
|---|---|---|---|
| 机制健康（流水线自身） | 候选到采纳率、实验到通过率、信号误报率、抽审发现率、回滚率 | 流水线是否在做对的事？信号是否误报？auto 授权是否过宽？ | `proposals/ideas`、decisions、回测记录 |
| 知识质量（库整体） | 命中率、resolve 率（S1）、误诊率、路由准确率、判别力、覆盖缺口 | 知识库整体在变准吗？哪个格子弱？ | `scripts/trace_metrics.py` 加 `scripts/index_counts.py` |
| 单次沉淀效果 | `validation_record`（S2 内容验证一致或不一致）加 `confidence`（S1 resolve） | 每次沉淀是否有效？哪个来源产出低质沉淀？ | `scripts/settle_s2_feedback.py` 加 groom |
| skill 组件质量 | 归因事件簇（按需聚合）、每次 skill 变更前后的差 | 哪个组件反复出错？这次 skill 改动有效吗？ | `scripts/component_tally.py` 聚合加回测 |

口径纪律沿用 `docs/guide/metrics.md`：比例带分母；分母小于 10 时显式标注；`source: live / replay / issue-replay` 必标；无数据时不写。回滚率是新进的指标，衡量合入闸门放错了多少，是授权级别校准（[pipeline.md](pipeline.md) §6.3）与季度自评（[pipeline.md](pipeline.md) §6.6）的输入。

## 7. Agent 决策点的信息供给

当执行与评审交给 agent 时，每个决策点要明确供给什么。第 2、3 节的信息契约不是文档装饰，而是 agent 能正确执行的前提。

| 决策点 | 供给清单 | 缺失后果 |
|---|---|---|
| 执行 skill 优化 | 目标组件的当前全文（SKILL.md 相关节、triage 分支、script）、改前反例的原文（不是摘要）、改动影响面、历史先例（该组件在归因事件与历史卡里被改过吗，结果如何） | 盲改；重复提交已失败的改进项 |
| 执行沉淀评估 | 来源 issue 或 trace 的原文（或充分证据）、同 namespace 现有相似 case 的全文（判重复与判别力）、覆盖矩阵的缺口 | 判不出判别力，重复或低质沉淀入库 |
| 评审（reviewer 角色） | 卡、改前改后的 diff、`predicted_effect` 与验证结果的对照，要求 30 秒内可判定。判定把手是 `python3 scripts/ev_measure.py <card-id> --run`，它打印判据命令、实测输出与退出码 | 评审变成橡皮图章，或被迫打开全文 |
| 季度自评 | 四层指标聚合、跨期对比、回滚案例、抽审发现 | 元层审视没有依据 |

评审把手的判据强度（原则十）：`ev_measure --run` 证明效果，即改动是否产生了它声称的变化；它不证明价值，即这个变化是否值得。命令是否真的在测那件事，机器判不了，这条属于约定强度，靠人审抽查。退出码分三态：`0` 符合预测、`1` 预测被证伪、`2` 无法判定，避免「判不了」被读成「验证失败」。存量卡（`created_at` 早于 `MEASURE_CUTOVER`，该常量在 `scripts/verify_proposals.py:63`，值为 2026-09-11）豁免强制要求：给已完成的决策补一条命令，不恢复当时的判断，只造事后叙述。这类缺口由 `python3 scripts/ev_measure.py --audit` 报出，不静默跳过。多人协作下这条尤其关键：评审者会变多，而完整心智模型只有一个。

分层供给控预算（原则九）：决策点先给卡（聚合值与证据引用），判定前才展开证据原文；只有进入 follow-up 判定的卡才加载完整回测数据。供给的目标是每个决策点给够判定所需的信息；信息不足与信息过载同样损害执行质量。

归因事件的按需聚合与改进项、深度轮报告的历史记录合在一起，构成 agent 判断「这个组件以前怎么改、结果如何」的依据（对应 SkillOpt 的 reject buffer 与 meta-skill 思路；载体是本仓库的词法归因事件加按需聚合，不是模型内的隐状态）。

## 8. 与现有机制的关系

| 本文 | 对接的现有机制 | 关系 |
|---|---|---|
| 改进项契约（第 2、3 节） | pipeline.md 第 7 节的 schema | pipeline.md 定义状态机与最小字段，本文定义执行级完整字段；落地时以本文扩展 |
| 沉淀效果度量（第 4 节） | case 的 `confidence` 与 `validation_record`、groom 的 R 轮次 | `confidence` 语义不变（只认 S1 resolve），`validation_record` 承接 S2 内容验证；groom 跑 `scripts/settle_s2_feedback.py` |
| follow-up 验证（第 5 节） | golden fixture 回放（roadmap.md 里的 fixture replay 半自动化与 fixture 自动生成两行）、S2 校准集、反馈结算 | 观察窗的即时判定依赖 golden 回放与 S2；S1 类依赖 `scripts/settle_trace_feedback.py` |
| metrics 分层（第 6 节） | `metrics/timeline.yaml`、`scripts/trace_metrics.py` | 新指标进 timeline 要通过 `scripts/verify_metrics.py` 的结构校验扩展（按准入三条件评估） |
| agent 供给（第 7 节） | 归因事件加 `scripts/component_tally.py` 的按需聚合（pipeline.md 第 2 节） | 归因事件是历史先例的载体 |

## 9. 原则追溯

| 设计元素 | 服务的原则 | 说明 |
|---|---|---|
| 改进项卡带 baseline、`predicted_effect`、verification | 八、一 | 没有改前基线、预期与验证就无法判定，验证先于交付 |
| `predicted_effect.measure`（预测的出处，可复现） | 二、六、八、九、十一 | 口径机器可判则进 CI 硬门（二、六）；不可度量的改进不被接受（八）；把 reviewer 的注意力从读全文压到跑一条命令（九）；假设换成实测（十一） |
| 卡 schema 的必填字段 | 二 | 不变量写进结构（落地评估 CI 化） |
| follow-up 观察窗加 `validated` 终态 | 一、七 | 合理性在效果确认时判定，不在合入时判定；观察窗内可以回滚 |
| 沉淀当作带预期的实验 | 八、十一 | 每次沉淀可评估；数据回流到 issue 筛选假设 |
| 归因事件作为决策档案 | 八 | 历史先例防重复提交已失败的改进项 |
| 分层供给控预算 | 九 | 每个决策点给够，不追求全量 |
| 脱敏纪律（引用不含原文） | 十 | 信息完整与隐私冲突时降级 |
| 回滚率指标 | 六、十一 | 合入闸门质量可度量，用于校准授权级别 |

## 10. 落地顺序

本表只回答本文所述契约内部先做什么。整体落地总纲见 [pipeline.md](pipeline.md) §11，以那份为准，本表与其不平行。

| 步骤 | 内容 | 入口闸门 |
|---|---|---|
| 1 | 改进项 schema v3 落 `proposals/ideas/` 模板（与 pipeline.md §11.1 的第一批落地同批） | owner 确认（已完成：schema 加 `scripts/verify_proposals.py`） |
| 2 | `validation_record` 结算落地（`scripts/settle_s2_feedback.py` 加 groom 3.5b） | 已完成；真实 S2 result 批量后结算首轮 |
| 3 | follow-up 观察窗常态化 | golden 回放或 S2 校准集可用（即时判定类） |
| 4 | 回滚率、采纳率等机制健康指标进 timeline | 自演进执行流程试点满一轮 |
| 5 | agent 供给清单固化为执行 checklist（将来由 skill 承载） | 步骤 1 到 3 有真实执行记录 |
