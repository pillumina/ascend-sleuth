# Retrieval: lightweight generated index, no vector RAG

知识检索采用"生成式轻量索引"（`knowledge/_index.yaml`），不引入向量检索 / RAG 基础设施。embedding 字段化（intake 语义去重）**推迟而非否决**，重评触发条件见文末。

## Context（需求参数）

- 增速：**200~400 篇 postmortem/年**（含重复，入库需人审）→ Tier 2 稳态预估 300~600 条（3 年，按 category 拆分后 ~15 个 namespace × 30 上限 ≈ 450 容量，大体匹配、边缘紧张）
- **过滤率 / 退休率当前未知，不作为前置输入**——第一年由 `scripts/trace_metrics.py` 实测替代，届时重算本 ADR 的容量推演
- 团队：训练 / 推理两个团队共用一个 repo（非跨组织联邦）
- 运行形态：工程师笔记本上的 agent（pi / Claude Code / Codex），repo 即数据库

## Decision

1. **不上向量检索 / RAG。** 四重错配：
   - 检索信号是**词法的**（错误签名、错误码、数值阈值），embedding 对精确串匹配是降质不是增强；
   - **agent 本身就是语义层**（能 grep、换关键词、读片段再下探），经典 RAG"哑检索器服务不能行动的模型"的前提在这里不成立；
   - **repo 即数据库 = 知识变更可 diff、可审、可回滚**；向量库是不可 diff 的二进制产物，破坏 groom 的审计链；
   - 零服务、零依赖、可进隔离环境，是 skill 可扩散的前提。
2. **Tier 2 阶段一改为读生成索引** `knowledge/_index.yaml`：把"只加载索引字段"从 prompt 纪律变成**结构保证**。索引由 `scripts/build_index.py` 生成、提交进 git、`--check` 校验新鲜度（groom 每次跑，可挂 CI）。30/namespace 上限是**承重设计**：它保证全量索引 ~30K token 一次加载、暴力过滤永远成立——cap 使"永不购买检索基础设施"成为合法选型。
3. **intake 队列**：新沉淀进 `postmortems/inbox/`，groom 周批处理三分类（new_pattern / variant_of / covered_by），**预分诊给建议 + 证据，人做最终判定**。预分诊当前由 agent（LLM 判断）完成，不引入 embedding。covered ≠ 丢弃：postmortem 照样转正 Tier 3 语料。

## Rejected / Deferred

- **向量库 + ANN**（否决）：为 10⁴ 量级召回设计，本库 cap 在 ~600，物理上用不到；且不可 diff。
- **embedding sidecar**（推迟，主动选择）：单条 case 加 `semantics.text_hash` + `.embeddings/*.vec` sidecar 的设计已论证（模型版本字段、hash 锁一致性、人审文件 diff 保持干净），但当前周 4-8 篇的量能下，一致性管理成本 > 收益。触发条件满足时按此设计落地，不需要重新论证。

## 重评触发条件（数据驱动，不时尚驱动）

以下任一出现才重开本决策，否则不进路线图：

- 单 namespace 拆分后仍 >100 条，且路由准确率持续下降（看 `trace_metrics.py`）；
- Tier 3 语料 >5K 篇，且 grep 兜底挽救率可测地不足；
- 真出现多组织联邦（当前两团队一 repo 不算）。
