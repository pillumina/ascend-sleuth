---
name: resume-diagnosis
description: >
  续接一个被打断的昇腾诊断 session。读活跃的 traces/*.yaml（每个并发诊断一个文件，含 trace），
  复述上次停在哪一步、排除了哪些 case、当前 active case，等人贴回命令输出后继续。
  诊断被会议/上下文 compact 打断后恢复用。
disable-model-invocation: true
---

# Resume Diagnosis

诊断不是连续时段——你正跑 check 命令，被拉去开会，回来 agent 上下文已被 compact，诊断链路丢失。

## 流程

**先清反馈债**：扫到的 state 文件里若有 `feedback_pending: <case-id>`（上次给了 fix 还没回报结果），先追问“上次 <case-id> 的 fix 应用后解决了吗？（解决 / 没解决 / 部分解决）”——按结果回写该 case 的 confidence（hits/misdiagnoses/last_hit）、trace 记 `{action: feedback, case, outcome}`、清掉标记，再进入续接。

1. 读活跃的 `traces/*.yaml`（每个并发诊断一个文件；模板见 `diagnosis_state.yaml.example`，含 `trace` 数组）。**多个时列出让工程师选续接哪个**
2. **恢复完整现场（读 trace 全轨迹，不只元信息）**：
   - 复述：session_id、status、current_step、已排除的 case（`excluded_cases`）、当前 active_case、`last_action`（上次等你做什么）
   - **读 trace 数组恢复对话上下文**：上次问了用户什么、用户已回答了什么、已排除哪些候选及原因（`reason`）——续接是**接着上次的对话继续**，不是从头开始（用户已提供的信息不重复要）
3. **证据确认（跨 agent/session 的关键——agent 无法自证摘要够，必须用户裁决）**：
   - **复述证据清单**：每个 user 事件的 `content`（摘要）+ `evidence`（内联了什么 / 引用了哪些文件 `files` / 来源 `sources` / 已知缺口 `missing`）
   - **问用户："证据齐全吗？有遗漏吗？"**——跨 agent 时新 agent 只见过摘要，无法判断摘要是否等于原文；`missing` 字段自动列出已知缺口。用户确认齐全 → 继续；用户补充 → 更新该 user 事件的 `evidence` 后再继续
   - **文件证据可读**：`evidence.files` 是相对仓库路径（`traces/evidence/<session_id>/`），同工作区可直接读；读不到 → 问用户要
4. **续接必写 trace（与 diagnose 同要求，闭环关键）**：确认续接开始后，往 `traces/<session_id>.yaml` 追加一条 `{role: agent, action: resume, step: <current_step+1>, output: "续接 <session_id>，恢复到 step <N>"}`，**并刷新顶层 `updated_at: <ISO 时间>`**——这是诊断面板"最新活动置顶"的依据（续接 = 该 session 又活跃了）；后续续接中的关键决策同样带 `reason`（与 diagnose 的 trace 要求一致）
5. 等人执行上次要求的命令并贴回输出，从 current_step 继续

## 不要做

- 不要从头重新收集症状——state 文件里都有
- 如果 `session_id` 和当前不匹配，提示"该问题可能已被其他人接手——是否继续？"（并发检测，脆弱机制，只作提示不硬阻塞）

## 状态文件生命周期

case 标 `resolved`/`escalated` 时，把 state 文件移入 `postmortems/history/`。
active 目录只留进行中 session。**trace 历史不删**——它是路由准确率、执行保真度等指标的数据源（见 docs/metrics.md）。

**与诊断面板的闭环**：resume 是 trace 的写入方之一——续接追加 `resume` 事件 + 刷新 `updated_at`，使该 session 在面板"更新 X 前"重置、置顶。面板"继续诊断"按钮 → 复制指令 → 本 skill 触发 → 续接写 trace → 面板刷新可见活动。任一环缺失（如续接不写 trace）闭环断，面板不反映续接。
