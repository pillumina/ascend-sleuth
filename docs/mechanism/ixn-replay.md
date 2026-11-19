# 交互回放评测（延后项）

交互回放是 issue 回放（单发）之外的另一个能力面：它测 diagnose 在信息不足时的追问行为。把一条 issue 按轮次分段披露，看 agent 会不会追问、问的是不是决定性字段、会不会在信息不够时就下结论。

**现状：延后。** 工具与评测规格已入库，首批已出分；评分阈值、筛选标准的固定值与分数进趋势都等 `held_out` 样本达到门槛条数后再定。日常诊断与其他评测不受影响。读者是要改交互面评测规则、或要跑一次交互回放的人；前置是 [evaluation.md](evaluation.md) 3.7 与 `skills/diagnose/SKILL.md`。

范围：选样、存放、分流、四项指标、运行协议、成本与门槛。不含归因型 replay 的实现，也不含 issue 回放（单发）的规则。

## 1 解决什么问题与不解决什么

issue 回放（单发）只测检索与内容面：给全量 issue 背景，看系统能否路由、命中、到达正确结论。diagnose 的交互面它测不了。那一面要回答三个问题：信息不足时会不会追问、问的是不是决定性字段、会不会过早下结论。

| 评测 | 测什么 | 输入 | 对照答案 | 关联能力 |
|---|---|---|---|---|
| issue 回放（单发） | 检索、内容与路由 | issue 全量背景 | issue resolution | 知识库与 triage 的质量 |
| 交互回放（`ixn-replay`） | 交互、追问与信息充分性 | 分期披露：先给一部分，追问后给下一段 | 维护者真实追问与决定性字段，取合理下限而非最优 | diagnose 在信息不足时追问的行为 |
| 归因型 replay | 源码归因深度 | 现象或代码片段 | PR 或 commit 引用 | 源码级定位能力 |

三种评测互不重叠。一条 issue 可以同时作为单发、分期与归因三种评测的输入，各自回答一个能力面。本文不解决三件事：不评源码归因深度（归因型 replay 的职责）；不评知识库与 triage 的质量（issue 回放单发的职责）；不产出评分阈值与筛选标准的固定值（延后，条件见 3.6）。

主要构件：`scripts/ixn_replay.py` 负责数据与评分；`eval/ixn-arena/<issue>/` 存入库的评测规格（`gold.yaml` 标注、`stage-k.md` 分期输入、`registry.yaml` 样本清单）；`.ixn-replay/<issue>/` 存只在本地的真实正文与运行产物；diagnose skill 是被测的交互策略来源。

## 2 最小可执行模型

把一条 issue 做成一次评测只需要四样东西：一份分期输入、一个逐段运行的 agent、一份对照答案、一个算分脚本。

- 分期输入：`eval/ixn-arena/<issue>/stage-0.md` 是第一段，只给标题与现象；后续每段依次披露该轮真实信息。
- 逐段运行：agent 读一段，按 diagnose skill 判断路由、信息充分性、是否要追问、能否下结论，把判断写进 `.ixn-replay/<issue>/stage-k.result.yaml`。
- 对照答案：`eval/ixn-arena/<issue>/gold.yaml`，记维护者问过的字段、决定性字段与上游结论。
- 算分：`scripts/ixn_replay.py --score <issue>` 比对判断与对照答案，输出四个指标。

一条样本的规格是三个文件：

| 文件 | 作用 | 关键字段 |
|---|---|---|
| `gold.yaml` | 对照答案 | `held_out`、`resolution_ref`、`maintainer_questions`、`decisive_fields`、`resolution_summary` |
| `stage-k.md` | 分期输入 | 每段只含该轮真实披露的信息，不含 `decisive_fields` 的答案 |
| `registry.yaml` | 样本清单 | issue 号、URL、`held_out`、`staged`、决定性字段、评分行 |

跑通一轮是五步：`--prepare` 拉取素材并生成标注模板；人或 agent 补齐标注并切段；agent 逐段运行；`--score` 评分；`--aggregate` 聚合。

## 3 完整机制

### 3.1 选样：筛选制，不是全池可用

样本库扩到 10 条后统计（跨 vllm-ascend、verl、MindSpeed-LLM 三个仓库），其中真正需要渐进披露的约 2–3 条：body 不全，或关键信息在评论里，维护者向报告者追问过。多数 issue 属于另外两类：详尽型（body 完整，只能人为拆段）或归因型（决定性信息来自源码调查，追问没有意义）。

选样规则：

1. 渐进披露型优先：body 信息不足，评论里有要版本、环境、日志或复现的追问，且 issue 已关闭并有 resolution。可以用 GitHub 搜索 `in:comments "What version"` 这类语法定位。
2. 详尽型可以靠人为拆段补入：正文材料要够，且第一段里不含决定性内容，不能让答案过早自明。
3. 归因型不进入本评测：决定性信息来自源码调查而不是追问，评追问测不出差别。
4. 样本库按这套筛选制入库，由上游 issue 流持续自然补充。

### 3.2 存放：规格入库，正文与结果留在本地

每个样本分两处存放：

- `eval/ixn-arena/<issue>/`：入库，随 PR 审，可复用不重建。`gold.yaml` 记 `held_out`、`resolution_ref`、`maintainer_questions`、`decisive_fields`、`resolution_summary`；`stage-k.md` 是分期输入，各段都不含决定性字段的答案；`registry.yaml` 是样本清单。
- `.ixn-replay/<issue>/`：留在本地、不进 git，存放真实正文（`--prepare` 用 `gh` 按 issue 号拉取）与运行产物。

新增或修订样本时编辑 `eval/ixn-arena/`，走方法论 PR。真实正文只留在本地，公共仓不包含真实语料全文，这条纪律与 `eval/s2/` 相同。`--score` 读 `gold` 的权威来源是 `eval/ixn-arena/`，取不到时回退本地。切段纪律：段间的信息增量必须来自线程或 body 的真实内容，不能编造报告者没有给过的信息。

### 3.3 `held_out` 与 `self_consistent` 分流

- `held_out: false`（已沉淀为 case）：重放命中即 `self_consistent`。它只作训练与回归样本，不计为外部验证，与 issue 回放同一纪律。
- `held_out: true`（未沉淀）：作评测样本。

验证集复用：issue 进入评测集不等于它被用掉。纪律是该 issue 不再沉淀，也不把评测反馈送回知识侧；允许它与现有 case 族冗余，因为该 issue 不再沉淀，代价不大。合成变体（用 case 派生、按 seed 重新生成）可以测表面鲁棒性，前提是 [roadmap.md](../plan/roadmap.md) 的 fixture 自动生成落地。

### 3.4 评分：双层指标加防过早

对每条样本，agent 按诊断协议逐段运行。每一步做三件事：读 `stage-k.md`；按 diagnose skill 判断路由、信息充分性、是否需要追问、能否下结论；写 `stage-k.result.yaml`（含 `questions`、`sufficient`、`premature_conclusion`）。最后一段结束后写 `conclusion.yaml`。

`--score` 计算四个指标：

| 指标 | 定义 | 依据（试点数据） |
|---|---|---|
| 追问召回 | 分子是命中的字段数，分母是 `maintainer_questions ∪ decisive_fields` 里按字段去重后的字段数。命中判定用每个字段自己的 `keywords` 正则匹配全部追问文本，再加人工核验 | #2424 命中 3/3 |
| 决定性字段在链 | `decisive_fields ⊆ ∪questions`，不要求出现在首轮 | 只问 CANN 版本会漏掉 #9769 的分支一致性 |
| 过早结论 | 任一中间段的 `premature_conclusion` 为真。`--score` 列出这些段的段名，不折算成率 | 对照基线是「读完第一段就直接下结论」，它在这一维必然失分 |
| 结论一致 | `conclusion.yaml` 与 `resolution_summary` 比较 | 只作参考分：resolution 常是 workaround、版本要求与后续修复的多阶段结论 |

对照答案有两条标注规则，另加一条统计纪律：`maintainer_questions` 是合理下限，不是最优标准；多报告者线程按集合标注（不同 CANN 版本的根因不同）；分数进报告时带分母。

标注校准有两条：`decisive_fields` 必须是能向报告者问到的信息，resolution 一侧的事实（fix PR 号、维护者的源码结论）只进 `resolution_ref`；每个字段的 `keywords` 要包含别名写法，评分工具只做机械匹配，所以召回率标注的是关键词规则，不是绝对语义。提问写成 `env=0`、标注是 `VLLM_ASCEND_ENABLE_TOPK_TOPP_OPTIMIZATION` 这类词面不一致会误伤召回，人工核验是降级路径。

### 3.5 运行协议与运行时数据归属

运行协议与 `scripts/s2_replay.py` 同构：工具只负责数据与评分，每一段的诊断与追问都由 agent 执行（读分期输入、走 diagnose skill、写结果），不自动运行。执行顺序：`--prepare`；人或 agent 补齐标注并切段；agent 逐段运行；`--score`；`--aggregate`。

盲测纪律：执行 agent 不看后续段与标注文件。分段文件天然隔离，标注与分期输入分开存放。

评测规格入库 `eval/ixn-arena/`，随 PR 审、可复用不重建。规格曾放在临时检出里，清理 worktree 时整个目录被删除、需要重建；规格入库后重建只缺正文，正文可以按 issue 号用 `gh` 拉取。本地不进 git 的只有真实正文与运行件（`.ixn-replay/`、`.s2-replay/arena/`），它们放在主检出，不放在会随 `git worktree remove` 删除的临时检出里。

### 3.6 成本与门槛

- 分期运行一次约为单发的 1.5–2.5 倍 token（约 3–6K 一条，含知识库检索）。
- 标注一个样本约 3–8 分钟（用 `gh` 拉线程再勾选字段），可以半自动。
- 样本库达到 3–5 条（含 `held_out` 与 `self_consistent` 两种分流）即可做第一轮阈值校准。这是校准门槛，与分数进趋势的样本门槛是两件事。

`held_out` 样本数是否达到 10 条，只决定分数何时进 `metrics/timeline.d/` 的趋势，不决定评测集能否使用或入库：测试集规格随 PR 入库即可复用，与条数无关。分母小于 10 时，分数可以带小样本标注进本地报告，不进趋势；进趋势要求 `held_out` 达到 10 条且带分母。出分结果作本地报告留档。

## 4 边界与失败模式

缺素材、缺标注、词面不一致都只让单个样本不可评分，不中断整批；跨样本的风险只有一处——把规格放在临时检出，会连规格一起丢。

| 情形 | 行为 | 细则 |
|---|---|---|
| 拉不到真实正文（网络不可达、`gh` 未登录） | 该样本停在未 staged | `registry.yaml` 记 `staged: false`、评分行「未跑」；其余样本不受影响 |
| `gold.yaml` 缺失或字段不全 | `--score` 先读 `eval/ixn-arena/` 的 `gold`，取不到回退本地 | 两处都没有时该样本不能评分，列进未跑 |
| 规格放在临时检出 | `git worktree remove` 会连同规格一起删除 | 已实际发生一次，需要重建；规矩是规格进 `eval/ixn-arena/`、正文与运行件留本地且放主检出 |
| 提问措辞与标注词面不一致 | 机械匹配误伤召回 | 关键词规则修正；人工核验是降级路径 |
| 中间段过早下结论 | 只列段名，不折算成率 | 小样本下率会失真；对照基线在这一维必然失分，列段名就能区分 |
| `held_out` 样本不足 10 条 | 分数带小样本标注进本地报告，不进趋势 | 3.6 |
| 结论一致的比较 | 只作参考分 | resolution 常是多阶段结论，不是二元 |
| 规格已入库后再次跑同一 issue | 规格复用不重建 | 重跑只重跑逐段运行与评分 |

## 5 现状

### 5.1 已落地

- 评测工具 v1：`scripts/ixn_replay.py`（`prepare`、`score`、`aggregate`）。
- 评测规格入库：`eval/ixn-arena/`。
- 运行时件排除：`.gitignore` 的 `.ixn-replay/`。
- 路线图条目与交互面验收接线：`docs/plan/roadmap.md`、`docs/guide/eval.md` 的交互面对口样本一节。
- 首批出分：`staged` 10 条，其中 `held_out` 8 条、self 与回归 2 条；追问召回 9 条为 100%、1 条为 80%，决定性字段全部在链，零过早结论。条数与分数以 `python3 scripts/ixn_replay.py --aggregate` 的输出为准，不要引用本文的数字。

### 5.2 蓝图

- 交互型 replay 判定池的 expected 标注与基线；评分阈值与筛选标准的固定值在 `held_out` 达到门槛条数后按实测校准。
- 交互面分数进 timeline：`held_out` 达到 10 条且带分母。
- 归因型 replay 工具化（用 PR 引用作标注）与合成变体生成器（case 派生扰动加 seed）：前者等归因评测需求，后者等 roadmap 的 fixture 自动生成落地。

### 5.3 已否决

- 全池选样：多数 issue 属详尽型或归因型，追问测不出差别并产生不了信号。
- 把评测规格放在临时检出（`git worktree remove` 会连规格一起删除，已实际发生一次）或把真实正文入库。
- 把归因型 issue 并入样本池、或把评测反馈送回知识侧：前者决定性信息来自源码调查，后者等于从评测中学习。
- 自动运行诊断与追问：工具只做数据与评分，自动化会把交互策略换成脚本，测的就不再是 skill。
- 新增评分指标：过早结论只列段名、结论一致只作参考分，都不折算成率；小样本下指标一多每一个都噪声。
- 重建已入库的规格，或提前固定评分阈值与筛选标准：前者随 PR 审、可复用；后者等 `held_out` 达到 10 条按实测校准。

## 6 代码与文档入口

| 用途 | 入口 |
|---|---|
| 评测工具 | `scripts/ixn_replay.py`（`cmd_prepare`、`cmd_score`、`cmd_aggregate`） |
| 对照答案与分期输入 | `eval/ixn-arena/<issue>/gold.yaml`、`stage-k.md` |
| 样本清单 | `eval/ixn-arena/registry.yaml` |
| 本地正文与运行件 | `.ixn-replay/<issue>/` |
| 运行件排除规则 | `.gitignore` 的 `.ixn-replay/` |
| 交互面改动检查 | [eval.md](../guide/eval.md) 的交互面对口样本一节 |
| 路线图与门槛 | [roadmap.md](../plan/roadmap.md) |
| 状态与全库入口 | [status.md](status.md) |

## 7 外部参考

本节讲本评测与三种相邻做法的关系，不重复机制状态（在 [status.md](status.md)）。

- **与 issue 回放（单发）**：借鉴「工具只做数据与评分」的分工、规格入库而结果留本地的持久化模型、`self_consistent` 不计为外部验证的纪律、分数带分母的统计纪律，都与 `eval/s2/` 一致；运行协议同构。不取：issue 回放一次给全量背景，交互回放分期披露；issue 回放测检索与内容面，交互回放测交互面。
- **与归因型 replay**：归因型是第三个维度，测源码归因深度，用 PR 或 commit 引用作标注。它不进本评测的样本池，工具化是延后项；不取的理由是决定性信息来自源码调查而不是追问。
- **与合成变体生成**：合成变体用 case 派生、按 seed 重新生成，可以测表面鲁棒性；它等 fixture 自动生成落地后再做，上游 issue 流只作自然扩池。
