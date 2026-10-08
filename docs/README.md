# docs 怎么读

第一次接触这套系统，读 [demo-walkthrough.md](demo-walkthrough.md)。两分钟看完系统在做什么、数据怎么流动，不需要动手。

其余文档按"你什么时候会用到它"分五层。**目录名就是层次名**，所以你在路径里就能看出这篇是给谁的。

| 目录 | 这一层是给谁的 | 什么时候读 |
|---|---|---|
| `spec/` | 要改设计或实现的人 | 判断某个改动是否合规之前 |
| `mechanism/` | 要改机制本身的人、以及要看全景的人 | 改演进、评测、编排机制时。**先读 `mechanism/rsi-mechanism.md`**，那是这一层的入口 |
| `guide/` | 要动手操作的人 | 装环境、跑评测、看指标、走 git 门控、做导入时 |
| `plan/` | 要排下一步工作的人 | 决定接下来做什么，或评估能不能推广给一个团队时 |
| `adr/` | 要推翻某个既有选择的人 | 先看它当初的论证与重评条件 |

`assets/`、`diagrams/`、`demo-assets/`、`kb-explorer/` 是素材与演示页，不是阅读顺序里的文档。

**一件想找的事只有一个权威处。** 按"你要做什么"查 [mechanism/rsi-mechanism.md](mechanism/rsi-mechanism.md) §11.2 的权威归属表，那张表也说明每篇文档什么时候该读。

## 文档目录

完整的文档目录与每篇的一句话说明由 `docs/_manifest.yaml` 生成在这里（`scripts/build_docs_index.py`）。

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

**演进机制（改机制本身才读；日常不必读）**
*你要改演进/评测/编排机制本身时——日常只读 docs/mechanism/rsi-mechanism.md 一篇，论证层在 docs/mechanism/*

- [evolution.md](../docs/evolution.md) — 旧链接入口（保留以免旧链接失效）：内容已并入 mechanism/rsi-mechanism.md，本文只是一页指路，不要在此续写
- [rsi-mechanism.md](../docs/mechanism/rsi-mechanism.md) — 机制技术说明（这一层的入口）：三环主线、什么时候触发、验证怎么闭环、哪一步需要人、每周做什么
- [pipeline.md](../docs/mechanism/pipeline.md) — 三层闭环（知识 / 流程 / 编排）与 proposal 状态机、卡 schema
- [execution.md](../docs/mechanism/execution.md) — proposal 信息契约、评审判据、follow-up 验证、指标分层
- [orchestration.md](../docs/mechanism/orchestration.md) — 自演进会话协议、目标函数与停止条件、token 预算
- [run.md](../docs/mechanism/run.md) — 长期运行、issue 三重角色、统一执行记录、可视化
- [eval-arena.md](../docs/mechanism/eval-arena.md) — 元层 eval 台（train/val 门控）与影响账本
- [ixn-replay.md](../docs/mechanism/ixn-replay.md) — 交互面评测（追问 / 信息充分性 / 过早结论）

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
  - [0001](../docs/adr/0001-soft-version-matching.md)、[0002](../docs/adr/0002-retrieval-no-rag-lightweight-index.md)、[0003](../docs/adr/0003-platform-portability.md)、[0004](../docs/adr/0004-capacity-governance.md)、[0005](../docs/adr/0005-knowledge-consumption-split.md)、[0006](../docs/adr/0006-knowledge-ingest-dedup.md)、[0008](../docs/adr/0008-prior-knowledge-framework.md)、[0009](../docs/adr/0009-counterfactual-replay-exploration-policy.md)
<!-- END generated: docs-index -->
