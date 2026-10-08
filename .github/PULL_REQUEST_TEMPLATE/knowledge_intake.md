<!-- 模板元数据（GitHub 不解析 PR 模板 frontmatter，置于注释内避免正文渲染成粗体块）：
  name: 知识注入（新 case / postmortem 转正）
  about: 新知识经 to-postmortem 沉淀、groom 预分诊后的升格 PR
  labels: []（按需 gh pr create --label）
PR body 正文从首个 "## " 区块开始。
  首屏一个视图的写法见 methodology.md 的「变更内容」一节；本模板的证据与合入风险由
  「完整性」与「高风险检查」两节承担。
-->

## 背景与动机

<!-- 三行以内，一行一件事：这条知识从哪来（哪次诊断 / 反馈 / 外部对话）→ 不收会怎样（同类问题会被重新诊断一遍）→ 收进来之后覆盖到哪一类症状。
     写工程师能直接读的话：短句、动词开头、给具体事实或读数；不用比喻与自造缩写，也不写自我评价（如「已如实标注」）。 -->

- 触发：
- 不做的代价：
- 做完的变化：

## 预分诊结论（groom 周批审产出，机器可填）

<!-- 三分类之一，并附证据。证据 = 与现有 case 的比对结果（namespace、root_cause 重叠度） -->

- 分类：new_pattern / variant_of:\<case-id\> / covered_by:\<case-id\>
- 证据：
- 建议处置：升格 Tier 2 / 并入已有 case（扩 compat）/ 仅 postmortem 转正

## Agent 预核意见（**由独立 agent 产出**；作者不得代填；低风险改动可留空）

<!-- 独立 = 与作者不同的会话（另起 session 或 subagent），不是外部第三方，别读成担保。
     三档强度、产出格式与为什么不做成 CI 门，见 docs/guide/git-workflow.md 的「独立预核」一节。
     这段只放 reviewer 判断要用的内容：结论、按严重度排的问题、查过什么。
     命令输出与逐条证据留在预核报告里，末行给链接即可，不复制进 body。 -->

- 结论（`MERGE_READY: yes/no`，加一句最要紧的理由）：
- 核对的版本（提交号或文件哈希；还没提交写「改动前」）：
- 期望正确性（命中 case 与证据是否一致：trustworthy / uncertain / misdiagnosed）：
- 问题（逐条按严重度写：阻断级 / 重要级 / 建议级，每条一句话 + `文件:行`；没有写「无发现」）：
- 覆盖清单（查了哪些门与文件、跑了什么命令、结果如何；没查到的部分一并写明；没查出问题也要写）：
- 反例与可复跑命令（脚本与机制类填构造的反例、命令与实测结果；文档与内容类写「不适用」及原因）：
- 人读文本三项判定（可读性 / 逻辑性 / 黑话，各一行结论；没发现写「无发现」，没碰人读文本写「不适用」）：
- 预核报告（链接或 `文件:行`；没有写「无」）：

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
