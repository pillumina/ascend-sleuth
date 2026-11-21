# docs 怎么读

本文是这套系统全部文档的入口：文档按"你什么时候会用到它"分五层，每篇给一句话说明。

它值得读，是因为分层解决"我现在该读哪篇"——同一个层里的文档结构一致，你不必每篇重新猜结论在哪。范围只覆盖 `docs/` 下的文档与阅读顺序；素材与演示页不在阅读顺序里。读者是第一次读这套文档、或要改机制的人。第一次接触先读 [demo-walkthrough.md](demo-walkthrough.md)；只想跑一次诊断、不改机制的人，看完演示就可以去用，不必读本文其余部分。

## 1 这是什么

`docs/` 是这套系统的文档层，按"什么时候读"分五层：规范、演进机制、操作指南、计划与就绪度、决策留痕。目录名就是层次名，路径里就能看出这篇是给谁的。

## 2 它解决什么问题

同一层的两篇文档如果结构不一致，读者每读一篇都要重新判断哪一节才是结论。分层回答"我现在该读哪篇"；每层内统一的骨架回答"这篇的结论在哪"。某件事由哪篇文档说了算，查 [mechanism/rsi-mechanism.md](mechanism/rsi-mechanism.md) §11.2 的权威归属表——那张表也说明每篇什么时候该读。

## 3 由哪几块组成

| 目录 | 这一层是给谁的 | 什么时候读 |
|---|---|---|
| `spec/` | 要改设计或实现的人 | 判断某个改动是否合规之前 |
| `mechanism/` | 要改机制本身的人、以及要看全景的人 | 改演进、评测、编排机制时。**先读 `mechanism/rsi-mechanism.md`**，那是这一层的入口 |
| `guide/` | 要动手操作的人 | 装环境、跑评测、看指标、走 git 门控、做导入时 |
| `plan/` | 要排下一步工作的人 | 决定接下来做什么，或评估能不能推广给一个团队时 |
| `adr/` | 要推翻某个既有选择的人 | 先看它当初的论证与重评条件 |

`assets/`、`diagrams/`、`demo-assets/`、`kb-explorer/` 是素材与演示页，不是阅读顺序里的文档。

## 4 从哪读起

第一次接触：读 [demo-walkthrough.md](demo-walkthrough.md)。两分钟看完系统在做什么、数据怎么流动，不需要动手。

完整的文档目录与每篇的一句话说明由 `docs/_manifest.yaml` 生成在这里（`scripts/build_docs_index.py`）：

<!-- BEGIN generated: docs-index (scripts/build_docs_index.py；由 docs/_manifest.yaml 生成，勿手改) -->
**入门（第一次接触先读这篇）**
*你还不清楚这套系统在做什么、数据怎么流动*

- `docs/README.md` — docs 怎么读：分层表（每一层给谁、什么时候读）+ 入口指路
- [demo-walkthrough.md](../docs/demo-walkthrough.md) — 从一次诊断到知识演化的可读演示：两分钟架构总览 + 术语与 skill 速览 + 全流程示例（不需要动手）

**规范（约束一切设计与演进；改机制前必读）**
*你要判断某个设计/改动是否合规，或要挑战一条既有规则时*

- [case-schema.md](../docs/spec/case-schema.md) — case 的字段定义、口径，以及哪些内容不允许进库
- [design-principles.md](../docs/spec/design-principles.md) — 十一条规范性条文——一切设计、实现、修复与演进的依据
- [design-theory.md](../docs/spec/design-theory.md) — 四公理 → 公式 → 原则的完整推导链（原则的生成处）
- [writing-norms.md](../docs/spec/writing-norms.md) — 人读/审阅文本的行文规范（词句层：口径以本文件为准）：共用条目、必须保留的原值、各面的共用与定制判定、哪些能硬化；篇章结构口径见 skills/doc-standards/
- [test-portability.md](../docs/spec/test-portability.md) — 测试在 Windows/Linux/macOS 上同一结论的判定口径（编码、路径、字节夹具、平台 API、外网用例），以及哪几条已进 CI、哪几条只能人审
- [terminology.md](../docs/spec/terminology.md) — 内部行话、易混词与禁用词：禁用词改写、五个英文词的一译一义、六个多义词按语境改；业界通用词不进表

**演进机制（改机制本身才读；日常不必读）**
*你要改演进/评测/编排机制本身时——日常只读 docs/mechanism/rsi-mechanism.md 一篇，论证层在 docs/mechanism/*

- [evolution.md](../docs/evolution.md) — 旧链接入口（保留以免旧链接失效）：内容已并入 mechanism/rsi-mechanism.md，本文只是一页指路，不要在此续写
- [evolution-config.md](../docs/mechanism/evolution-config.md) — 自演进配置的唯一入口：sleuth.config.yaml 的角色、policy、profile、store、sync、pipeline 组合与信号/RSI/EV 边界
- [rsi-acceptance.md](../docs/mechanism/rsi-acceptance.md) — RSI 真实数据验收记录：样本、候选、A/B gate、full flow、store 缺口与插件验证结论
- [rsi-mechanism.md](../docs/mechanism/rsi-mechanism.md) — 机制技术入口：目标、三条环路、一轮演进、角色、人工介入等级、八篇文档地图
- [evaluation.md](../docs/mechanism/evaluation.md) — 评估对象与评估集、rubric、配对判定、成本、版本，以及评估台（arena）的池与结论
- [records.md](../docs/mechanism/records.md) — 记录与数据契约：改进项卡 schema、样本、执行、结论、接口、存储归属、版本坐标
- [operations.md](../docs/mechanism/operations.md) — 运行节奏：触发入口、运行模式与授权、停止条件、每周流程、采样、内容维护、长期任务
- [ixn-replay.md](../docs/mechanism/ixn-replay.md) — 交互面评测（延后项）：追问、信息充分性、过早结论的样本、评分与门槛
- [diagnosis-observability.md](../docs/mechanism/diagnosis-observability.md) — 一次诊断记什么字段、怎么汇总上仓、与知识库的解耦、反馈联动、指标清单与面板；取舍在 ADR-0011
- [status.md](../docs/mechanism/status.md) — 机制状态总表、未建与空转、代码与文件入口对照、相邻文档分工（全库唯一一份）
- [agent-groom.md](../docs/mechanism/agent-groom.md) — Agent Groom 的知识快照、有界语义比对、证据绑定、合入前复核与收尾撤销

**操作指南（用到那个环节时才读）**
*你要搭新部署、装环境（Windows skills 使能）、跑评测、看指标、走 git 门控、或做导入时*

- [evolution-user-guide.md](../docs/guide/evolution-user-guide.md) — 使用者侧：能说什么、一句话后发生什么、怎么读进度
- [eval.md](../docs/guide/eval.md) — 改 skill 前后跑什么（门禁分级）、对照集封存与已冻结的判据
- [metrics.md](../docs/guide/metrics.md) — 指标口径与周批流程（数字以 metrics/timeline.yaml 为准）
- [git-workflow.md](../docs/guide/git-workflow.md) — 审核、门控、合入与多人协作的落地（含评审把手）
- [knowledge-acquisition.md](../docs/guide/knowledge-acquisition.md) — 知识获取的三种起步形态、稀疏拉取白名单，以及部署形态与目录归属的入口
- [issue-ingest-pipeline.md](../docs/guide/issue-ingest-pipeline.md) — issue → case 的半自动导入管道
- [reference-ingest-pipeline.md](../docs/guide/reference-ingest-pipeline.md) — 文档仓 → reference 的导入管道（状态文件、成本结构、已知坑）
- [windows-setup.md](../docs/guide/windows-setup.md) — Windows 下让 agent 发现 skills：三种状态的判别与两条修法
- [handoff.md](../docs/guide/handoff.md) — 把一单诊断交到另一台机器继续（交接包的布局、交接单字段、两条命令的契约与强度边界）

**计划与就绪度（想知道"下一步做什么"时读）**
*你要排下一步工作，或评估能不能推广给一个团队时*

- [roadmap.md](../docs/plan/roadmap.md) — 闸门驱动的演进计划（每个事项的入口条件与验收标准）
- [rollout-assessment.md](../docs/plan/rollout-assessment.md) — 对照原则的四层就绪度评估与推广动作清单

**决策留痕（查"当初为什么这样选"时读）**
*你想推翻某个既有选择，需要先看它当时的论证与重评条件*

- `docs/adr/` — 架构决策记录（软版本匹配 / 不引入 RAG / 容量治理 / 先验知识层等）
  - [0001](../docs/adr/0001-soft-version-matching.md)、[0002](../docs/adr/0002-retrieval-no-rag-lightweight-index.md)、[0003](../docs/adr/0003-platform-portability.md)、[0004](../docs/adr/0004-capacity-governance.md)、[0005](../docs/adr/0005-knowledge-consumption-split.md)、[0006](../docs/adr/0006-knowledge-ingest-dedup.md)、[0008](../docs/adr/0008-prior-knowledge-framework.md)、[0009](../docs/adr/0009-counterfactual-replay-exploration-policy.md)、[0011](../docs/adr/0011-diagnosis-observability-data-plane.md)、[0012](../docs/adr/0012-generated-views-main-owned.md)
<!-- END generated: docs-index -->

## 5 不覆盖什么

- 知识库内容本身（`knowledge/`、`references/`、`postmortems/`）：那是 case 与先验词条，不是 `docs/` 下的文档，入口见各层自己的说明。
- 素材与演示页（`assets/`、`diagrams/`、`demo-assets/`、`kb-explorer/`）：不在阅读顺序里，见各目录自己的 README。
- 脚本与校验器的实现细节：看脚本本身；每层的「代码与文档入口」节给指针。
