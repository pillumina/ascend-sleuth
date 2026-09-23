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

<!-- 独立 = 新上下文的 agent，看不到作者的推理过程——作者自评漏掉的东西，正是这一段要抓的
     （实测：一次结构改动的作者自评漏了 1 条阻断级 + 2 条重要级问题，独立 agent 评出来了）。
     三档强度、产出格式与「为什么不做成 CI 门」见 docs/guide/git-workflow.md 的「评审把手」。
     没查出问题也要给覆盖清单——否则「没问题」与「没查」在 PR 上长得一样。
     不替代人审；高风险改动仍需双签。 -->

- 预核者（独立 agent 的 session / 模型；与作者上下文无关）：
- 事实依据（trace 路由错例 / metrics 快照 / 容量读数）：
- 预期影响（路由准确率 / 候选召回的变化方向）：
- 风险标注（受影响 namespace / 需双签重点核项）：
- 覆盖清单（跑了哪些门 / 哪些命令 / 结果；没查出问题也照写）：
- 反例与可复跑命令（改了判定逻辑、生成器或门时必填；文档与内容类写「不适用」并说明为什么）：
- 结论（`MERGE_READY: yes/no` + 最关键的 1–2 条）：

## 迁移完整性检查单（目录变更必勾）

- [ ] case 文件迁移完成，`_archive/` 处置明确
- [ ] 路由 `search_namespaces` 同步（改的是 `triage-tree.d/<族>.yaml`，不是生成的 `triage-tree.yaml`）
- [ ] 生成物随本 PR 一起提交（跑 `python3 scripts/build_index.py` 与 `python3 scripts/build_triage_tree.py` 后 `git add`）：索引分片、总表、路由族文件、路由聚合
- [ ] golden fixture 的 namespace 断言同步
- [ ] 受影响 case 的 references 路径修正

## 双签

- [ ] 领域 owner：
- [ ] 体系维护人：
