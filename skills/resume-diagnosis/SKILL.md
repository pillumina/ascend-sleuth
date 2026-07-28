---
name: resume-diagnosis
description: >
  续接一个被打断的昇腾诊断 session。读 diagnosis_state.yaml（含 trace），
  复述上次停在哪一步、排除了哪些 case、当前 active case，等人贴回命令输出后继续。
  诊断被会议/上下文 compact 打断后恢复用。
disable-model-invocation: true
---

# Resume Diagnosis

诊断不是连续时段——你正跑 check 命令，被拉去开会，回来 agent 上下文已被 compact，诊断链路丢失。

## 流程

1. 读 `diagnosis_state.yaml`（模板见 `diagnosis_state.yaml.example`，含 `trace` 数组）
2. 复述：
   - session_id、status、current_step
   - 已排除的 case（`excluded_cases`）
   - 当前 active_case
   - `last_action`（上次等你做什么）
3. 等人执行上次要求的命令并贴回输出，从 current_step 继续

## 不要做

- 不要从头重新收集症状——state 文件里都有
- 如果 `session_id` 和当前不匹配，提示"该问题可能已被其他人接手——是否继续？"（并发检测，脆弱机制，只作提示不硬阻塞）

## 状态文件生命周期

case 标 `resolved`/`escalated` 时，把 state 文件移入 `postmortems/history/`。
active 目录只留进行中 session。**trace 历史不删**——它是路由准确率、执行保真度等指标的数据源（见 docs/metrics.md）。
