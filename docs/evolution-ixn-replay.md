# 交互型 replay 评测（ixn-replay）

> 机制决议：EV-2026-012。pilot 数据与口径验证：`proposals/reviews/2026-09-04-ixn-replay-pilot.md`（gitignore 运行时件）。本文是评测机制的**设计文档**（第一批落地 = 文档 + `scripts/ixn_replay.py` v1）；评分阈值与筛选标准的校准属蓝图，触发条件见 §8。

## 1. 定位：诊断评测的第三个维度

单发 S2 replay（evolution-pipeline §2.1）只测**检索/内容面**：给全量 issue 背景，看能否路由、命中、到达正确结论。它测不了 diagnose 的**交互面**——信息不足时会不会追问、问的是不是决定性字段、会不会过早下结论。交互型 replay（下称 ixn-replay）补这一维：

| 评测 | 测什么 | 输入 | ground truth | 关联能力 |
|---|---|---|---|---|
| 单发 S2 | 检索/内容/路由 | issue 全量背景 | issue resolution | KB/triage 质量 |
| **ixn-replay** | **交互/追问/充分性** | 分期披露（先给一部分，追问后给下一段） | 维护者真实追问 + 决定性字段（合理下限，非最优） | diagnose 的"信息不足就问"行为 |
| 归因型 replay（兄弟维度，本机制不含实现） | 源码归因深度 | 现象/代码片段 | PR/commit 引用 | 源码级定位能力 |

三者正交：一条 issue 可同时作单发、分期、归因三种评测，各答一个能力面。

## 2. 选样：筛选制，不是全池可用

扩样 10 条（vllm-ascend + verl + MindSpeed-LLM）显示**真·渐进披露约 2–3/10**（#2424/#9769/#9798 型：body 不全或关键信息在评论里、维护者向报告者追问过）；多数 issue 是"详尽型"（body 全，只能人为拆段）或"归因型"（决定性信息来自源码调查，追问无意义）。规则：

1. **渐进披露型优先**：body 信息不足 + 评论含"要版本/环境/日志/复现"类追问 + closed 有 resolution（GitHub 搜索可用 `in:comments "What version"` 等定位）；
2. **详尽型**可经**人为拆段**补入（31KB body 素材充足），但拆段不得让答案过早自明（S0 不含决定性行）；
3. **归因型**不进入本评测，归兄弟维度；
4. 样本库按此**筛选制**入库，持续由 issue 流自然补充（reuse 方案见 §6）。

## 3. 分期构造规则

每样本一个目录 `.ixn-replay/<issue>/`：

- `issue.md` / `comments.md`：gh 拉取的原始线程（含作者，供 gold 提取）；
- `gold.yaml`：标注文件——
  - `held_out: true|false`（该 issue 是否已沉淀为 case；已沉淀 → self_consistent，只作 train/回归，见 §6）；
  - `resolution_ref`：上游 fix PR / commit / closed 依据；
  - `maintainer_questions`：维护者实际追问的字段（合理下限 ground truth）；
  - `decisive_fields`：**改变结论走向的字段**（如 #2424 的 CANN 版本 + env 复测、#9769 的分支一致性）；
  - `resolution_summary`：结论链；
- `stage-0.md … stage-N.md`：分期 feed（S0 = 重构"首报版"，只给标题 + 现象段；后续每段只含该轮真实披露的信息；**S0 与 feed 均不含 decisive_fields 的答案**）。

**切段纪律**：段间信息增量必须真实（来自线程或详 body 的真实内容），不许伪造"用户没说但假装给了"。

## 4. 评分口径（双层 + 防过早）

对每条样本，agent 按诊断协议逐段运行：读 `stage-k.md` → 按 diagnose skill 判断（路由 / 信息充分性 / 追问 / 是否可下结论）→ 写 `stage-k.result.yaml`（含 `questions: [...]`、`sufficient: bool`、`premature_conclusion: bool`）；最终段后写 `conclusion.yaml`。

`scripts/ixn_replay.py --score` 计算：

| 指标 | 定义 | 为什么（pilot 数据） |
|---|---|---|
| **追问召回** | `∪questions` 命中 `maintainer_questions ∪ decisive_fields` 的比例（字段级关键词匹配 + 人工核验） | #2424 命中 5/5 可算 |
| **决定性字段在链** | `decisive_fields ⊆ ∪questions`（**不要求首轮**） | pilot 教训：只问"CANN 版本"会漏 #9769 的"分支一致性"——光首轮命中放走"问不深"的 agent |
| **过早结论率** | 任一中间段 `premature_conclusion: true` 或 `sufficient: true` 时仍下最终结论 | premature 基线（S0 即结论）在此维度低分 → 区分度 |
| **结论一致** | `conclusion.yaml` vs `resolution_summary` | 只作参考分：resolution 常为"workaround + 版本要求 + 后续修复"多阶段，非二元 |

ground truth 三标注：`maintainer_questions` 是**合理下限非最优**（如实标注，不冒充最优标准）；多报告者线程（#2424 型）ground truth **集合化**（不同 CANN 版本根因不同 → 用字段集合而非单答案）；分数字段进报告时带分母（口径纪律，同 metrics.md）。

## 5. 运行协议（agent 侧）

与 s2_replay 同构：harness 只做数据与评分；**每段"诊断 + 追问"由 agent 执行**（读 feed → 走 diagnose skill → 写 result），不自动。顺序：`--prepare`（拉素材 + gold 模板）→ 人/agent 补 gold 与切段 → agent 逐段运行 → `--score` → `--aggregate`。盲测纪律：执行 agent **不看后续 feed 与 gold**（harness 提供分段文件即天然隔离；gold 与 feed 分文件存放）。

## 6. self / held-out 分流与 val 复用

- `held_out: false`（已沉淀为 case，如 #9769）：重放命中即 self_consistent——作 **train/回归**样本（检索与交互回归），**不虚增**外部验证权重（与 S2 同一纪律）；
- `held_out: true`（未沉淀，如 #2424）：作**评测**样本；
- **val 复用**：issue 进入评测集 ≠ 消耗品——纪律是"永不沉淀 + 不把评测反馈喂回知识侧"（扰动不从评测学）；真实 issue 选"与现有 case 族冗余"者入库（牺牲小），辅以 case 派生合成变体（seed 再生，测表面鲁棒性，roadmap M3 为其地基）。上游 issue 流只做自然扩池。

## 7. 成本（pilot 实测量级）

- staged run ≈ 单发 1.5–2.5× token（约 3–6K/条，含 KB 检索）；
- gold 标注 ≈ 3–8 分钟/条（gh 拉线程 + 字段勾选），可半自动；
- 首批样本库 ≥3–5 条（含 held-out 与 self_consistent 分流）即校准阈值。

## 8. 分级与闸门（防过度设计）

| 分级 | 内容 | 何时 |
|---|---|---|
| **第一批（本 PR）** | 设计文档 + `ixn_replay.py` v1（prepare/score/aggregate）+ gold/feed/result 目录规范 + .gitignore + roadmap O8 | 现在（pilot 数据已定口径） |
| 蓝图 | 评分阈值与筛选标准固化、交互面分数进 timeline | 首批真实运行 ≥3 条（含 held-out/self 分流）后按实测校准 |
| 蓝图 | 归因型 replay 工具化（PR 引用为 gold） | 出现归因评测需求 + 样本可溯 PR 引用 |
| 蓝图 | 合成变体生成器（case 派生扰动 + seed） | roadmap M3 落地后 |

## 9. 原则追溯

| 元素 | 原则 |
|---|---|
| 三维评测各测一个能力面、ground truth 合理下限如实标注 | 十（诚实退化） |
| 追问按链评分 + 集合化 | 八（可观测先于改进——评分度量的是可判行为） |
| 筛选制选样、蓝图分级、阈值等实测校准 | 十一（数据触发） |
| harness 只做数据/评分，agent 执行协议、人工核验字段 | 五（建议与决定分离） |
| self_consistent 不虚增、分数带分母 | 十、三 |
