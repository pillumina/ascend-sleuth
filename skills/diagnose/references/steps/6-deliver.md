# 步骤 6：产出

> **何时读**：命中候选要给结论、或深度排查出结果收尾时（必读）。
> **完成判据**：`status` / `summary` / 报告（全路）/ `feedback` / `severity` / `fix_emitted` / `sediment_candidates` 齐；有日志材料时 `failure_process` 已写（无日志不写）；trace 收尾字段（`ended_at` / `stop_reason`）写齐。
> **本步产出**：定位报告、`feedback` 债与回报指令、`sediment_candidates`、收尾后的 trace。

- `status: resolved`（**含义是"已收尾"，不是"已修好"**：根因定位明确、fix 或明确的下一步已给出）`| escalated | unknown`；fix 是否在用户环境生效不写 status，写 `feedback.outcome`（词表见 `trace-status.yaml`；命中单由给 fix 时挂的 `pending` 起，有人回报后再追加 `feedback` 事件改值）
- 写 `traces/<session_id>.yaml`（每并发诊断一文件，含完整 trace），status 到收尾态后留在 `traces/`（gitignored）；沉淀状态写 `sedimented`
- **写人读定位报告 `traces/<session_id>.report.md`**（**全路**产出，**快路**不产；结构与行文见 `../report-template.md`）：trace 管过程可回放，对话输出管现场能行动，报告管"结论可复述 + 证据可核对 + 沉淀可执行"。**一律按深度排查规格写**——读者要据此自行判断对错并从中学机制，不因已知根因而缩水。写完过一遍 `python3 scripts/report_lint.py <报告>`（结构自检，非 CI 门禁）。
- **报告是活件，不是一次性交付物**：它必须跟着诊断走，否则第一次交付之后就开始说谎。同一份文件改到底（不另起 `report-v2`），每次修订更新元信息的"最后更新"、在第 10 节追加一行修订记录，旧结论被推翻时**降级标注而不是删掉**（读者要看到判断怎么变的）。触发点与各改哪节见 `../report-template.md` 第 2 节；本步骤最常见的两处是 **用户回报 fix 结果**（改 1/6/7/8 节）与 **resume 续接**（改 7/3 节）。
- **改当前值走 content 写入口，并同步报告**：`summary` 与 `incident_env` / `incident_timeline` / `failure_process` / `upstream_timeline` 用 `python3 scripts/trace_transition.py <sid> --field content --content-file <json> --by agent --json` 写；写入口按 id 比对自动落一条 `revisions`（`before` / `after` / `reason` / `hashes`），手改 YAML 会被修订一致性检查报错。报告对应小节与第 10 节同一次改完，两侧不能一边新一边旧。
- **顶层写 `severity` 与 `fix_emitted`（收尾时各写一次）**：`severity` 取 `benign` / `service-affecting` / `data-loss-risk`（命中单取命中 case 的 `severity`；未命中按根因判——会丢数据的一律 `data-loss-risk`）；`fix_emitted` 写 `true` / `false`，表示本次是否给出了可执行的修复或规避方案（等上游修复、只定位到根因写 `false`）。两个字段是面板列表唯一能表达"这单该不该先停""有没有可执行修复"的地方；不写，列表上这类单与 benign 的单长得一样，读的人只能点开才发现要停训练。
- **写 `sediment_candidates`**（顶层字段，与报告第 8 节同源，**全路**产出）：把"这单能沉淀什么"结构化——报告给人读，trace 给机器与 resume 读；trace 记一条 `{action: report, report_file, sediment_candidates: N}` 事件。
- **Tier-2 命中**：常规 postmortem 草稿
- **Tier-2 未命中但最终解决**：postmortem 含一段 agent 起草的候选 case（初始分数由 `verification` × `investigation_quality` 决定的冷启动先验给出，通常偏低），交 groom 验证。人的角色从“结构化”上移到“验证草案”。
- **结果反馈：挂账 + 回报指令，不在这里当场追问**：给完 fix 那一刻，工程师还没应用、也没跑验证命令，此时问"解决了吗"只会得到一句"还没试"——这一问把债的产生点当成清偿点。正确顺序是：
  1. **立刻写**：`feedback: {case: <真实 case id 或占位串 pending-investigation>, outcome: pending}` + `feedback_pending_since: <当天日期>`（顶层字段，定义见 `diagnosis_state.yaml.example` 与 `trace-status.yaml`；**不再写 `feedback_pending`**，那是面板口头沿用的旧说法，脚本读不到）。写账龄是为了让这笔债可排序、可催——没有它，"挂了两周的反馈"与"昨天刚挂的"在面板上一样。
  2. **对话里给一条可复制的回报指令**，三选一、话术照抄可用：「应用后解决了吗？回我一句就行——`解决` / `没解决` / `部分解决`」。
  3. **有人回来回报时才记**：trace 记 `{action: feedback, case, outcome: resolved|not_resolved|partial}` 并清 `pending`；计数由知识整理收尾的结算步骤（`scripts/settle_trace_feedback.py`）落进条目使用记录，**不写回 case 文件**。not_resolved / partial 自动进入误诊归因（见文末）。
- **这笔债谁追**：`/skill:resume-diagnosis` 续那一单时问得其所；`/diagnose` **不在新诊断的开屏逐单念**（新问题的第一屏只服务新问题，积压时那是审讯）；面板待办面承载其余（谁欠、哪一单、欠多久），人去清。
- **`case` 按是否命中填两种之一**：命中 → **真实 case id**（回报后结算到它头上）；未命中但给了建议 → 占位串 `pending-investigation`，表示"**没有 case 可结算**"——后续追问这类单时问的是"上次要求的材料拿到了吗"，不是"那个 case 的 fix 生效了吗"。反馈捕获是学习环的吞吐上限，靠文件标记而非记性。
- **沉淀已含在本步骤**：命中=常规 postmortem、未命中=含候选 case 的 postmortem，已生成。只有非 /diagnose 定位的（Kimi/手工、或没配 session-end hook 导致没生成）才需 `/skill:to-postmortem` 手动沉淀。

### 命中时的输出格式（4 段必需 + 2 个按需块）

> **判读标准**：输出的段数与长度应与**问题复杂度相关**。根因明确、fix 是单个开关时，四段写完即可。
> **一件事只说一遍**——同一信息在"结论先行"与后续分节各写一次就是冗余（盲评对照里这是最被诟病的一点）。
> **一段只说一件事**：一段不超过 3 句，同一层级的并列信息用列表列，不串进一句里。现场工程师要在三十秒内决定动手，一堵墙他读不完。

**行文**：对话输出是给人读的，按 `docs/spec/writing-norms.md` 写（可选论证层，不影响本 skill 执行）；本面的定制条款见该文件 §3 的「诊断对话输出」一行。写 trace 的字段时另见 `../diagnosis-trace.md` 的「行文要求」。

**必需四段**（顺序即优先级）：

1. **结论先行**——一句话：现象 + 根因 + 改哪个开关（无内部词表）。
2. **依据链**——每条结论 → 支撑它的证据/检查结果，**逐条标强度**：`已验证`（本轮实际执行过）/`推测`（依赖推断、未直接验证）/`数据`（历史积累，非本轮判断）。
   命中 case 时，把「命中 case / 路由依据 / 排除链 / 匹配症状 / 版本匹配 / 历史表现」作为**本段的子清单**列出，不另起一段：
   - **命中 case 的 id 与分数必写**：`<CASE-ID>`（索引里的 score `<score>`）——它是工程师回溯知识库、以及反馈回收的锚点，**不要省**。历史解决 / 误诊计数不住在 case 里，要看就去条目使用记录的生成物（`metrics/entry-activity/<部署>.yaml`）按 id 取；
   - 排除链要给出检查明细；材料没给的如实标"未提供"，**不写"已验证"**；
   - 版本匹配按软匹配规则（compat 不符只降排序分数）；历史表现标为「数据」。
3. **修复方案**——精确命令或 diff 要点 + `rollback` + side-effect（需重启 / 需升级驱动等）+ **应用后如何验证生效**。
   `fix_type` 决定呈现：`env-var` / `config-change` 直接给可执行命令；`code-patch` 给改动文件 + diff 要点（**不可直接执行**）；`pending-investigation` 给排查建议。
   **前提未验证时把核验写成修复的第 0 步**（例：case 的 compat 是 `hdk <26.1` 而客户没报 HDK 版本 → 第 0 步先 `npu-smi info` 核版本，前提不成立就转 plan B），不要带着未验证的前提直接开方。
4. **可靠度与残余风险**——**分数分档讲明**（索引里那条候选的 score）：`>0.8` 高可信直接应用、`0.5–0.8` 中可信（应用同时备 plan B）、`<0.5` 仅作提示重点靠手动排查。
   另给：哪些是推测、**触发/不触发面**（什么条件用得上这条结论）、follow-up。

**两个按需块**（不要默认展开）：

- **机制原理**——源码/流程层面的因果链。**展开就讲完整**（触发前置条件 → 每步的"为什么" → 因果链完整），不得压成一句；命中且根因已由依据链说清时不展开。
  去 AI 味 ≠ 删机制：机制与可核对性必须保留，只把内部词表/交叉引用翻译成因果白话。
- **时间线**——按日志时间排列的可观察事实，只放可观察项、不夹判断；仅当排查跨多轮、或时间先后本身是判据时展开。
