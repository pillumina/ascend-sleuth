<!-- 模板元数据（GitHub 不解析 PR 模板 frontmatter，置于注释内避免正文渲染成粗体块）：
  name: 路由与结构变更（triage-tree / namespace / 平台目录）
  about: 修改路由表、拆分/新建 namespace、调整目录结构
  labels: [kb/high-risk]（需 gh pr create --label kb/high-risk 显式打）
PR body 正文从首个 "## " 区块开始。
  首屏一个视图的写法见 methodology.md 的「变更内容」一节；本模板的证据与合入风险由
  「依据」与「迁移完整性检查单」两节承担。
-->

> 路由是共享资产：变更影响两个团队所有诊断的命中率。需双签；目录迁移必须同一 PR 完成全部关联更新（roadmap A2）。

## 变更类型

- [ ] triage-tree 分支修改（增/改/删正则或 search_namespaces）
- [ ] namespace 拆分 / 新建
- [ ] 平台目录调整
- [ ] 其他结构变更：

## 依据（数据驱动，原则十一）

- 触发数据：路由准确率趋势 / 容量表读数 / trace 错例（附来源）
- 无数据支撑的路由变更不接受

## Agent 预核意见（**由独立 agent 产出**；作者不得代填；低风险改动可留空）

<!-- 独立 = 由与作者不同的会话产出（另起 session 或 subagent）。本仓常见的 subagent 与作者同父会话，
     它看不到作者的推理，但这不是外部第三方独立，别读成担保。
     三档强度与产出格式见 docs/guide/git-workflow.md 的「评审把手」；为什么不进 CI 同处说明。
     没查出问题也要写覆盖清单：没查与没问题在 PR 上长得一样。
     这段不替代人审，高风险改动仍需双签。 -->

- 预核者（产出这条的会话；与作者不是同一次会话）：
- 事实依据（trace 路由错例 / metrics 快照 / 容量读数）：
- 预期影响（路由准确率 / 候选召回的变化方向）：
- 风险标注（受影响 namespace / 需双签重点核项）：
- 覆盖清单（跑了哪些门、哪些命令、结果如何；未发现问题也照写）：
- 反例与可复跑命令（填：构造了什么反例、命令、实测结果；文档与内容类填「不适用」并说明为什么）：
- 结论（填：`MERGE_READY: yes/no` + 最关键的 1–2 条）：

## 迁移完整性检查单（目录变更必勾）

- [ ] case 文件迁移完成，`_archive/` 处置明确
- [ ] 路由 `search_namespaces` 同步（改的是 `triage-tree.d/<族>.yaml`，不是生成的 `triage-tree.yaml`）
- [ ] 生成物随本 PR 一起提交（跑 `python3 scripts/build_index.py` 与 `python3 scripts/build_triage_tree.py` 后 `git add`）：索引分片、总表、路由族文件、路由聚合
- [ ] golden fixture 的 namespace 断言同步
- [ ] 受影响 case 的 references 路径修正

## 双签

- [ ] 领域 owner：
- [ ] 体系维护人：
