# 交互型 replay 评测（ixn-replay）

这是交互型 replay 评测（ixn-replay）的设计文档。它测 diagnose 在信息不足时的追问行为：把一条 issue 按轮次分段披露，看 agent 会不会追问、问的是不是决定性字段、会不会在信息不够时就下结论。

要改交互面的评测口径，或要跑一次 ixn-replay 时读本文。读完能分清检索、内容面与交互面的边界，并解释一次 replay 的结果。

范围：含评测集的选样与存放规则、四个评分指标、运行协议、成本量级、现状与闸门。不含归因型 replay 的实现，也不含单发 S2 replay 的口径。

读者与前置：知道单发 S2 replay 是什么，读过 [pipeline.md](pipeline.md) §2.1 与 diagnose skill。本文属论证层，日常诊断不必读；执行规则与机制地图见 [rsi-mechanism.md](rsi-mechanism.md)。

## 1. 解决什么问题与不解决什么

单发 S2 replay（[pipeline.md](pipeline.md) §2.1）只测检索与内容面：给全量 issue 背景，看系统能否路由、命中、到达正确结论。diagnose 的交互面它测不了。那一面要回答三个问题：信息不足时会不会追问、问的是不是决定性字段、会不会过早下结论。ixn-replay 补的就是这一维。

| 评测 | 测什么 | 输入 | 对照答案 | 关联能力 |
|---|---|---|---|---|
| 单发 S2 | 检索、内容与路由 | issue 全量背景 | issue resolution | 知识库与 triage 的质量 |
| ixn-replay | 交互、追问与信息充分性 | 分期披露：先给一部分，追问后给下一段 | 维护者真实追问与决定性字段，取合理下限而非最优 | diagnose 在信息不足时追问的行为 |
| 归因型 replay | 源码归因深度 | 现象或代码片段 | PR/commit 引用 | 源码级定位能力 |

归因型 replay 是另一个维度，本文不含它的实现。

三种评测互不重叠。一条 issue 可以同时作为单发、分期与归因三种评测的输入，各自回答一个能力面。

本文不解决三件事：不评源码归因深度（归因型 replay 的职责）；不评知识库与 triage 的质量（单发 S2 的职责）；不产出评分阈值与筛选标准的固化值（蓝图，触发条件见 §8）。

主要构件：`scripts/ixn_replay.py` 是评测工具，只负责数据与评分；`eval/ixn-arena/<issue>/` 存入库的评测规格（`gold.yaml` 标注、`stage-k.md` 分期输入、`registry.yaml` 样本清单）；`.ixn-replay/<issue>/` 存只在本地的真实正文与运行产物；diagnose skill 是被测的交互策略来源。

## 2. 最小可执行模型

把一条 issue 做成一次评测只需要四样东西：一份分期输入、一个逐段运行的 agent、一份对照答案、一个算分脚本。

- 分期输入：`eval/ixn-arena/<issue>/stage-0.md` 是第一段，只给标题与现象；`stage-1.md`、`stage-2.md` 依次是后续每轮的披露内容。
- 逐段运行：agent 读一段，按 diagnose skill 判断路由、信息充分性、是否要追问、能否下结论，把判断写进 `.ixn-replay/<issue>/stage-k.result.yaml`。
- 对照答案：`eval/ixn-arena/<issue>/gold.yaml`，记维护者问过的字段、决定性字段与上游结论。
- 算分：`scripts/ixn_replay.py --score <issue>` 比对判断与对照答案，输出四个指标。

一条样本的规格是三个文件：

| 文件 | 作用 | 关键字段 |
|---|---|---|
| `gold.yaml` | 对照答案 | `held_out`、`resolution_ref`、`maintainer_questions`、`decisive_fields`、`resolution_summary` |
| `stage-k.md` | 分期输入 | 每段只含该轮真实披露的信息，不含 `decisive_fields` 的答案 |
| `registry.yaml` | 样本清单 | issue 号、URL、`held_out`、`staged`、决定性字段、评分行 |

跑通一轮是五步：

1. `python3 scripts/ixn_replay.py --prepare 2424 --repo vllm-project/vllm-ascend` 拉取素材并生成标注模板。
2. 人或 agent 补齐标注并切段。
3. agent 逐段运行。
4. `python3 scripts/ixn_replay.py --score 2424` 评分。
5. `python3 scripts/ixn_replay.py --aggregate` 聚合。

后面的选样、分流、闸门都是在这个模型上加规则。

## 3. 样本与评测规格：选样、入库、分流

### 3.1 选样：筛选制，不是全池可用

样本库扩到 10 条后统计（跨 vllm-ascend、verl、MindSpeed-LLM 三个仓库），其中真正需要渐进披露的约 2–3 条，即 #2424、#9769、#9798 这一类型：body 不全，或关键信息在评论里，维护者向报告者追问过。多数 issue 属于另外两类：详尽型（body 完整，只能人为拆段）或归因型（决定性信息来自源码调查，追问没有意义）。

选样规则：

1. 渐进披露型优先：body 信息不足，评论里有要版本、环境、日志或复现的追问，且 issue 已 closed 并有 resolution。可以用 GitHub 搜索 `in:comments "What version"` 这类语法定位。
2. 详尽型可以靠人为拆段补入。正文材料要够，试点样本里有一条 issue 的正文有 31 KB（样本正文是本地运行时件，不入库），够拆成多段。拆段不能让答案过早自明：`stage-0.md`（第一段，首报内容）里不含决定性内容。
3. 归因型不进入本评测：决定性信息来自源码调查而不是追问，评追问测不出差别。
4. 样本库按这套筛选制入库，由上游 issue 流持续自然补充（复用方案见 §3.3）。

### 3.2 存放：规格入库，正文与结果留在本地

每个样本分两处存放：

- `eval/ixn-arena/<issue>/`：入库，随 PR 审，可复用不重建。
  - `gold.yaml`：标注文件，字段有：
    - `held_out`：该 issue 是否未沉淀。`true` 表示未沉淀，留作评测样本；`false` 表示已沉淀，重放命中记 `self_consistent`，只作训练与回归样本，见 §3.3。
    - `resolution_ref`：上游 fix PR、commit 或 closed 依据。
    - `maintainer_questions`：维护者实际追问过的字段，用作合理下限的对照答案。
    - `decisive_fields`：改变结论走向的字段，例如 #2424 的 CANN 版本与 env 复测、#9769 的分支一致性。
    - `resolution_summary`：处置结论的汇总。
  - `stage-k.md`（k 从 0 起）：分期输入。`stage-0.md` 是重构后的首报版，只给标题与现象段；后续每段只含该轮真实披露的信息。各段都不含 `decisive_fields` 的答案。
  - `registry.yaml`：样本清单，记 issue 号、URL、`held_out`、`staged`、决定性字段与评分行。
- `.ixn-replay/<issue>/`：留在本地、不进 git。存放真实正文 `issue.md`、`comments.md`（`--prepare` 用 `gh` 按 issue 号拉取），以及运行产物 `stage-k.result.yaml`、`conclusion.yaml`、`score.yaml`。

新增或修订样本时编辑 `eval/ixn-arena/`，走 methodology PR。真实正文只留在本地，公共仓不包含真实语料全文，这条纪律与 `eval/s2/` 相同。`scripts/ixn_replay.py --score` 读 `gold` 的权威来源是 `eval/ixn-arena/`，取不到时回退本地。

切段纪律：段间的信息增量必须来自线程或 body 的真实内容，不能编造报告者没有给过的信息。

### 3.3 `held_out` 与 `self_consistent` 分流、验证集复用

- `held_out: false`（已沉淀为 case，例如 #9769）：重放命中即 `self_consistent`。它只作训练与回归样本（检索与交互回归），不计为外部验证，与 S2 同一纪律。
- `held_out: true`（未沉淀，例如 #2424）：作评测样本。

验证集复用：issue 进入评测集不等于它被用掉。纪律是该 issue 不再沉淀，也不把评测反馈送回知识侧，也就是不从评测中学习扰动。允许验证集里的 issue 与现有 case 族冗余：该 issue 不再沉淀，冗余入库的代价不大。合成变体（用 case 派生，按 seed 重新生成）可以测表面鲁棒性，前提是 [roadmap.md](../plan/roadmap.md) 第 126 行的 fixture 自动生成落地。上游 issue 流只作自然扩池。

## 4. 评分口径：双层指标加防过早

对每条样本，agent 按诊断协议逐段运行。每一步做三件事：读 `stage-k.md`；按 diagnose skill 判断路由、信息充分性、是否需要追问与能否下结论；写 `stage-k.result.yaml`（含 `questions`、`sufficient`、`premature_conclusion`）。最后一段结束后写 `conclusion.yaml`。

`scripts/ixn_replay.py --score` 计算四个指标：

| 指标 | 定义 | 依据（试点数据） |
|---|---|---|
| 追问召回 | 分子是命中的字段数，分母是 `maintainer_questions ∪ decisive_fields` 里按 `field` 去重后的字段数。命中判定用每个字段自己的 `keywords` 正则匹配全部追问文本，再加人工核验 | #2424 命中 3/3（`maintainer_questions ∪ decisive_fields` 去重后 3 个字段） |
| 决定性字段在链 | `decisive_fields ⊆ ∪questions`，不要求出现在首轮 | 试点教训：只问 CANN 版本会漏掉 #9769 的分支一致性；只看首轮命中会放过问不深的 agent |
| 过早结论 | 任一中间段的 `premature_conclusion` 为真。`--score` 列出这些段的段名，不折算成率 | 对照基线是「读完第一段就直接下结论」，它在这一维必然失分，因此该指标有区分度 |
| 结论一致 | `conclusion.yaml` 与 `resolution_summary` 比较 | 只作参考分：resolution 常常是 workaround、版本要求与后续修复的多阶段结论，不是二元 |

对照答案有两条标注规则，另加一条口径纪律：

1. `maintainer_questions` 是合理下限，不是最优标准。
2. 多报告者线程（#2424 这一类）按集合标注：不同 CANN 版本的根因不同，用字段集合而不是单个答案。

口径纪律：分数进报告时带分母，同 [metrics.md](../guide/metrics.md)。

对照答案的标注校准（EV-2026-016）有两条：

1. `decisive_fields` 必须是能向报告者问到的信息（CANN、环境、版本组合、复现细节）。resolution 一侧的事实（fix PR 号、维护者的源码结论）只进 `resolution_ref`：诊断者不该问用户有没有某个 PR。#3325 曾把这类字段错设成决定性字段，导致评分失真。
2. 每个字段条目下都有 `keywords`，它要包含别名的写法。`gold.yaml` 顶层只有 `issue`/`repo`/`held_out`/`resolution_ref`/`resolution_summary`/`maintainer_questions`/`decisive_fields`，字段名与关键词都写在列表项里。agent 的提问措辞与标注词面经常不一致：例如提问写成 `env=0`，标注是 `VLLM_ASCEND_ENABLE_TOPK_TOPP_OPTIMIZATION`；或者提问写成关闭优化。词面太窄会误伤召回，#2424 从 2/3 提到 3/3 就是这一类。评分工具只做机械匹配，所以召回率标注的是关键词口径，不是绝对语义。

## 5. 运行协议（agent 侧）与运行时数据归属

### 5.1 执行顺序

运行协议与 `scripts/s2_replay.py` 同构：工具只负责数据与评分，每一段的诊断与追问都由 agent 执行（读分期输入、走 diagnose skill、写结果），不自动运行。执行顺序：

1. `--prepare` 拉取素材并生成标注模板。
2. 人或 agent 补齐标注并切段。
3. agent 逐段运行。
4. `--score` 评分。
5. `--aggregate` 聚合。

### 5.2 盲测纪律

执行 agent 不看后续段与标注文件。分段文件天然隔离，标注与分期输入分开存放。

### 5.3 运行时数据归属

评测规格（标注与分期输入）入库 `eval/ixn-arena/`，随 PR 审、可复用不重建。规格入库前曾放在临时检出里，清理 worktree 时整个目录被删除，需要重建；规格入库后重建只缺正文，正文可以按 issue 号用 `gh` 拉取。本地不进 git 的只有真实正文与运行件（`.ixn-replay/`、`.s2-replay/arena/`）。它们放在主检出，不放在会随 `git worktree remove` 删除的临时检出里。

## 6. 边界与失败模式

缺素材、缺标注、词面不一致都只让单个样本不可评分，不中断整批；跨样本的风险只有一处——把规格放在临时检出，会连规格一起丢。

| 情形 | 行为 | 细则 |
|---|---|---|
| 拉不到真实正文（网络不可达、`gh` 未登录） | 该样本停在未 staged | `registry.yaml` 记 `staged: false`、评分行「未跑」；其余样本不受影响 |
| `gold.yaml` 缺失或字段不全 | `--score` 先读 `eval/ixn-arena/` 的 `gold`，取不到回退本地 `.ixn-replay/<issue>/` | 两处都没有时该样本不能评分，列进未跑 |
| 规格放在临时检出 | `git worktree remove` 会连同规格一起删除 | 已实际发生一次，需要重建；规矩是规格进 `eval/ixn-arena/`、正文与运行件留本地且放主检出 |
| 提问措辞与标注词面不一致 | 机械匹配误伤召回 | #2424 从 2/3 提到 3/3 是关键词口径修正；3453 的 80% 是维护者字段「安装/编译方式」未字面命中；人工核验兜底 |
| 中间段过早下结论 | 只列段名，不折算成率 | 小样本下率会失真；对照基线是「读完第一段就直接下结论」，它在这一维必然失分，列段名就能区分 |
| `held_out` 样本不足 10 条 | 分数带小样本标注进本地报告，不进趋势 | 门槛口径见 §8 |
| 结论一致的比较 | 只作参考分 | resolution 常是 workaround、版本要求与后续修复的多阶段结论，不是二元 |
| 规格已入库后再次跑同一 issue | 规格复用不重建 | 重跑只重跑逐段运行与评分 |

## 7. 成本（试点实测量级）

- 分期运行一次约为单发的 1.5–2.5 倍 token（约 3–6K/条，含知识库检索）。
- 标注一个样本约 3–8 分钟（用 `gh` 拉线程再勾选字段），可以半自动。
- 样本库达到 3–5 条（含 `held_out` 与 `self_consistent` 两种分流）即可做第一轮阈值校准。这是校准门槛，与分数进 timeline 的样本门槛是两件事，见 §8。

## 8. 现状与闸门

机制决议是 EV-2026-012。第一阶段（本文档与 `scripts/ixn_replay.py` v1）已落地，首次出分见 §8.4。评分口径经 2026-09 的本地试点验证：N=3（vllm-ascend #2424、#9769、#9798），含 `held_out`（未沉淀、留作评测）与 `self_consistent`（自指隔离）两种分流。试点数据与结论写在 §4 与 §7，试点的运行留档是本地运行时件，不入库。评分阈值与筛选标准的校准是蓝图，触发条件见 §8.2。

### 8.1 已落地

| 机制 | 落地形态 | 确认方式 |
|---|---|---|
| 本文档 | `docs/mechanism/ixn-replay.md` 已登记进文档清单 | `grep -n 'ixn-replay.md' docs/_manifest.yaml`（第 94 行） |
| 评测工具 v1 | `scripts/ixn_replay.py`，含 `prepare`/`score`/`aggregate` | `python3 scripts/ixn_replay.py --help`；源码入口 `scripts/ixn_replay.py:62`、`:121`、`:176` |
| 评测规格入库 | `eval/ixn-arena/<issue>/` 的 `gold.yaml`、`stage-k.md` 与 `registry.yaml` | `ls eval/ixn-arena/`；`sed -n '1,4p' eval/ixn-arena/registry.yaml` |
| 运行时件排除 | `.gitignore` 排除 `.ixn-replay/` | `sed -n '80,81p' .gitignore` |
| 路线图条目 | 交互型 replay 评测（roadmap 里该事项的首级 2026-09-04 达成） | `sed -n '143p' docs/plan/roadmap.md` |
| 首批出分记录 | 2026-W37 的 timeline 条目（EV-2026-018） | `sed -n '1,20p' metrics/timeline.d/2026-W37.yaml` |
| 交互面闸门接线 | 交互/追问面改动走 ixn 对口样本（EV-2026-016） | `grep -n 'ixn' docs/guide/eval.md`（第 72–73 行）；触发条件：下一次 diagnose skill 改动时启用 |

### 8.2 蓝图

| 机制 | 触发条件 |
|---|---|
| 评分阈值与筛选标准固化 | `held_out` 样本达到 10 条后按实测校准；规则见 [roadmap.md](../plan/roadmap.md) 第 143 行 |
| 交互面分数进 timeline | `held_out` ≥10 且带分母（当前 8 条，首批按小样本显式标注的规则带标注记录、不作趋势基准） |
| 归因型 replay 工具化（用 PR 引用作标注） | 出现归因评测需求，且样本可追溯到 PR 引用；关系见 §12.2 |
| 合成变体生成器（case 派生扰动加 seed） | [roadmap.md](../plan/roadmap.md) 第 126 行的 fixture 自动生成事项落地后；关系见 §12.3 |

### 8.3 已否决

| 做法 | 否决理由 |
|---|---|
| 全池选样 | 多数 issue 属详尽型或归因型，追问测不出差别，样本进去也不产生信号 |
| 把评测规格放在临时检出 | `git worktree remove` 会连规格一起删除，已实际发生一次、需要重建 |

### 8.4 首次出分与门槛

首次出分（规格已入库 `eval/ixn-arena/`，记录见 2026-W37 的 timeline 条目，EV-2026-018）：staged N=10，其中 `held_out` 8 条、self 与回归 2 条；追问召回 9 条为 100%，1 条为 80%，决定性字段全部在链，零过早结论。条数与分数以 `scripts/ixn_replay.py --aggregate` 的输出为准，不要引用本文的数字。2026-W37 的条目按小样本规则带标注记录，不作趋势基准。

样本 #3325 的追问召回起初为 0%，原因是没有追问最新版本或镜像是否仍能复现，属于 diagnose 交互缺口的信号；补丁（EV-2026-016）合入后重跑为 100%。

`held_out` 样本数是否达到 10 条，只决定分数何时进 timeline 趋势，不决定评测集能否使用或入库：测试集规格随 PR 入库即可复用，与条数无关。分母小于 10 时，分数可以带小样本标注进本地报告，不进趋势；进趋势要求 `held_out` 达到 10 条且带分母，口径纪律同 [metrics.md](../guide/metrics.md)。出分结果作本地报告留档。

## 9. 明确不做（防过度设计）

- 不自动运行诊断与追问：工具只做数据与评分，读分期输入、走 diagnose skill、写结果都由 agent 执行。自动化的代价是把交互策略换成一份脚本，测的就不再是 skill。
- 不把真实正文入库：公共仓只放评测规格，真实语料全文留本地。代价是换机器后要按 issue 号重新拉正文。
- 不新增评分指标：过早结论只列段名、结论一致只作参考分，都不折算成率。指标一多，小样本下每一个都很噪声。
- 不重建已入库的规格：`eval/ixn-arena/` 随 PR 审、可复用，重跑只重跑逐段运行与评分。
- 不提前固化评分阈值与筛选标准：等 `held_out` 达到 10 条、按实测校准。提前定阈值等于用当前的 8 条样本拟合门槛。

## 10. 原则追溯

下表的设计元素对应 [design-principles.md](../spec/design-principles.md) 的条文。

| 元素 | 原则 |
|---|---|
| 三维评测各测一个能力面，对照答案取合理下限 | 十（诚实退化） |
| 追问按链评分并按集合标注 | 八（可观测先于改进，评分度量可判行为） |
| 筛选制选样、蓝图分级、阈值等实测校准 | 十一（数据触发） |
| 工具只做数据与评分，agent 执行协议，人工核验字段 | 五（建议与决定分离） |
| `self_consistent` 不计为外部验证，分数带分母 | 十、三 |

## 11. 代码与文档入口

### 11.1 白话到代码名

| 概念 | 文件或脚本 | 行号 |
|---|---|---|
| 评测工具 | `scripts/ixn_replay.py` | `:62` `cmd_prepare`、`:121` `cmd_score`、`:176` `cmd_aggregate`、`:198` `main` |
| 对照答案与分期输入 | `eval/ixn-arena/<issue>/gold.yaml`、`stage-k.md` | 目录规范见 §3.2 |
| 样本清单 | `eval/ixn-arena/registry.yaml` | `version: 2` |
| 本地正文与运行件 | `.ixn-replay/<issue>/` | 排除规则见 `.gitignore:80-81` |
| 单发 S2 先例 | `scripts/s2_replay.py`、`eval/s2/` | S2 口径见 [pipeline.md](pipeline.md) §2.1 |
| 交互面改动门禁 | `docs/guide/eval.md` | `:72-73` |

### 11.2 相邻文档分工

| 文档 | 管什么 |
|---|---|
| [pipeline.md](pipeline.md) | 三层模型、S2 口径与评分源分级（§2.1） |
| [eval-arena.md](eval-arena.md) | 评测台总览与兄弟台分工 |
| [rsi-mechanism.md](rsi-mechanism.md) | 机制地图与权威归属 |
| [metrics.md](../guide/metrics.md) | 指标定义与闸门口径 |
| [roadmap.md](../plan/roadmap.md) | 交互型 replay 评测的路线状态与门槛规则 |
| [design-principles.md](../spec/design-principles.md) | 原则条文 |

## 12. 外部参考

### 12.1 已落地：与单发 S2 replay 的关系（借鉴什么、不取什么）

- 借鉴：工具只做数据与评分的分工、规格入库而结果留本地的持久化模型、`self_consistent` 不计为外部验证的纪律、分数带分母的口径纪律，都与 `eval/s2/` 一致；运行协议与 `scripts/s2_replay.py` 同构。
- 不取：S2 一次给全量 issue 背景，ixn-replay 分期披露；S2 测检索与内容面，ixn-replay 测交互面。

确认方式：`ls eval/s2/ scripts/s2_replay.py`；S2 口径见 [pipeline.md](pipeline.md) §2.1。

### 12.2 蓝图：与归因型 replay 的关系

归因型 replay 是第三个维度，测源码归因深度，用 PR/commit 引用作标注。它不进本评测的样本池，工具化是蓝图，触发条件是出现归因评测需求且样本可追溯到 PR 引用；不取的理由见 §12.4。

### 12.3 蓝图：与合成变体生成的关系

合成变体用 case 派生、按 seed 重新生成，可以测表面鲁棒性。它等 [roadmap.md](../plan/roadmap.md) 第 126 行的 fixture 自动生成落地后再做；上游 issue 流只作自然扩池。

### 12.4 已否决：不采纳的相邻做法

| 做法 | 否决理由 |
|---|---|
| 把归因型 issue 并入本评测的样本池 | 决定性信息来自源码调查而不是追问，评追问测不出差别 |
| 把评测反馈送回知识侧 | 等于从评测中学习，验证集被自己扰动 |
