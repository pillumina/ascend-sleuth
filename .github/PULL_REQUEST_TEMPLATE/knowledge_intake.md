---
name: 知识注入（新 case / postmortem 转正）
about: 新知识经 to-postmortem 沉淀、groom 预分诊后的升格 PR
labels: []
---

## 预分诊结论（groom 周批审产出，机器可填）

<!-- 三分类之一，并附证据。证据 = 与现有 case 的比对结果（namespace、root_cause 重叠度） -->

- 分类：new_pattern / variant_of:\<case-id\> / covered_by:\<case-id\>
- 证据：
- 建议处置：升格 Tier 2 / 并入已有 case（扩 compat）/ 仅 postmortem 转正

## Agent 预核意见（机器可填，可选——agent 提交链路未打通时人工填写或留空）

<!-- 基于事实的独立意见，供 reviewer 对齐判断——不替代人审；非 agent 链路提交可留空 -->

- 事实依据（trace 摘录 / 反馈记录 / metrics 引用）：
- 期望正确性（命中 case 与证据一致：trustworthy / uncertain / misdiagnosed）：
- 风险标注（high-risk 项 / 需 spot-check 项）：

## 知识来源

- 来源类型：diagnose session / 外部对话 / 手工笔记 / wiki 导入
- investigation_quality：high / medium / low（决定初始 score，Beta 先验实例化，理论 §4.1）
- 初始 score 与理由：

## 脱敏自查（人填，合入前必勾）

- [ ] 日志片段不含内网 IP、密钥、token、客户名
- [ ] 集群规模/拓扑信息已泛化到诊断所需最小粒度
- [ ] 无法脱敏的字段已移入私有仓并在此注明

## 完整性（机器校验）

- [ ] CI 绿：`build_index.py --check`（索引已随本 PR 重建）
- [ ] postmortem 落位 `postmortems/YYYY-QN/`（covered 也转正，不是丢弃）
- [ ] 新 case 照 `examples/sample-case.yaml` 模板，category 形态未混用

## 高风险检查

未触碰以下任一项则无需双签；触碰任一项改用「知识修改」模板：

expected / fix_on_mismatch / compat 区间 / common/ 权威记录 / triage-tree
