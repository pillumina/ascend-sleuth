# research/ —— 本地调研物料（不进机制文档体系）

放什么：为设计决策做的外部文献调研（RSI / 自演化 / skill / 记忆 / 治理等切片）。
不放什么：机制文档（那些进 `docs/`，且必须在 `docs/_manifest.yaml` 登记，否则 `build_docs_index.py --check` 红）。

三条纪律：

1. **这里不是权威处。** 物料本身没有约束力；结论要生效，得转成 EV 卡、ADR 或 `docs/` 里的机制条款。
2. **不登记进 `docs/_manifest.yaml`**，否则会被生成器当成机制文档抄进 README 目录。
3. **当前未进 git**（`git status` 显示为未跟踪）。要让它从 `git status` 消失，需在 `.gitignore` 加一行 `research/`——那是 tracked 改动，按 `docs/git-workflow.md` 走 worktree，别在主检出直接改。

物料清单：

| 文件 | 切片 | 核验日期 |
|---|---|---|
| `lit-review-agent-memory-2026.md` | Agent memory / 经验复用 / 上下文演化（2026-01 → 2026-09 + 2025 锚点） | 2026-09-17 |
| `lit-review-rsi-2026-09.md` | RSI / 自演化机制 / skill 库准入 / 自演化的治理与失效模式 | 2026-09-17 |
