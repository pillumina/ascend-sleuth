---
name: knowledge-groom
description: >
  昇腾知识库的周期性维护引擎。批处理 postmortems/inbox/ 待审队列（预分诊 new/variant/covered 三分类），
  结构化升格到 Tier 2、校验 references 完整性、检测值重复、重算 confidence_score、
  软退休过期 case、重建生成索引。建议每周运行。产出**变更摘要 + 待审项**交领域 owner 审；提交由 owner 自己来（不自动开 PR）。
disable-model-invocation: true
---

# Knowledge Groom

体系的演化引擎。不加控制的增长会摧毁检索效率——这个 skill 是知识库的"免疫系统 + 清道夫"。

## 触发

手动运行，建议每周一次（连续四周无新 postmortem 则自动切双周）。

## 流程（一次 groom 产出一个变更摘要）

1. **intake 队列批处理（升格的前置）**：处理 `postmortems/inbox/`（`/skill:to-postmortem` 的产出 + agent 自起草候选都落这里）：
   - 逐条**预分诊**（agent 判断，给证据；当前不引入 embedding，论证见 docs/adr/0002）：`new_pattern` / `variant_of:<case-id>` / `covered_by:<case-id>` + 置信度。比对对象：命中 namespace + `common/` 的现有 case——用 `knowledge/_index.yaml` 按 symptoms/tags 定位候选，全量读比对 root_cause 与 fix
   - 产出**批审清单**交 owner 周批处理（像清 PR inbox，~30 秒/条）：
     - `covered_by` → 建议关闭升格；postmortem 转正 `postmortems/YYYY-QN/`（Tier 3 语料，**不是丢弃**）
     - `variant_of` → 建议并入已有 case（扩 compat 区间、补 symptoms）；若要动 `expected`/`fix_on_mismatch` 按高风险变更走双签
     - `new_pattern` → 结构化 + 语义校验 → 升格 `knowledge/<ns>/`。校验失败标 `needs-structurer-review`，语义不明标 `needs-human-review`
   - inbox 停留 >2 周的条目在摘要里标红（队列不是档案）
   - **建议与决定分离**：预分诊只排序注意力，accept / adjust / reject 由人
2. **引用完整性校验**:扫所有 case 的 `references`,检查指向真实存在的文件和锚点。悬挂引用进变更摘要（自演化系统的“坏账”，不校验会静默累积）。
3. **值重复检测**：框架 case 的 `expected`/`fix_on_mismatch` 是否硬编码了 `common/` 权威记录拥有的值？是 → 标 must-fix，要求改成引用。
4. **置信度重算**：从 `hits`/`misdiagnoses`/`last_hit` 重算每条 case 的 `confidence.score`（按时间衰减）。**新升格的 case 初始 score 不设 0**——按 to-postmortem 标的 `confidence`（人的调查质量判断）设初始值：high→0.6、medium→0.3、low→0.1。score=0 意味着新 case 永远排候选最后，对 5 天详查的高质量 case 不合理。
5. **软退休**：区分两种"未命中"——
   - **cold**（从未被 quickly_check 选中）→ **不退**（正确但罕见的 case 占索引成本极低，误删是静默损失）
   - **tried-and-failed**（被选中但近 12 周未解决）且 `score` 低 → 移入 `_archive/`
   - `compat` 版本过期 → 移入 `_archive/`（与命中无关）
   - 检查 `_archive/` 中 case 是否因新 `compat` 区间该复活（2.7 退休、2.8 恢复）
6. **namespace 拆分建议**：某 namespace 超 30 条 → 报告内容分布 + 拆分建议（首选拆分轴是 **category**——interrupt/precision/performance）。人确认后才建子目录。每次 groom 附**容量表**：各 namespace 条数 / 30 上限百分比、近 4 周增速（从 inbox 转正记录算）——达 80%（24/30）即**预告**拆分，不等超限。拆分被数据预告，不被卡住才想起（容量论证见 docs/adr/0002）。
7. **同 namespace 合并建议**：相似 case 对自动提示。
8. **索引维护（收尾必做）**：所有 KB 变更（升格/合并/退休/改 confidence）完成后，运行 `python3 scripts/build_index.py` 重新生成 `knowledge/_index.yaml` 并随变更摘要一起提交。`--check` 报过期 = 变更不完整（忘了重建索引）。软退休的 case 移 `_archive/` 后自动从活跃索引消失。

## 变更摘要里的高风险变更标记（强制深审，不走 30 秒快通道）

- 新建 `common/` 权威记录
- 改 `expected` 值
- 改 `fix_on_mismatch`
- 改 `compat` 区间
- `confidence.score` 被手动覆盖

高风险变更要求两个 owner 签字（领域 owner + 体系维护人）。变更在 session 内**随机排序**审，对抗疲劳——一个 session 审 30 条变更，第 30 条得到的 scrutiny 远少于第 1 条，随机化缓解这个偏差。git 落地：变更走 PR 并打 `kb/high-risk` 标签，`CODEOWNERS` 双组路径强制对应 owner 审批，细节见 `docs/git-workflow.md`（owner 未定前用 `CODEOWNERS.example` 占位，机制先跑）。

## 信号 → 动作（演化信号表）

| 信号 | 动作 |
|---|---|
| 单 namespace 超 30 条 | 给拆分建议（首选 category 轴） |
| 两个框架 namespace 各有条 case 指向同 root cause | 在 `common/` 建权威记录，框架层加 `references` |
| Tier 2 未命中率 > 60% 持续两周 | **先看路由准确率**（见 docs/metrics.md）：路由准确率低→改 triage-tree；路由准但未命中→加 case |
| 某 case `score` 高且命中频繁 | 进候选优先验证队列 |
| 某 case `score` 低仍被加载 | 标待复审；命中一次失败即转人工 |
| 某案例 `needs-structurer-review` 超 14 天 | 提醒领域 owner |
| inbox 条目停留 >2 周 | 变更摘要标红，提醒 owner（队列不是档案） |
| 某 namespace 达容量 80%（24/30） | 预告 category 拆分建议，不等超限 |

## v2 职责（路线图，v1 不做）

8. **结构挖掘**：挖 trace 语料，报告低判别力 `quickly_check`、噪声 triage 分支、高验证耗时 case。让库学结构，不只 bump 分数。
9. **trusted auto-promotion 审计**：近重复 + quickly_check 通过 + 连续 N 次兄弟命中未误诊的新 case 可 auto-promote，标 `auto_promoted: true`，进月度抽审。
