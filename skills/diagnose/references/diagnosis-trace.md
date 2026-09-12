# Diagnosis Trace（trace 写作细节展开）

`/diagnose` 的 SKILL.md「每步必写 trace」写主干（事件结构/证据落盘铁律/时间戳/trace 边界），这里展开**细节**（词表、外部事实落盘、agent 事件两层、反馈闭环词表）。执行时按需加载。

## KNOWN_ACTIONS 词表（与 `scripts/trace_metrics.py` 一致，新增 action 必须两处同步）

trace 的 agent 事件 `action` 必须落在词表内（词表外 action 会被 `trace_metrics.py` 报为纪律违规）：

```
triage | load_index | quickly_check | load_full | run_check | hit | miss | tier3
| feedback | reference_lookup | triage_semantic | source_analysis | attribution | resume
| procedure_follow | report
```

user 事件无 `action`，不参与词表检查。**新增 action 时同步改 `trace_metrics.py` 的 `KNOWN_ACTIONS` 与本文**（单一数据源纪律）。

### `report` 事件（人读定位报告产出，步骤 6 必写一条）

报告是 diagnose 的三份产出之一（另两份是 trace 与对话输出）：trace 管过程可回放，对话输出管现场能行动，
报告管"结论可复述 + 证据可核对 + 沉淀可执行"。结构与行文见 `report-template.md`（本目录）。产出时记：

```yaml
- {step: 6, action: report, report_file: "<session_id>.report.md",
   sediment_candidates: 3, output: "产出报告（9 节 + N 张 mermaid 图）",
   reason: "为什么写报告；命中型也要写清机制，不因已知根因缩水"}
```

- `report_file`：文件名（与 trace 同目录、同名不同后缀），面板据此提供"打开报告"入口；
- `sediment_candidates`：候选条数（内容见顶层字段，别在事件里重复正文）。

**报告是活件**：报告后来被修订时（resume 续接、用户回报 fix 结果、新证据推翻原结论、沉淀动作发生），
**再记一条** `{action: report, step: <当前步>, report_file, output: "修订了什么（哪几节）", reason: "触发来源"}`——
step 递增即可。没有这条，"报告被维护过"就不可观测（面板与指标都只能看到初稿）。

### 顶层 `sediment_candidates`（结构化沉淀候选）

报告第 8 节与 trace 的这个字段是**同一份内容**的两种呈现：报告给人读，trace 给机器与 resume 读——
resume 时不必重读报告全文即可知道"这单能沉淀什么"。每条四项：

```yaml
sediment_candidates:
  - kind: reference          # case | reference | triage
    summary: 一句话说清可复用的结构事实（跨事故稳定，不绑定本次个案）
    evidence: 本轮哪条证据支撑它（trace 事件 / 文件 / issue）
    suggested_skill: to-reference   # to-postmortem | to-reference | knowledge-groom
    status: proposed         # drafted（本轮已起草）| proposed（建议做，未做）
```

判"能不能当 reference"的口径：换个事故、换个客户还成立吗？只对本次个案成立的内容属于 case（走 to-postmortem）。

### `procedure_follow` 事件（方法缺口消费点）

流程闸门命中后，按流程执行时记一条：

```yaml
- {step: N, action: procedure_follow, ref_id: msprof-comm-bottleneck-thresholds,
   steps_executed: [1, 2, 3], branch_taken: 慢卡, gap: null}
```

- `ref_id`：本轮加载并按之执行的流程词条（对应一条 `reference_lookup` 事件，purpose: `procedure`）；
- `steps_executed`：实际走完的 step 序号；**跳步要写理由**（`skipped` 字段，如 `{2: "本导出无计算列"}`）；
- `branch_taken`：流程给出分流时的实际分支（如"慢卡" / "链路异常"）；无分流写 `null`；
- `gap`：流程某步所需数据不在手上时如实记缺口（缺什么、怎么补），**不臆断分支结论**；
- `conflict`：流程的前提/分支与现场证据**明确矛盾**时记该矛盾（如"流程假设可采到逐卡计算耗时，本导出无此列"）——
  这是"以证据为准、换一条或转深度排查"的依据；无冲突写 `null`。**记冲突不是记叛逆**：流程被判据推翻是正常结果，
  写下来才能让流程层知道自己哪一步在这个现场不成立。

**流程走完但没解决**：在 `attribution` 事件里带 `component: reference:<ref_id>`（verdict 照旧按
case 错 / 执行错判）——让 `component_tally.py` 能聚合出"被跟随后仍失败"的流程簇。否则流程层只有加载率、
没有失败率（加载率是活动度量，加了触发点必然接近 100%），错流程会被稳定注入而无人察觉。

这组字段是"流程是否被真正使用、用得对不对"的唯一数据源——没有它，流程层不可观测（原则八），
也就无法判断某条流程该留、该改、该摘。

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
