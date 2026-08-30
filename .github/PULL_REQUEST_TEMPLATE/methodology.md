---
name: 方法论变更（skill / scripts / docs / eval）
about: 修改 skills/、scripts/、docs/、eval/ 等框架本身
labels: []
---

## 变更内容

- 对象：SKILL.md / 脚本 / 文档 / fixture
- 动机：

## 原则追溯（原则文件的元规则：不可追溯的变更是可疑的）

- 本变更服务哪条设计原则：
- 是否修改了原则/理论本身的语义：否 / 是（需先走 ADR）

## 回归检查（改 skill 本身必做，docs/eval.md）

- [ ] 改动前跑了 golden 套件，基线：N 条通过
- [ ] 改动后重跑，原通过项无一变为失败
- 改前/改后对照（摘要或附完整报告）：

## Agent 预核意见（机器可填，可选——非 agent 链路提交可留空）

<!-- 基于事实的独立意见，供 reviewer 对齐判断——不替代人审 -->

- 事实依据（golden 回放对照 / trace 回归结果）：
- 行为差异（改动前后的路由/命中差异摘要）：
- 风险标注（涉及流程步骤 / 需 spot-check 项）：

## 影响面

- 涉及的 skill / 流程步骤：
- 对 CLAUDE.md / README / CONTEXT.md 术语表的同步：已检查 / 不涉及
