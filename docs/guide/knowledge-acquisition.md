# 知识获取：三种起步形态

**仓库即 workspace**：诊断读 `knowledge/`、`references/` 与 `triage-tree.yaml`，沉淀写 `postmortems/inbox/`、`references/` 与 `ingest-state.json`，读写都发生在同一个 clone 里。SKILL 里的知识路径相对仓根，所以三种形态都要先有知识仓结构。

| 形态 | 起步方式 | 结果 | 适合谁 |
|---|---|---|---|
| 自积累（空仓起步） | clone 本仓（或 fork）后清空 `knowledge/` | 结构完整（`skills/` + 空 `knowledge/` + 队列与状态就位），从零沉淀 | 新团队、问题域不同、知识要私有 |
| 消费现成（带知识库） | clone 整个仓库（含 `knowledge/` 与 `references/`） | 直接用上游验证过的 case 与 reference，也可继续沉淀 | 已有沉淀、问题域重叠、想复用 |
| 定制知识面（稀疏拉取） | clone 后用 `git sparse-checkout` 收窄白名单 | 只收窄 case 数据（`knowledge/` 子集），方法论与工具仍全量 | 知识库长大后、带宽或存储受限、只要自己框架的知识 |

`npx skills add -s <skill>` 只装 skill，不构成可用形态：SKILL 的知识路径（`postmortems/inbox/`、`references/`、`ingest-state.json`）相对仓根，没有知识仓结构的裸 skill 无法沉淀。它适合在已有仓库里临时试用诊断方法论（不沉淀回本仓），或把 `skills/` 合并进自己已有结构的仓库。`-g` 与 `-s` 的确切行为以 `npx skills add --help` 为准：不同版本的安装器对"仓库整体还是指定 skill"的粒度有差异。

三种形态共用同一套 skill 与机制，可以递进：自积累的团队脱敏后可选回馈上游，补充上游的公开库。

## 稀疏拉取的白名单

白名单必须含方法论与工具全量（`skills/` `scripts/` `references/` `triage-tree.d/` `postmortems/` `ingest-state.json` `.dsh/` 等，缺了 agent 就没有 skill 可用），`knowledge/` 按需收窄（如 `vllm-ascend/` + `common/`）。两张生成物表都能重建：收窄后跑 `scripts/build_index.py` 重建索引总表；路由改过就跑 `scripts/build_triage_tree.py` 重建 `triage-tree.yaml`（它要求 `triage-tree.d/` 全在，所以白名单里那个目录不能省）；`common/` 必留占位（见 [ADR-0005](../adr/0005-knowledge-consumption-split.md)）。当前规模用全量 clone，稀疏拉取是知识库长大后的带宽优化。

## 部署形态与目录归属

集中式与框架式 fork 两种形态的差别，以及每条路径归谁写（同步时冲突按哪条规则处理），见 [git-workflow.md](git-workflow.md) 的「部署形态」与「目录归属」两节。两种形态下 inbox、groom、索引与 CI 机制的工作方式相同。
