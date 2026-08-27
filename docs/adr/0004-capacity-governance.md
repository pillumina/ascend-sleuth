# 容量治理：category 子层与参数化 cap（替代拍脑袋的 30）

## Context

- 批量导入（评估 0001）暴露增长模式与容量模型的失配：groom 的容量模型假设渐进增长（每周几条，80% 预警线有缓冲），但 issue 拉取是**批式持续知识源**——首批 19 条直达 63%，下一批必然触线。拆分从"是否"变成"何时"，而答案是"几乎立即"
- 现有 cap（30/namespace）是**拍脑袋常数**。理论 §7 明示常数是参数估计而非推导链内；roadmap 待定池"参数治理"条目正是为这类常数准备的
- 拆轴已有预定：roadmap A2 首选 category（interrupt/precision/performance）——本 ADR 只是把落地时机从"撞线后"提前到"增长模式证明必然撞线"

## Decision

**一、目录结构按 (framework × category) 分层（方案 B：目录分层、索引统一）**

```
knowledge/inference/vllm-ascend/
├── interrupt/     # 本批 13 条
├── precision/     # 3 条
├── performance/   # 2 条
└── other/         # 4 条（other 是评估 0001 发现的原生类别，保留——见注释）
```

理由（理论推导）：
1. **检索语义两轴正交**（triage 输出 category + namespace）——目录反映检索结构（原则二：结构对齐语义）
2. **信道成本不变**：`_index.yaml` 单文件带 category 分组，阶段一加载量相同；category 过滤在阶段一自然发生
3. **cap 语义精确化**：30 cap 的本意是"单次可暴力过滤的候选集规模"——(framework, category) 格子才是 triage 定 category 后实际被扫的单元。现实现 cap 在框架层，粒度比理论要求粗
4. **triage-tree 不改**：search_namespaces 仍路由到框架层，category 过滤交给 quickly_check 阶段（两轴正交设计的既有行为）
5. A2 闸门针对"要不要引入新轴"；category 轴已被预定，本 ADR 是落地时机决策，非破例先例（决策留痕，原则十一）

注：other 是评估 0001 发现的"错误签名→版本支持差异"型知识类别，超出原三分类 schema——本 ADR 保留它作为格子，同时把"是否正式入 schema"登记为待定项（观察使用后决定）。

**二、cap 参数化：常数 → 三层模型**

| 层 | 值 | 语义 | 触发动作 |
|---|---|---|---|
| soft_cap | 每格子 30 | 到达即触发**拆分评估**（非强制拆） | groom 容量表标黄 + 健康指标检查 |
| 健康指标 | 见下 | 拆分评估的判据 | 任一恶化 → 评估报告 + 拆分建议 |
| hard_cap | 每格子 60（≈ 信道物理上限，B_ctx 内可加载 60×70≈4.2K tok） | 到达强制拆分（不管健康指标） | 索引加载成本约束的硬边界 |

**健康指标（三个可观测代理，替代"数到 30"）**：

| 指标 | 定义 | 恶化阈值（初始估计，参数治理复核） | 对应约束 |
|---|---|---|---|
| 候选溢出率 | 阶段一后候选 >5 的诊断/回放占比 | >20% | 区分力（候选 ≤5 是阶段二硬约束） |
| 重复率 | groom 去重检出的同根因对 / 格子 case 数 | 连续两轮上升 | 信噪比（重复=噪声） |
| 维护时长 | groom 周审该格子耗时 | >30 分钟/周 | 注意力预算 B_attn |

**三、实现变更**

- `build_index.py`：按 (ns, category) 分组输出；每格计数进入索引头注释；支持 soft/hard cap 配置（YAML 或常量，初值 30/60）
- groom 容量表：按格子报告（计数/soft_cap + 健康指标），替代按 namespace 报告
- roadmap A2 改写：触发条件从"超 30"改为"超 soft_cap 且健康指标恶化 / 超 hard_cap 强制"
- fixture 断言：`expected.namespace` 更新为含 category 的路径

## Rejected / Deferred

- **方案 A（目录深度 +2 全量迁移）**：代价高（triage-tree 也改）且索引不省——目录分层已满足语义，无需双重改动
- **立即把 other 并入 interrupt**：其他格子的 case 语义上是"版本/模型兼容知识"而非中断——并入会污染 category 判别（评估 0001 已证明其可检索性）。保留，观察
- **cap 全动态无上限**：信道物理约束是硬性的（hard_cap），不可为"可调"牺牲。动态调节发生在 soft_cap 与健康指标层，hard_cap 恒定

## 索引字段拆分（本 ADR 的延续，PR #8）

`_index.yaml` 条目只保留 `confidence.score`（阶段一排序所需）；hits/misdiagnoses 是学习环动态字段（Beta 后验），留在 case 本体，由 groom 置信度重算读取，不入检索视图。理由：动态字段进静态索引 → 每次反馈全量重建 + diff 噪音 + `--check` 把"索引过期"与"置信度未同步"混淆。索引是生成物，只读，不手改。

## 参数治理（本 ADR 的参数归属）

soft_cap=30、健康指标阈值、hard_cap=60 均为初始估计，服从 roadmap"参数治理"条目：metrics 实测（候选溢出率来自回放 harness/trace、维护时长来自 groom 报告）后按理论 §4.4 复核。首个复核点：评估 0001 的回放数据即可给出候选溢出率基线（当前 21 例溢出 0 次——格子健康，支持 30 起步）。
