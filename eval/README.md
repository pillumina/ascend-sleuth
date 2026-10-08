# eval/ —— 变更的量尺

`eval/` 放的是"怎么知道一次改动没把原来能命中的场景改坏"以及"候选改动该不该收"所用的样本、账本与封存规则。

它值得读，是因为知识库的变更有指标反馈（confidence、命中率、误诊率），skill 本身的改动没有——这一层补上那个缺口。范围只覆盖评测样本与门控，不覆盖诊断机制本身。读者是改 skill、改路由、改 case 的人，以及要判"这次改动能不能收"的评审。只跑诊断、不改仓库的人不必读。

## 1 这是什么

`eval/` 是变更的量尺：固定输入加期望输出的样本（夹具）、回放后的观测账本、以及按内容哈希封存的对照集。它回答两个问题——改动前后同一批题上逐题比，原来过的还过不过；候选改动在这批题上是不是真的提升。

## 2 它解决什么问题

诊断质量随使用有数据反馈，skill 与路由的改动没有。没有固定题，改动只能靠"读起来更顺"判断，回归会静默发生。这一层把改动的成败变成可复跑的对照：同一批输入在改动前后各跑一遍，此前通过的条目不能变为失败。

LLM 有非确定性，所以断言的是"top-3 命中"而不是"必须第一"。回放结果会过期——同一条样本可能因为知识库后来补了 case 而从 miss 变 hit，判"现在会不会命中"必须当场重跑，不能沿用账本里的历史记录。

## 3 由哪几块组成

| 目录 / 文件 | 是什么 | 谁在跑 |
|---|---|---|
| [golden/](golden/) | 回归夹具：固定输入（症状、框架、日志片段）+ 期望输出（namespace、case、fix 关键内容）。构造示例与真实投影两类 | 改 skill 前后各跑一遍 replay，见 [docs/guide/eval.md](../docs/guide/eval.md) |
| [s2/](s2/) | S2 校准集：ground truth 是 issue 实际的 resolution（PR 号），由 [s2_calibration.py](../scripts/s2_calibration.py) 生成；`vllm-ascend-cross.yaml` 放 cross-validation 样本 | 检索与内容正确性的校准，见 [docs/mechanism/eval-arena.md](../docs/mechanism/eval-arena.md) |
| [flow/](flow/) | 流程类先验知识的评测池：ground truth 是对应 case 的 root_cause，用来判"加载哪条流程、加载多深" | 池内口径与命令见 [flow/README.md](flow/README.md) |
| [ixn-arena/](ixn-arena/) | 交互型 replay 的样本规格（追问召回、决定性字段是否在链、是否过早结论） | [ixn_replay.py](../scripts/ixn_replay.py)，设计见 [docs/mechanism/ixn-replay.md](../docs/mechanism/ixn-replay.md) |
| [holdout.yaml](holdout.yaml) | 封存对照集：由维护者独占的那部分夹具，按内容哈希钉住 | `python3 scripts/holdout.py --check` / `--list` / `--reseal` |
| [scorecard.yaml](scorecard.yaml) | 回放观测账本（生成物）：上次回放观测到什么、夹具与目标 case 是否变过 | `python3 scripts/eval_scorecard.py --check` / `--list` / `--build` |

已进 CI 的：`holdout-integrity`（`holdout.py --check`，改封存内容即红）、`eval-scorecard`（`eval_scorecard.py --check`，夹具改了不重建账本即红）、`arena-gate-rule`（`eval_arena.py --self-test`）。**CI 不执行 replay**——回放要模型，依赖改动人自觉执行。

## 4 从哪读起

- 第一次改 skill：读 [docs/guide/eval.md](../docs/guide/eval.md)，它给出"改哪里测哪里"的门禁分级、怎么跑、以及对照集封存的规则。
- 要判候选改动该不该收：读 [docs/mechanism/eval-arena.md](../docs/mechanism/eval-arena.md)（元层 eval 台的门控协议与影响账本）。
- 要改交互面：读 [docs/mechanism/ixn-replay.md](../docs/mechanism/ixn-replay.md)。
- 只在流程先验层做事：直接读 [flow/README.md](flow/README.md)。

## 5 不覆盖什么

- 不执行回放：CI 只校验结构与哈希，命中率是否达标靠人跑并附报告。
- 不在 CI 里做强断言：检索与匹配随真实夹具规模变化，等级是"约定"，见 [docs/guide/eval.md](../docs/guide/eval.md) 的门禁分级。
- 不放真实客户数据：公开仓只放构造示例，真实夹具进私有仓，脱敏在入仓前完成。
- 不回传评测反馈到知识侧：被评测的 issue 不再沉淀，避免用评测样本训练自己，见 [docs/mechanism/ixn-replay.md](../docs/mechanism/ixn-replay.md)。
