---
name: knowledge-groom
description: >
  昇腾知识库的周期性维护引擎。扫 postmortems/ 新增记录（含 agent 自起草的候选 case），
  结构化升格到 Tier 2、校验 references 完整性、检测值重复、重算 confidence_score、
  软退休过期 case、重生成 CHEATSHEET.md。建议每周运行。产出 PR 交领域 owner 审。
disable-model-invocation: true
---

# Knowledge Groom

体系的演化引擎。不加控制的增长会摧毁检索效率——这个 skill 是知识库的"免疫系统 + 清道夫"。

## 触发

手动运行，建议每周一次（连续四周无新 postmortem 则自动切双周）。

## 流程（一次 groom 产出一个 PR）

1. **升格**：扫 `postmortems/` 未处理记录（含 agent 自起草的候选 case），结构化 + 语义校验 → YAML → 追加 `knowledge/<ns>/`。语义校验失败标 `needs-structurer-review`，语义不明标 `needs-human-review`。
2. **引用完整性校验**：扫所有 case 的 `references`，检查指向真实存在的文件和锚点。悬挂引用进 PR 报告（自演化系统的"坏账"，不校验会静默累积）。
3. **值重复检测**：框架 case 的 `expected`/`fix_on_mismatch` 是否硬编码了 `common/` 权威记录拥有的值？是 → 标 must-fix，要求改成引用。
4. **置信度重算**：从 `hits`/`misdiagnoses`/`last_hit` 重算每条 case 的 `confidence.score`（按时间衰减）。
5. **软退休**：区分两种"未命中"——
   - **cold**（从未被 quickly_check 选中）→ **不退**（正确但罕见的 case 占索引成本极低，误删是静默损失）
   - **tried-and-failed**（被选中但近 12 周未解决）且 `score` 低 → 移入 `_archive/`
   - `compat` 版本过期 → 移入 `_archive/`（与命中无关）
   - 检查 `_archive/` 中 case 是否因新 `compat` 区间该复活（2.7 退休、2.8 恢复）
6. **namespace 拆分建议**：某 namespace 超 30 条 → 报告内容分布 + 拆分建议（首选拆分轴是 **category**——interrupt/precision/performance）。人确认后才建子目录。
7. **同 namespace 合并建议**：相似 case 对自动提示。
8. **CHEATSHEET 重生成**：按 `namespace × category` 分段（如 `## training/mindspeed-llm / interrupt`）——遇到精度问题直接翻 precision 段。

## PR 里的高风险变更标记（强制深审，不走 30 秒快通道）

- 新建 `common/` 权威记录
- 改 `expected` 值
- 改 `fix_on_mismatch`
- 改 `compat` 区间
- `confidence.score` 被手动覆盖

高风险变更要求两个 owner 签字（领域 owner + 体系维护人）。PR 在 session 内**随机排序**审，对抗疲劳——一个 session 审 30 条 PR，第 30 条得到的 scrutiny 远少于第 1 条，随机化缓解这个偏差。

## 信号 → 动作（演化信号表）

| 信号 | 动作 |
|---|---|
| 单 namespace 超 30 条 | 给拆分建议（首选 category 轴） |
| 两个框架 namespace 各有条 case 指向同 root cause | 在 `common/` 建权威记录，框架层加 `references` |
| Tier 2 未命中率 > 60% 持续两周 | **先看路由准确率**（见 docs/metrics.md）：路由准确率低→改 triage-tree；路由准但未命中→加 case |
| 某 case `score` 高且命中频繁 | 进候选优先验证队列 |
| 某 case `score` 低仍被加载 | 标待复审；命中一次失败即转人工 |
| 某案例 `needs-structurer-review` 超 14 天 | 提醒领域 owner |

## v2 职责（路线图，v1 不做）

9. **结构挖掘**：挖 trace 语料，报告低判别力 `quickly_check`、噪声 triage 分支、高验证耗时 case。让库学结构，不只 bump 分数。
10. **trusted auto-promotion 审计**：近重复 + quickly_check 通过 + 连续 N 次兄弟命中未误诊的新 case 可 auto-promote，标 `auto_promoted: true`，进月度抽审。
