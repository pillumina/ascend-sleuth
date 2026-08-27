# ascend-sleuth Metrics

多数指标可以半自动计算：`python3 scripts/trace_metrics.py` 从 trace 生成 markdown 指标表，人复核后追加到本文件。比例类指标务必连同分母一起解读，样本量小（分母不足 10）时波动很大，不宜直接下结论。季度回顾时用实测数据校准各项阈值，包括 [roadmap](roadmap.md) 中的闸门数值。

## 指标定义

| 指标 | 含义 |
|---|---|
| 命中率 | Tier 2 直接匹配并解决的比例 |
| 误诊率 | 命中了但 fix 没有解决问题的比例 |
| 路由准确率 | 最终 root cause 所在 namespace 是否在被加载集合内 |
| 执行-误诊归因比 | 误诊中 case 错与执行错的比例 |
| 按类命中 | interrupt / precision / performance 各自的命中率 |
| 置信度分布 | 低置信 case 占比、低置信高命中 case 数 |
| 自起草采纳率 | groom 验证通过的草案 / agent 起草总数 |
| trace 完整性 | 有 trace 记录的 step / 实际执行 step |
| Tier 3 挽救率 | 走 Tier 3 兜底检索且最终 resolved 的比例（trace `tier3` action） |
| 反馈捕获率 | 回报 fix 结果的 session / 给出 fix 的 session，反映学习环的实际吞吐（trace `feedback` action） |

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

> 数据来自 docs/eval-reports/0001（21 例措辞差+交叉回放）。回放非活诊断，指标口径见该报告 §二；小样本（n=21）波动大。

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
