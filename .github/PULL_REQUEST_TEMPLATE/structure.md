---
name: 路由与结构变更（triage-tree / namespace / 平台目录）
about: 修改路由表、拆分/新建 namespace、调整目录结构
labels: [kb/high-risk]
---

> 路由是共享资产：变更影响两个团队所有诊断的命中率。需双签；目录迁移必须同一 PR 完成全部关联更新（roadmap A2）。

## 变更类型

- [ ] triage-tree 分支修改（增/改/删正则或 search_namespaces）
- [ ] namespace 拆分 / 新建
- [ ] 平台目录调整
- [ ] 其他结构变更：

## 依据（数据驱动，原则十一）

- 触发数据：路由准确率趋势 / 容量表读数 / trace 错例（附来源）
- 无数据支撑的路由变更不接受

## Agent 预核意见（机器可填，可选——非 agent 链路提交可留空）

<!-- 基于事实的独立意见，供 reviewer 对齐判断——不替代人审，双签仍需人完成 -->

- 事实依据（trace 路由错例 / metrics 快照 / 容量读数）：
- 预期影响（路由准确率 / 候选召回的变化方向）：
- 风险标注（受影响 namespace / 需双签重点核项）：

## 迁移完整性检查单（目录变更必勾）

- [ ] case 文件迁移完成，`_archive/` 处置明确
- [ ] triage-tree `search_namespaces` 同步
- [ ] `knowledge/_index.yaml` 随本 PR 重建（CI 会验）
- [ ] golden fixture 的 namespace 断言同步
- [ ] 受影响 case 的 references 路径修正

## 双签

- [ ] 领域 owner：
- [ ] 体系维护人：
