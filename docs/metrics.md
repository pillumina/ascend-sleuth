# ascend-sleuth Metrics

> 多数指标可半自动计算：`python3 scripts/trace_metrics.py` 从 trace 生成 markdown 表，人复核后追加到本文件。小样本时比例波动大，解读先看分母。季度回顾时用真实数据校准阈值。

## 指标定义

| 指标 | 含义 |
|---|---|
| 命中率 | Tier 2 直接匹配解决的比例 |
| 误诊率 | 命中了但 fix 没解决 |
| 路由准确率 | 最终 root cause 所在 namespace 是否在被加载集合里 |
| 执行-误诊归因比 | 误诊中 case 错 vs 执行错 |
| 按类命中 | interrupt / precision / performance 各自命中率 |
| 置信度分布 | 低置信 case 占比、低置信高命中 case 数 |
| 自起草采纳率 | groom 验证通过的草案 / agent 起草总数 |
| trace 完整性 | 有 trace 记录的 step / 实际执行 step |
| Tier 3 挽救率 | 走了 Tier 3 兜底检索且最终 resolved 的比例（trace `tier3` action） |
| 反馈捕获率 | 回报 fix 结果的 session / 给出 fix 的 session（学习环的吞吐上限，trace `feedback` action） |

---

## 2026-W28（示例）

- 处理 issue: 12（/diagnose 诊断 7 / 外部沉淀 5）
- Tier 2 命中: 7 (58%)
- 误诊: 1（归因：case错 1 / 执行错 0）
- 路由准确率: 10/12 (83%)
- 按类命中: interrupt 5/6 / precision 1/3 / performance 1/3
- 低置信 case 占比: 3/47
- 自起草采纳率: 1/1 (100%)
- trace 完整性: 11/12 (92%)
- 新增 postmortem: 4（含 agent 自起草 1）/ 升格: 2
- 软退休: 1
- groom backlog: 6（绿）
- 平均诊断时间: ~45min

<!-- 季度回顾问题：这三层架构真的在变好用，还是我们在自欺欺人？ -->
