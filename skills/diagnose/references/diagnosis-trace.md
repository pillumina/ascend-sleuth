# Diagnosis Trace（trace 写作细节展开）

`/diagnose` 的 SKILL.md「每步必写 trace」写主干（事件结构/证据落盘铁律/时间戳/trace 边界），这里展开**细节**（词表、外部事实落盘、agent 事件两层、反馈闭环词表）。执行时按需加载。

## KNOWN_ACTIONS 词表（与 `scripts/trace_metrics.py` 一致，新增 action 必须两处同步）

trace 的 agent 事件 `action` 必须落在词表内（词表外 action 会被 `trace_metrics.py` 报为纪律违规）：

```
triage | load_index | quickly_check | load_full | run_check | hit | miss | tier3
| feedback | reference_lookup | triage_semantic | source_analysis | attribution | resume
```

user 事件无 `action`，不参与词表检查。**新增 action 时同步改 `trace_metrics.py` 的 `KNOWN_ACTIONS` 与本文**（单一数据源纪律）。

## 外部事实获取落盘（agent 侧，与 `user.evidence` 分开）

诊断中为**形成结论**而做的外部获取——`web_search` / `web_fetch` / `gh api` / `git clone` / 源码 `grep` 读——**记到 agent 事件**（`source_analysis` 的 `tool_calls`，或 `reference_lookup`）。

- 每条 = `[<工具/来源>: <该来源确立的关键事实 或 失败原因>]`，**记"用了哪个事实"而非"抓了整页"**（token 纪律）。
- 失败的源也记（"哪源不可达/404"是可复用教训，备选源清单由此沉淀）。
- 判据：这条外部事实是否**进入了本次诊断结论的推理链**——是 → 记；纯背景、未用 → 不必记。
- **别与 `user.evidence` 混**：外部是 agent 查到的、可再查证（记来源+事实即可）；用户**提供**的现场证据是跨 agent 必须自包含的（走 `inline`/`file`）。

## agent 事件分两层（output 给用户 / reason 记决策依据，缺一不可）

- `output`：给用户看的内容（可精简）——透明性的呈现层。
- `reason`：**决策依据/推理过程**（回放、误诊归因、知识沉淀的证据）——**关键决策必写**：triage 路由（为什么命中此分支）、quickly_check 排除（比对了哪些候选、为何排除）、hit/miss（证据链、比对结果）、reference 甄别（为何部分适用/不适用）、根因判断（证据→结论）。**output 和 reason 分开**：结论简洁，推理要完整。

## 反馈闭环词表

反馈确认后，顶层 `feedback: {case, outcome, confirmed_at}` 要填——`status=resolved 且 feedback.outcome=resolved` 是该 trace 升格为 fixture（强断言基准）的资格条件（`scripts/replay_trace.py --emit-fixtures` 只看这种）。

## 词表同步纪律

`trace` 的 action 词表与 `scripts/trace_metrics.py` 的 `KNOWN_ACTIONS` 保持一致；新增 action 必须两处同步（本文 + 脚本）。user 事件无 action，不参与词表检查。
