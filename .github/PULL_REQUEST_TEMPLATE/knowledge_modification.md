<!-- 模板元数据（GitHub 不解析 PR 模板 frontmatter，置于注释内避免正文渲染成粗体块）：
  name: 知识修改（改已有 case 的关键字段）
  about: 修改 expected / fix_on_mismatch / compat / severity 等高风险字段，或合并 case
  labels: [kb/high-risk]（需 gh pr create --label kb/high-risk 显式打）
PR body 正文从首个 "## " 区块开始。
  首屏一个视图的写法见 methodology.md 的「变更内容」一节；本模板的证据与合入风险由
  「变更依据」与「影响与回退」两节承担。
-->

> 高风险变更：错误修改会污染后续所有诊断。需领域 owner + 体系维护人双签（原则六：代价大的变更多一道闸）。

## 触发条款（勾选全部适用项）

- [ ] 修改 `expected` 值
- [ ] 修改 `fix_on_mismatch` / `rollback`
- [ ] 修改 `compat` 版本区间
- [ ] 修改 `severity` / `fix_side_effects`
- [ ] 新建 `common/` 权威记录
- [ ] 手动覆盖 `confidence.score`
- [ ] case 合并 / 拆分

## 变更依据（必填：证据链，不接受"感觉应该改"）

- 触发来源：误诊归因（trace 结论）/ fix 结果反馈 / 版本演进 / 其他
- 证据（trace 摘录 / 反馈记录 / 版本发布说明）：

## Agent 预核意见（**由独立 agent 产出**；作者不得代填；低风险改动可留空）

<!-- 独立 = 新上下文的 agent，看不到作者的推理过程——作者自评漏掉的东西，正是这一段要抓的
     （实测：一次结构改动的作者自评漏了 1 条阻断级 + 2 条重要级问题，独立 agent 评出来了）。
     三档强度、产出格式与「为什么不做成 CI 门」见 docs/guide/git-workflow.md 的「评审把手」。
     没查出问题也要给覆盖清单——否则「没问题」与「没查」在 PR 上长得一样。
     不替代人审；高风险改动仍需双签。 -->

- 预核者（独立 agent 的 session / 模型；与作者上下文无关）：
- 事实依据（trace 归因结论 / 反馈记录）：
- 归因判定（case 错 / 执行错 / 版本演进）：
- 风险标注（影响哪些匹配路径 / 需 spot-check 项）：
- 覆盖清单（跑了哪些门 / 哪些命令 / 结果；没查出问题也照写）：
- 反例与可复跑命令（改了判定逻辑、生成器或门时必填；文档与内容类写「不适用」并说明为什么）：
- 结论（`MERGE_READY: yes/no` + 最关键的 1–2 条）：

## 双签

- [ ] 领域 owner：
- [ ] 体系维护人：

## 影响与回退

- 影响范围：哪些症状匹配路径会变化
- 回退方式：revert 本 PR 即可 / 其他（说明）
- [ ] CI 绿：索引随本 PR 重建

## 关联更新（如适用）

- [ ] 对应 golden fixture 的 expected 已同步（否则回归假失败，docs/guide/eval.md）
- [ ] 引用本 case 的 references 已检查
