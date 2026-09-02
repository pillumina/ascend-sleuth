# proposals/ —— 自演进领域状态

自演进（self-evolving）体系的领域状态目录。机制定义见 `docs/evolution-pipeline.md`（三层闭环/授权/状态机）、`docs/evolution-execution.md`（proposal 契约/验证）、`docs/evolution-run.md`（持续运行）。

## 目录与 git 归属

| 子目录 | 内容 | git 归属 |
|---|---|---|
| `ideas/` | idea 卡（`EV-YYYY-NNN.yaml`）：候选 → 验证 → 合入的完整生命周期记录（**资产**，随 PR 进出，同 knowledge/ 纪律，脱敏后入 git） | ✅ 入 git |
| `sessions/` | 单轮会话状态（进度/token 账本/停止原因）——**运行时** | ❌ gitignore |
| `tasks/` | 长期任务状态（goal/轮次引用/预算账本）——**运行时** | ❌ gitignore |
| `reviews/` | 季度自评报告——**运行时**（稳态结论以策略记忆入 git） | ❌ gitignore |
| `experiments/` | 实验记录（golden 前后对照/台账复测）——**运行时** | ❌ gitignore |

## git 归属原则（对齐仓库 .gitignore 哲学）

- **资产进 git**：idea 卡含最终状态与 decisions，是知识资产（同 knowledge/ 纪律），随 PR 进出；
- **运行时状态不进 git**：sessions/tasks/reviews/experiments 记录逐轮变化的进度与账本（类比 traces/ 与 inbox 草稿），本地留存；稳态结果以报告/采纳项投影入 git。

## schema 校验

- idea 卡 schema 由 `scripts/verify_proposals.py --check` 校验（与 build_index/verify_references 并列）；
- 组件台账在 `metrics/component-tally.yaml`（定义见 evolution-pipeline.md §2）。
