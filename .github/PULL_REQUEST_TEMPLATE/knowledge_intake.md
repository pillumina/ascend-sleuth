<!-- 模板元数据（GitHub 不解析 PR 模板 frontmatter，置于注释内避免正文渲染成粗体块）：
  name: 知识注入（新 case / postmortem 转正）
  about: 新知识经 to-postmortem 沉淀、groom 预分诊后的升格 PR
  labels: []（按需 gh pr create --label）
PR body 正文从首个 "## " 区块开始。
  首屏一个视图的写法见 methodology.md 的「变更内容」一节；本模板的证据与合入风险由
  「完整性」与「高风险检查」两节承担。
-->

## 预分诊结论（groom 周批审产出，机器可填）

<!-- 三分类之一，并附证据。证据 = 与现有 case 的比对结果（namespace、root_cause 重叠度） -->

- 分类：new_pattern / variant_of:\<case-id\> / covered_by:\<case-id\>
- 证据：
- 建议处置：升格 Tier 2 / 并入已有 case（扩 compat）/ 仅 postmortem 转正

## Agent 预核意见（**由独立 agent 产出**；作者不得代填；低风险改动可留空）

<!-- 独立 = 由与作者不同的会话产出（另起 session 或 subagent）。本仓常见的 subagent 与作者同父会话，
     它看不到作者的推理，但这不是外部第三方独立，别读成担保。
     三档强度与产出格式见 docs/guide/git-workflow.md 的「评审把手」；为什么不进 CI 同处说明。
     没查出问题也要写覆盖清单：没查与没问题在 PR 上长得一样。
     这段不替代人审，高风险改动仍需双签。 -->

- 预核者（产出这条的会话；与作者不是同一次会话）：
- 事实依据（trace 摘录 / 反馈记录 / metrics 引用）：
- 期望正确性（命中 case 与证据一致：trustworthy / uncertain / misdiagnosed）：
- 风险标注（high-risk 项 / 需 spot-check 项）：
- 覆盖清单（跑了哪些门、哪些命令、结果如何；未发现问题也照写）：
- 反例与可复跑命令（填：构造了什么反例、命令、实测结果；文档与内容类填「不适用」并说明为什么）：
- 结论（填：`MERGE_READY: yes/no` + 最关键的 1–2 条）：

## 知识来源

- 来源类型：diagnose session / 外部对话 / 手工笔记 / wiki 导入
- investigation_quality：high / medium / low（决定初始 score，Beta 先验实例化，理论 §4.1）
- 初始 score 与理由：

## 脱敏自查（人填，合入前必勾）

- [ ] 日志片段不含内网 IP、密钥、token、客户名
- [ ] 集群规模/拓扑信息已泛化到诊断所需最小粒度
- [ ] 无法脱敏的字段已移入私有仓并在此注明

## 完整性（机器校验）

- [ ] CI 绿：`build_index.py --check`（索引已随本 PR 重建：分片 + 总表）
- [ ] postmortem 落位 `postmortems/YYYY-QN/`（covered 也转正，不是丢弃）
- [ ] 新 case 照 `examples/sample-case.yaml` 模板，category 形态未混用

## 高风险检查

未触碰以下任一项则无需双签；触碰任一项改用「知识修改」模板：

expected / fix_on_mismatch / compat 区间 / common/ 权威记录 / triage-tree
