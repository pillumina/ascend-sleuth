# ascend-sleuth Metrics

多数指标可以半自动计算：`python3 scripts/trace_metrics.py` 从 trace 生成 markdown 指标表，人复核后追加到本文件。比例类指标务必连同分母一起解读，样本量小（分母不足 10）时波动很大，不宜直接下结论。季度回顾时用实测数据校准各项阈值，包括 [roadmap](roadmap.md) 中的闸门数值。

## 指标定义

| 指标 | 含义 | 实现 |
|---|---|---|
| 命中率 | Tier 2 直接匹配并解决的比例 | `trace_metrics.py`（Tier 2 命中 session 数） |
| 误诊率 | 命中了但 fix 没有解决问题的比例 | `trace_metrics.py`（hit + feedback not_resolved/partial） |
| 路由准确率 | 最终 root cause 所在 namespace 是否在被加载集合内 | `trace_metrics.py`（triage.routed vs hit.case） |
| 执行-误诊归因比 | 误诊中 case 错与执行错的比例 | `trace_metrics.py`（trace `attribution` 事件 verdict，由 diagnose 反馈 not_resolved 后自动归因） |
| 按类命中 | interrupt / precision / performance 各自的命中率 | `trace_metrics.py`（trace triage/triage_semantic 的 category vs hit） |
| 置信度分布 | 低置信 case 占比、低置信高命中 case 数 | `trace_metrics.py`（索引 score 统计） |
| 自起草采纳率 | groom 验证通过的草案 / agent 起草总数 | 无实现（E1 agent 自起草未落地，无数据源——E1 落地后补） |
| trace 完整性 | 有 trace 记录的 step / 实际执行 step | `trace_metrics.py`（proxy：含 triage + 过滤步） |
| Tier 3 挽救率 | 走 Tier 3 兜底检索且最终 resolved 的比例（trace `tier3` action） | `trace_metrics.py` |
| 反馈捕获率 | 回报 fix 结果的 session / 给出 fix 的 session，反映学习环的实际吞吐（trace `feedback` action） | `trace_metrics.py` |

---

## 2026-W28（示例）

- 处理 issue: 12（/diagnose 诊断 7 / 外部沉淀 5）
- Tier 2 命中: 7 (58%)
- 误诊: 1（归因：case 错 1 / 执行错 0）
- 路由准确率: 10/12 (83%)
- 按类命中: interrupt 5/6 / precision 1/3 / performance 1/3
- 低置信 case 占比: 3/47
- 自起草采纳率: 1/1 (100%)
- trace 完整性: 11/12 (92%)
- 新增 postmortem: 4（含 agent 自起草 1）/ 升格: 2
- 软退休: 1
- groom backlog: 6（绿）
- 平均诊断时间: ~45min

---

## 2026-W35（首批真实数据：vllm-ascend 批量导入评估，回放模式）

> 数据来自首次真实数据评估 eval-reports/0001（21 例措辞差+交叉回放，git 历史可查）。回放非活诊断；小样本（n=21）波动大。

- 语义校验通过率: 21/21 (100%)——真实日志 regex 实测（首次大规模验证）
- 预分诊: new 19 / variant 2 / covered 0；variant 判定待人核（抽审）
- 路由准确率: 19/21 (90%)；2 例经 uncategorized 优雅退化救回
- 候选召回: 16/21 (76%)；miss 5 例全部归因"签名在跟帖不在首帖"
- rank1: 13 / top3: 16（rank2 两例为同分并列，印证 top-3 口径）
- 交叉回放（variant 并入验证）: 2/2 rank1 命中主 case
- 按类命中: precision 3/3 / interrupt 7/10 / other 2/2 / performance 0/1（metric 形态与 regex 回放不匹配——机制性，见报告 §四.4）
- golden 套件: 2 → 23（真实 fixture，解锁 M2 闸门）
- 库容量: inference/vllm-ascend 格子：interrupt 11/30 / precision 3/30 / performance 2/30 / other 3/30（ADR-0004 格子口径，均低于 soft_cap）

<!-- 季度回顾固定动作：核对命中率/误诊率/路由准确率趋势，校准 roadmap 闸门数值，确认学习闭环在数据上成立 -->

## 指标口径补充：reference 层（ADR-0008 观测性，2026-08-28 起）

> `scripts/trace_metrics.py` 现产出 reference 指标（与 case 指标同源——同一 diagnosis_state trace 管道，不新增采集动作）。
> **汇总职责：metrics 由 owner 在 groom 周批时集中生成并 append（每期一条，团队共享）。工程师不提交 metrics——诊断 trace 留在本地（.gitignore），反馈走 case confidence PR；中心化指标（命中/误诊/confidence 分布）直接从仓库 case 统计，无需工程师动作。**
> 口径：

- **reference 引用次数（hits）**：trace `reference_lookup` 事件计数（diagnose 阶段 2.5 实际发生的查询，非每次诊断必查）；
- **引用后 resolve 率**：引用某 ref 的诊断 session 中 `status: resolved` 占比——outcome 从 session 最终状态**派生**，不新增回报动作；
- **平台分布**：`reference_lookup` 事件的 platform 字段聚合——覆盖矩阵（哪些平台缺 ref）的依据；
- **无数据如实显示**：reference 刚建立时 hits=0 是现状，不是 bug——等 trace 积累 ≥2-3 期后再按实测设参考线（原则十一：假设换成实测，不拍脑袋）。

## 2026-W35 容量更新（1.0.0 打 tag 时点，2026-08-29）

> 1.0.0 release 前的容量快照（ADR-0004 格子口径，`scripts/build_index.py` 头注实时值）。

- 库容量: inference/vllm-ascend：interrupt **32/30（已超 soft_cap）** / performance 3/30 / precision 6/30；inference/sglang interrupt 1/30
- 触发评估：interrupt 格子超 soft_cap（roadmap A2 入口闸门）——健康指标（候选溢出率/重复率/维护时长）恶化或超 hard_cap 60 才强制拆分；当前先记录，拆分建议由下一轮 groom 数据判定
- case 总数: 42（全 active）；reference 总数: 95（全 active）
