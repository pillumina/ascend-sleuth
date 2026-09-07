<!-- 模板元数据（GitHub 不解析 PR 模板 frontmatter，置于注释内避免正文渲染成粗体块）：
  name: 知识修改（改已有 case 的关键字段）
  about: 修改 expected / fix_on_mismatch / compat / severity 等高风险字段，或合并 case
  labels: [kb/high-risk]（需 gh pr create --label kb/high-risk 显式打）
PR body 正文从首个 "## " 区块开始。
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

## Agent 预核意见（机器可填，可选——非 agent 链路提交可留空）

<!-- 基于事实的独立意见，供 reviewer 对齐判断——不替代人审，双签仍需人完成 -->

- 事实依据（trace 归因结论 / 反馈记录）：
- 归因判定（case 错 / 执行错 / 版本演进）：
- 风险标注（影响哪些匹配路径 / 需 spot-check 项）：

## 双签

- [ ] 领域 owner：
- [ ] 体系维护人：

## 影响与回退

- 影响范围：哪些症状匹配路径会变化
- 回退方式：revert 本 PR 即可 / 其他（说明）
- [ ] CI 绿：索引随本 PR 重建

## 关联更新（如适用）

- [ ] 对应 golden fixture 的 expected 已同步（否则回归假失败，docs/eval.md）
- [ ] 引用本 case 的 references 已检查
