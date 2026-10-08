# 交互型 replay 评测（ixn-replay）

> 本文是交互型 replay 评测（ixn-replay）的设计文档，给 diagnose 的交互行为（追问、信息充分性、过早结论）立评测。要改交互面的评测口径，或者要跑一次 ixn replay 时读它；读完能分清检索、内容面与交互面的边界，并解释一次 replay 的结果。论证层，日常不必读；执行规则与机制地图见 [rsi-mechanism.md](rsi-mechanism.md)。
>
> 机制决议是 EV-2026-012。第一阶段落地（本文档与 `scripts/ixn_replay.py` v1）已完成；首次出分见 §8。评分口径经 2026-09 的本地试点验证（N=3：vllm-ascend #2424、#9769、#9798，含 held-out（未沉淀、留作评测）与 self_consistent（自指隔离）两种分流），试点数据与结论写在 §4 与 §7；试点的运行留档是本地运行时件，不入库。评分阈值与筛选标准的校准是蓝图，触发条件见 §8。

## 1. 定位：诊断评测的第三个维度

单发 S2 replay（[pipeline.md](pipeline.md) §2.1）只测检索与内容面：给全量 issue 背景，看系统能否路由、命中、到达正确结论。它测不了 diagnose 的交互面：信息不足时会不会追问、问的是不是决定性字段、会不会过早下结论。交互型 replay（下称 ixn-replay）补的就是这一维：

| 评测 | 测什么 | 输入 | 对照答案 | 关联能力 |
|---|---|---|---|---|
| 单发 S2 | 检索、内容与路由 | issue 全量背景 | issue resolution | 知识库与 triage 的质量 |
| ixn-replay | 交互、追问与信息充分性 | 分期披露：先给一部分，追问后给下一段 | 维护者真实追问与决定性字段，取合理下限而非最优 | diagnose 在信息不足时追问的行为 |
| 归因型 replay（另一个维度，本文不含实现） | 源码归因深度 | 现象或代码片段 | PR/commit 引用 | 源码级定位能力 |

三种评测互不重叠：一条 issue 可以同时作为单发、分期与归因三种评测的输入，各自回答一个能力面。

## 2. 选样：筛选制，不是全池可用

样本库扩到 10 条（跨 vllm-ascend、verl、MindSpeed-LLM 三个仓库）后统计，其中真正需要渐进披露的约 2–3 条（#2424、#9769、#9798 这一类型：body 不全，或关键信息在评论里，维护者向报告者追问过）。多数 issue 属于详尽型（body 完整，只能人为拆段）或归因型（决定性信息来自源码调查，追问没有意义）。选样规则：

1. 渐进披露型优先：body 信息不足，评论里有要版本、环境、日志或复现的追问，且 issue 已 closed 并有 resolution。可以用 GitHub 搜索 `in:comments "What version"` 这类语法定位。
2. 详尽型可以靠人为拆段补入（正文材料足够，试点样本里有一条 issue 的正文有 31KB，够拆成多段），但拆段不能让答案过早自明：`stage-0.md`（第一段，首报内容）里不含决定性内容。
3. 归因型不进入本评测：决定性信息来自源码调查而不是追问，评追问测不出差别。
4. 样本库按这套筛选制入库，由上游 issue 流持续自然补充（复用方案见 §6）。

## 3. 分期构造规则：规格入库，正文与结果留在本地

每个样本分两处存放：

- `eval/ixn-arena/<issue>/`：入库，随 PR 审，可复用不重建。
  - `gold.yaml`：标注文件，字段有：
    - `held_out`：该 issue 是否未沉淀。`true` = 未沉淀，留作评测样本；`false` = 已沉淀，重放命中记 `self_consistent`，只作训练与回归样本，见 §6；
    - `resolution_ref`：上游 fix PR、commit 或 closed 依据；
    - `maintainer_questions`：维护者实际追问过的字段，用作合理下限的对照答案；
    - `decisive_fields`：改变结论走向的字段，例如 #2424 的 CANN 版本与 env 复测、#9769 的分支一致性；
    - `resolution_summary`：处置结论的汇总。
  - `stage-k.md`（k 从 0 起）：分期输入（feed）。`stage-0.md` 是重构后的首报版，只给标题与现象段；后续每段只含该轮真实披露的信息。`stage-0.md` 与后续各段都不含 `decisive_fields` 的答案。
  - `registry.yaml`：样本清单，记 issue 号、URL、`held_out`、`staged`、决定性字段与评分行。
- `.ixn-replay/<issue>/`：留在本地、不进 git，放 `issue.md`、`comments.md`（真实正文，`--prepare` 用 `gh` 按 issue 号拉取）与 `stage-k.result.yaml`、`conclusion.yaml`、`score.yaml`（运行产物）。

新增或修订样本时编辑 `eval/ixn-arena/`，走 methodology PR；真实正文只留在本地，公共仓不包含真实语料全文，这条纪律与 `eval/s2/` 相同。`scripts/ixn_replay.py --score` 读取 `gold` 的权威来源是 `eval/ixn-arena/`，取不到时回退本地。

切段纪律：段间的信息增量必须来自线程或 body 的真实内容，不能伪造用户没有说过而假装给出的信息。

## 4. 评分口径：双层指标加防过早

对每条样本，agent 按诊断协议逐段运行：读 `stage-k.md`，按 diagnose skill 判断路由、信息充分性、是否需要追问、能否下结论，然后写 `stage-k.result.yaml`（含 `questions`、`sufficient`、`premature_conclusion`）；最后一段结束后写 `conclusion.yaml`。

`scripts/ixn_replay.py --score` 计算四个指标：

| 指标 | 定义 | 依据（试点数据） |
|---|---|---|
| 追问召回 | 分子是命中的字段数，分母是 `maintainer_questions ∪ decisive_fields` 里按 `field` 去重后的字段数；命中判定用每个字段自己的 `keywords` 正则匹配全部追问文本，再加人工核验 | #2424 命中 3/3（`maintainer_questions ∪ decisive_fields` 去重后 3 个字段） |
| 决定性字段在链 | `decisive_fields ⊆ ∪questions`，不要求出现在首轮 | 试点教训：只问 CANN 版本会漏掉 #9769 的分支一致性；只看首轮命中会放过问不深的 agent |
| 过早结论 | 任一中间段的 `premature_conclusion` 为真；`--score` 列出这些段的段名，不折算成率 | 对照基线是「读完第一段就直接下结论」，它在这一维必然失分，因此该指标有区分度 |
| 结论一致 | `conclusion.yaml` 与 `resolution_summary` 比较 | 只作参考分：resolution 常常是 workaround、版本要求与后续修复的多阶段结论，不是二元 |

对照答案有两条标注规则，另加一条口径纪律：

1. `maintainer_questions` 是合理下限，不是最优标准；
2. 多报告者线程（#2424 这一类）按集合标注：不同 CANN 版本的根因不同，用字段集合而不是单个答案。

口径纪律：分数进报告时带分母，同 [metrics.md](../guide/metrics.md)。

对照答案的标注校准（EV-2026-016）：

1. `decisive_fields` 必须是能向报告者问到的信息（CANN、环境、版本组合、复现细节）。resolution 一侧的事实（fix PR 号、维护者的源码结论）只进 `resolution_ref`：诊断者不该问用户有没有某个 PR。#3325 曾把这类字段错设成决定性字段，导致评分失真。
2. 每个字段条目下都有 `keywords`（`gold.yaml` 顶层只有 `issue`/`repo`/`held_out`/`resolution_ref`/`resolution_summary`/`maintainer_questions`/`decisive_fields`，字段名与关键词都在列表项里），它要包含别名的写法。agent 的提问措辞与标注词面经常不一致，例如写成 `env=0` 而标注是 `VLLM_ASCEND_ENABLE_TOPK_TOPP_OPTIMIZATION`，或者写成关闭优化。词面太窄会误伤召回，#2424 从 2/3 提到 3/3 就是这一类。评分工具只做机械匹配，因此召回率标注的是关键词口径，不是绝对语义。

## 5. 运行协议（agent 侧）

运行协议与 `scripts/s2_replay.py` 同构：工具只负责数据与评分，每一段的诊断与追问都由 agent 执行（读分期输入、走 diagnose skill、写结果），不自动运行。顺序是：`--prepare` 拉取素材并生成标注模板，人或 agent 补齐标注并切段，agent 逐段运行，`--score` 评分，`--aggregate` 聚合。盲测纪律：执行 agent 不看后续段与标注文件；分段文件天然隔离，标注与分期输入分开存放。

运行时数据归属：评测规格（标注与分期输入）入库 `eval/ixn-arena/`，随 PR 审、可复用不重建。规格入库前曾放在临时检出里，清理 worktree 时整个目录被删除，需要重建；规格入库后重建只缺正文，正文可以按 issue 号用 `gh` 拉取。本地不进 git 的只有真实正文与运行件（`.ixn-replay/`、`.s2-replay/arena/`），它们放在主检出，不放在会随 `git worktree remove` 删除的临时检出里。

## 6. self 与 held-out 分流、验证集复用

- `held_out: false`（已沉淀为 case，例如 #9769）：重放命中即 `self_consistent`，只作训练与回归样本（检索与交互回归），不计为外部验证，与 S2 同一纪律。
- `held_out: true`（未沉淀，例如 #2424）：作评测样本。
- 验证集复用：issue 进入评测集不等于被消耗掉。纪律是该 issue 不再沉淀，并且不把评测反馈送回知识侧，也就是不从评测中学习扰动。允许验证集里的 issue 与现有 case 族冗余：该 issue 反正不再沉淀，冗余入库的代价不大。另外用 case 派生的合成变体（按 seed 重新生成）测表面鲁棒性，前提是 [roadmap.md](../plan/roadmap.md) 第 56 行的 M3（fixture 自动生成）落地。上游 issue 流只作自然扩池。

## 7. 成本（试点实测量级）

- 分期运行一次约为单发的 1.5–2.5 倍 token（约 3–6K/条，含知识库检索）；
- 标注一个样本约 3–8 分钟（用 `gh` 拉线程再勾选字段），可以半自动；
- 样本库达到 3–5 条（含 held-out 与 `self_consistent` 两种分流）即可做第一轮阈值校准；这是校准门槛，与分数进 timeline 的样本门槛是两回事（见 §8）。

## 8. 分级与闸门

| 分级 | 内容 | 何时 |
|---|---|---|
| 已落地 | 本文档、`scripts/ixn_replay.py` v1（`prepare`/`score`/`aggregate`）、标注与分期输入的目录规范、`.gitignore`，以及路线图中交互型 replay 评测这一项 | 已完成 |
| 蓝图 | 评分阈值与筛选标准固化、交互面分数进 timeline | held_out 样本达到 10 条后按实测校准（`held_out` ≥10 是分数进 timeline 趋势的门槛；当前 8 条，首批按 O1 的小样本规则带标注记录，不作趋势基准） |
| 蓝图 | 归因型 replay 工具化（用 PR 引用作标注） | 出现归因评测需求，且样本可追溯到 PR 引用 |
| 蓝图 | 合成变体生成器（case 派生扰动加 seed） | 路线图的 fixture 自动生成事项落地后 |
| 落地中 | 把交互面作为 diagnose 追问行为的闸门回归集：skill 改动前后用同一批分期样本对照（EV-2026-016） | 接线已完成，下一次 diagnose skill 改动时启用（#3325 那一类缺口的补丁已在 EV-2026-016 合入） |

首次出分（规格已入库 `eval/ixn-arena/`，记录见 2026-W37 的 timeline 条目，EV-2026-018）：staged n=10，其中 held_out 8 条、self 与回归 2 条；追问召回 9 条为 100%，1 条为 80%，决定性字段全部在链，零过早结论。条数与分数以 `scripts/ixn_replay.py --aggregate` 的输出为准，不要引用本文的数字。2026-W37 的条目按小样本规则带标注记录，不作趋势基准。

#3325 的追问召回起初为 0%，原因是没有追问最新版本或镜像是否仍能复现，属于 diagnose 交互缺口的信号；补丁（EV-2026-016）合入后重跑为 100%。

held_out 样本数是否达到 10 条，只决定分数何时进 timeline 趋势，不决定评测集能否使用或入库：测试集规格随 PR 入库即可复用，与条数无关。分数进 timeline 的门槛是 held_out 样本达到 10 条且带分母，口径纪律同 [metrics.md](../guide/metrics.md)；分母小于 10 时也可以带小样本标注进本地报告，不进趋势。出分结果作本地报告留档。

## 9. 原则追溯

下表的设计元素对应 [design-principles.md](../spec/design-principles.md) 的条文。

| 元素 | 原则 |
|---|---|
| 三维评测各测一个能力面，对照答案取合理下限 | 十（诚实退化） |
| 追问按链评分并按集合标注 | 八（可观测先于改进，评分度量可判行为） |
| 筛选制选样、蓝图分级、阈值等实测校准 | 十一（数据触发） |
| 工具只做数据与评分，agent 执行协议，人工核验字段 | 五（建议与决定分离） |
| `self_consistent` 不计为外部验证，分数带分母 | 十、三 |
