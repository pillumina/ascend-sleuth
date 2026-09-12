---
name: resume-diagnosis
description: >
  续接一个被打断的昇腾诊断 session。读活跃的 traces/*.yaml（每个并发诊断一个文件，含 trace），
  复述上次停在哪一步、排除了哪些 case、当前 active case，等人贴回命令输出后继续。
  诊断被会议/上下文 compact 打断后恢复用。
---

# Resume Diagnosis

诊断不是连续时段——你正跑 check 命令，被拉去开会，回来 agent 上下文已被 compact，诊断链路丢失。

## 流程

**先清反馈债**：扫到的 state 文件里若有 `feedback.outcome: pending` 且 `feedback.case` 非空（上次给了 fix 还没回报结果），先追问“上次 <case-id> 的 fix 应用后解决了吗？（解决 / 没解决 / 部分解决）”——按结果回写该 case 的 confidence（hits/misdiagnoses/last_hit）、trace 记 `{action: feedback, case, outcome}`、把 `feedback.outcome` 从 `pending` 改成实际结果，再进入续接。状态与结局词表见仓库根的 `trace-status.yaml`（**不是** `feedback_pending` 那个旧说法）。

1. 读活跃的 `traces/*.yaml`（每个并发诊断一个文件；模板见 `diagnosis_state.yaml.example`，含 `trace` 数组）。**多个时列出让工程师选续接哪个**
   - **先看有没有配套的人读报告** `traces/<session_id>.report.md`（diagnose 步骤 6 产出）：它把结论、证据链、源码分析、机制图、修复方案、**当前状态与下一步**、**沉淀候选**集中在一处。先读报告能最快恢复"这单在查什么、停在哪、待回报什么"，也直接告诉你**这次能沉淀什么知识**（顶层 `sediment_candidates` 是同一份内容的结构化版本）。读报告**不替代**读 trace：报告的结论要用 trace 的 `reason`/证据核对，两者冲突时以 trace 的现场记录为准并记下冲突。
   - **报告是活件——续接中要顺手修订它**（不是只读）：把新证据并入第 3 节对应强度段、更新第 7 节"当前状态与下一步"、必要时补第 4/5 节、元信息"最后更新"与第 10 节追加一行修订记录；**同一份文件改到底，不另起一份**。规则见 `skills/diagnose/references/report-template.md` 第 2 节。
   - 报告不存在（老 session 或未走完步骤 6）→ 照下面第 2、3 步从 trace 恢复，不视为异常。
2. **恢复完整现场（读 trace 全轨迹，不只元信息）**：
   - 复述：session_id、status、current_step、已排除的 case（`excluded_cases`）、当前 active_case、`last_action`（上次等你做什么）
   - **读 trace 数组恢复对话上下文**：上次问了用户什么、用户已回答了什么、已排除哪些候选及原因（`reason`）——续接是**接着上次的对话继续**，不是从头开始（用户已提供的信息不重复要）
3. **证据确认（跨 agent/session 的关键——agent 无法自证摘要够，必须用户裁决）**：
   - **复述证据清单**：每个 user 事件的 `content`（摘要）+ `evidence`（内联了什么 / 引用了哪些文件 `files` / 来源 `sources` / 已知缺口 `missing`）
   - **问用户："证据齐全吗？有遗漏吗？"**——跨 agent 时新 agent 只见过摘要，无法判断摘要是否等于原文；`missing` 字段自动列出已知缺口。用户确认齐全 → 继续；用户补充 → 更新该 user 事件的 `evidence` 后再继续
   - **文件证据可读**：`evidence.files` 是相对仓库路径（`traces/evidence/<session_id>/`），同工作区可直接读；读不到 → 问用户要
4. **续接必写 trace（与 diagnose 同要求，闭环关键）**：确认续接开始后，往 `traces/<session_id>.yaml` 追加一条 `{role: agent, action: resume, step: <current_step+1>, output: "续接 <session_id>，恢复到 step <N>"}`，**并刷新顶层 `updated_at: <ISO 时间>`**——这是诊断面板"最新活动置顶"的依据（续接 = 该 session 又活跃了）；后续续接中的关键决策同样带 `reason`（与 diagnose 的 trace 要求一致）
5. 等人执行上次要求的命令并贴回输出，从 current_step 继续

## 恢复后的约束（继承 diagnose，不降低）

resume 只负责**恢复现场**——恢复后继续的是 `/diagnose` 的完整诊断循环（步骤 2-6），**不是更松的模式**。续接中以下 diagnose 约束**同样生效**（完整定义以 `skills/diagnose/SKILL.md` 为准，此处只列续接时最易被丢失的）：

- **severity 闸门**：`data-loss-risk` 不给 fix，先停/保留现场/通知 owner；`service-affecting` 标 `fix_side_effects`。
- **命中输出格式 + 强度标注**：结构化推理链 + `已验证/推测/数据` + confidence 校准，别甩一句 fix。
- **经验证后给 fix**：对照已提供信息验证 diagnosis checks，缺就问；`fix_on_mismatch` 带 rollback。
- **版本软匹配**：compat 不符只降 confidence，不硬排除。
- **证据落盘铁律**：用户证据完整落 `traces/evidence/<session_id>/`，不写摘要/指纹；每次写 trace 刷新顶层 `updated_at`。
- **深度排查**：Tier 3 / 源码分析一律走 `scripts/src_fetch.py`（复用、不自行 clone）。
- **误诊归因**：反馈 not_resolved/partial → 读 trace 判 case_error/execution_error。
- **连续失败 ≤2**：两次未解决转人工，不连续试第三个。
- **trace 边界**：续接后同样别把流程/设计讨论写进本 trace（走 `_evnote.md`）。
- **检索面**：若续接中需重新路由/加载（如 active_case 丢失），照 diagnose 的 tier1 / 两阶段 tier2 / 2.5 reference 流程执行——那是续接中必要的重新定位，不是"回到起点"。

> 单一数据源纪律：上表是"易丢项清单"，**权威定义仍在 diagnose**；两者冲突时以 diagnose 为准，并在 diagnose 同步修正。

## 不要做

- 不要从头重新收集症状——state 文件里都有
- 如果 `session_id` 和当前不匹配，提示"该问题可能已被其他人接手——是否继续？"（并发检测，脆弱机制，只作提示不硬阻塞）
- **不要在这份 trace 里记录本 resume 期间发生的流程/设计讨论**（与 diagnose 的"trace 边界"一致——那是自演进信号，走 EV card / 自演进通道，不污染本问题的诊断 trace）。`resume` 事件只承载诊断状态（恢复到哪步、待办什么），不掺流程改进内容
- 续接中若需源码分析，**用 `scripts/src_fetch.py <repo> --ref <tag>`**（复用 `src-code/<org>/<repo>/` 本地缓存，同版本不重复 clone，`git -C <path> log -1` 核对版本；`--list` 看已知仓库与 host），不自行决定 clone 到哪、不重复拉取

## 状态文件生命周期

case 标 `resolved`/`escalated` 时**留在 `traces/` 原位**（用 `status` 字段标记闭环，**不挪去 `postmortems/history/`**——诊断面板与 `ascend_trace_status` 都只读 `traces/`，挪走会看不到/打不开）。`traces/` 持有全部诊断记录（进行中 + 已闭环），**判"可续接"看 `status`**：只把 `in_progress`/`feedback_pending` 的当活跃可续接；`resolved`/`escalated` 的只作参考不可续接（不再提示"续接"）。**trace 历史不删**——它是路由准确率、执行保真度等指标的数据源（见 docs/metrics.md）。`postmortems/` 只放知识 postmortem 工件（.md，Tier 3），不是 trace 的归档处（trace 是 gitignored 机密记录）。

**与诊断面板的闭环**：resume 是 trace 的写入方之一——续接追加 `resume` 事件 + 刷新 `updated_at`，使该 session 在面板"更新 X 前"重置、置顶。面板"继续诊断"按钮 → 复制指令 → 本 skill 触发 → 续接写 trace → 面板刷新可见活动。任一环缺失（如续接不写 trace）闭环断，面板不反映续接。
