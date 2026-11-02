# proposals/ —— 自演进领域状态

自演进（self-evolving）体系的领域状态目录。机制定义见 `docs/mechanism/pipeline.md`（三层闭环/授权/状态机）、`docs/mechanism/execution.md`（proposal 契约/验证）、`docs/mechanism/run.md`（持续运行）。

## 目录与 git 归属

| 子目录 | 内容 | git 归属 |
|---|---|---|
| `ideas/` | idea 卡（`EV-YYYY-NNN.yaml`）：候选 → 验证 → 合入的完整生命周期记录（**资产**，随 PR 进出，同 knowledge/ 纪律，脱敏后入 git） | ✅ 入 git |
| `sessions/` | 单轮会话状态（进度/token 账本/停止原因）——**运行时** | ❌ gitignore |
| `tasks/` | 长期任务状态（goal/轮次引用/预算账本）——**运行时** | ❌ gitignore |
| `reviews/` | 季度自评报告——**运行时**（稳态结论以策略记忆入 git） | ❌ gitignore |
| `experiments/` | 实验记录（golden 前后对照/归因事件复测）——**运行时** | ❌ gitignore |

## git 归属原则（对齐仓库 .gitignore 哲学）

- **资产进 git**：idea 卡含最终状态与 decisions，是知识资产（同 knowledge/ 纪律），随 PR 进出；
- **运行时状态不进 git**：sessions/tasks/reviews/experiments 记录逐轮变化的进度与账本（类比 traces/ 与 inbox 草稿），本地留存；稳态结果以报告/采纳项投影入 git。

## 方案文档怎么写（`proposals/*.md`）

一份方案要能让没参加讨论的人决定**做不做**。写四件事，各占一段：

- **要解决什么问题**：现象加读数，写清谁在什么场景下被卡住。
- **选哪条路**：候选路径、选这条放弃什么、可能坏在哪。
- **怎么算完成**：可复跑的判据，一条命令加期望。
- **不做会怎样**：代价落到具体的人或流程上，不写"风险可控"。

讨论过程、逐条论证与来回追问留在会话，不搬进文档。词句层的规矩按 `docs/spec/writing-norms.md`。

## schema 校验

- idea 卡 schema 由 `scripts/verify_proposals.py --check` 校验（与 build_index/verify_references 并列）——**由 kb-checks 的 `proposal-audit` job 在 CI 执行**（`proposals/**` 在触发路径里；2026-09-10 前只是纸面承诺）。除结构外还校验**生命周期完整性**：终态卡缺 decision / validated 缺 `actual_cost.tokens` / 在实验卡执行完未推进（status lag）/ 在实验超 14 天未闭合（僵尸卡）/ `source_signals` 缺 `trajectory` 出处；
- **状态与面板同口径**：`verify_proposals` 报的缺口与 `scripts/ev_board_data.py` 的 `audit_gaps` 是同一件事（CI 硬门 + 面板提示两处看同一批卡，不各报各的）；
- 归因事件在 `traces/`（diagnose attribution + S2 候选），按需聚合见 `scripts/component_tally.py`（无常驻表，定义见 docs/mechanism/pipeline.md §2）。
