# 知识获取：三种起步形态

本文是搭出可用的知识仓结构的操作指南：三种起步形态、稀疏拉取白名单、部署形态与目录归属。读者是要新起一个部署、或把知识面收窄的人。只想在本仓里跑一次诊断的人不必读。

## 1 做完得到什么

你得到一个可用的知识仓结构：诊断能读 `knowledge/`、`references/` 与 `triage-tree.yaml`，沉淀能写 `postmortems/inbox/`、`references/` 与 `ingest-state.json`，读写都发生在同一个 clone 里。三种起步形态都通向这个状态，区别只在知识面的宽窄。

## 2 前置条件

- 仓库即 workspace。SKILL 里的知识路径相对仓根，所以三种形态都要先有知识仓结构。
- `npx skills add -s <skill>` 只装 skill，不构成可用形态：SKILL 的知识路径（`postmortems/inbox/`、`references/`、`ingest-state.json`）相对仓根，没有知识仓结构的裸 skill 无法沉淀。它适合在已有仓库里临时试用诊断方法论（不沉淀回本仓），或把 `skills/` 合并进自己已有结构的仓库。`-g` 与 `-s` 的确切行为以 `npx skills add --help` 为准：不同版本的安装器对「仓库整体还是指定 skill」的粒度有差异。

### 部署形态与目录归属

集中式与框架式 fork 两种形态的差别，以及每条路径归谁写（同步时冲突按哪条规则处理），见 [git-workflow.md](git-workflow.md) 的「部署形态」与「目录归属」两节。两种形态下 inbox、groom、索引与 CI 机制的工作方式相同。

## 3 步骤

1. 按下面三种形态选一种，clone 或 fork 本仓。三种形态共用同一套 skill 与机制，可以递进：自积累的团队脱敏后可选回馈上游，补充上游的公开库。

### 三种起步形态

| 形态 | 起步方式 | 结果 | 适合谁 |
|---|---|---|---|
| 自积累（空仓起步） | clone 本仓（或 fork）后清空 `knowledge/` | 结构完整（`skills/` + 空 `knowledge/` + 队列与状态就位），从零沉淀 | 新团队、问题域不同、知识要私有 |
| 消费现成（带知识库） | clone 整个仓库（含 `knowledge/` 与 `references/`） | 直接用上游验证过的 case 与 reference，也可继续沉淀 | 已有沉淀、问题域重叠、想复用 |
| 定制知识面（稀疏拉取） | clone 后用 `git sparse-checkout` 收窄白名单 | 只收窄 case 数据（`knowledge/` 子集），方法论与工具仍全量 | 知识库长大后、带宽或存储受限、只要自己框架的知识 |

2. 选了稀疏拉取形态时，按白名单收窄，并重建两张生成物表。

### 稀疏拉取的白名单

白名单必须含方法论与工具全量（`skills/` `scripts/` `references/` `triage-tree.d/` `postmortems/` `ingest-state.json` `.dsh/` 等，缺了 agent 就没有 skill 可用），`knowledge/` 按需收窄（如 `vllm-ascend/` + `common/`）。两张生成物表都能重建：收窄后跑 `scripts/build_index.py` 重建索引总表；路由改过就跑 `scripts/build_triage_tree.py` 重建 `triage-tree.yaml`（它要求 `triage-tree.d/` 全在，所以白名单里那个目录不能省）；`common/` 必留占位（见 [ADR-0005](../adr/0005-knowledge-consumption-split.md)）。当前规模用全量 clone，稀疏拉取是知识库长大后的带宽优化。

## 4 怎么确认做对了

无。原文没有给出可观察的输出或状态。

## 5 出错了怎么办

无。原文没有记录失败现象与处置。

## 6 怎么退回去

无。原文没有给出回滚或清理步骤。
