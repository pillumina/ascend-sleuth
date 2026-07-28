# ascend-sleuth Metrics

> 两周一次手工追加。有数字比没有重要得多。季度回顾时用真实数据校准 §8.3 的阈值。

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

---

## 2026-W28（示例）

- 处理 issue: 12（路径 A 7 / B 5）
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
