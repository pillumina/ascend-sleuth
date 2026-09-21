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

### `triage` 事件（Tier-1 路由决策）

字段 `{action: triage, routed, category, output, reason}`：

- **`routed` 必写**，值是被路由到的 namespace 列表（按 `search_namespaces` 的顺序，如 `["inference/vllm-ascend", "common"]`）。
- **没命中任何分支也要写 `routed: []`，不要省略这个字段**——省略会被结算读成「未记录」，而「未记录」与「没错」在数据上同形（路由准确率的分母与 router 错例池都取这个字段）。
- 命中分支后走了语义兜底，另记 `triage_semantic`（带 `namespace` + `category`）：它同样计入路由准确率，**不要只留 triage 而不带 routed**。
- 完全无法分类时写 `routed: []`，并在 `reason` 里写明「无可用 namespace（原因）」，然后按流程走 Tier 3。

### `reference_lookup` 事件（四触发点 + 三态）

先验层的四个触发点各记一条，字段 `{action, purpose, outcome, ref_id, platform, output, reason}`：

| `purpose` | 触发点（时点） | `ref_id` |
|---|---|---|
| `collect` | 数据缺口：采集面（**步骤 3 候选加载后**，精度 / 性能单必留一条） | 采集面词条 id，或 `null` |
| `signature` | 键触发：证据里的错误码 / 故障签名 / 环境变量名 / 版本组合（步骤 2 收尾，**先于候选加载**） | 命中的族表 / 词条 id |
| `background` \| `fix` | 判断缺口：候选命中后的背景与修复依据（步骤 3 阶段 2.5） | 读到的词条 id，或 `null` |
| `procedure` | 方法缺口：候选全未命中后的流程取用（步骤 5，与 `procedure_follow` 成对） | 流程词条 id |

`outcome` 三态（词表与 `scripts/trace_metrics.py` 的 `KNOWN_OUTCOMES` 一致）：

- `hit`：查到并用于本次推理（`output` 记"用了哪个事实"，不是"读了整页"）；
- `miss`：查了，但没有相关词条（`reason` 写清按什么键查的、为何无关）——它记的是**知识库的覆盖缺口**；
- `skipped`：**没有查**（`reason` 必写为什么）。两种常见情形：本触发点不在本轮路径上（如候选全未命中时的 2.5）、证据里没有可检索键（框架自定义断言文本、Python traceback、业务日志）。

**为什么要有 `skipped`**：不查不留痕时，"查了没命中"与"根本没查"在数据上完全同形——消费率无法归因，也就分不清该改知识库（覆盖缺口）还是改流程（执行错）。`skipped` 不计入 reference 引用次数（那是"查过"的口径）。

### `report` 事件（人读定位报告产出，全路步骤 6 必写一条）

**快路不写这一条**，也不写顶层 `report_file`：那条路径按开屏所选范围不产报告（面板与导出脚本对没有报告的 session 有同名兜底，不会报缺件）。**不产报告不等于不落证据**——`user` 事件的 `evidence` 落盘与 agent 事件的 `reason` 照旧必写：没有报告时，trace 就是这单唯一的回放依据，缺了它续接与误诊归因都没有现场。

报告是 diagnose 的三份产出之一（另两份是 trace 与对话输出）：trace 管过程可回放，对话输出管现场能行动，
报告管"结论可复述 + 证据可核对 + 沉淀可执行"。结构与行文见 `report-template.md`（本目录）。产出时记：

```yaml
- {step: 6, action: report, report_file: "<session_id>.report.md",
   sediment_candidates: 3, output: "产出报告（9 节 + N 张 mermaid 图）",
   reason: "为什么写报告；命中型也要写清机制，不因已知根因缩水"}
```

- `report_file`：文件名（与 trace 同目录、同名不同后缀），面板据此提供"打开报告"入口。
  **只写文件名，别写 `traces/` 前缀或绝对路径**——面板统一在 `traces/` 下拼路径，写 `traces/<名>.md`
  会拼成 `traces/traces/<名>.md`（读与打开都对不上；面板现在会归一，但别依赖它兜底）；
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

## `user` 事件的 `evidence.quotes`（原件引文回验）

**只在工程师交了原件时填**。原件 = agent 之外、能按路径重新打开并在第 N 行读到那句话的文件：日志文件、解开的日志包、交接包里的原件。对话里粘贴的片段不是原件。

```yaml
- role: user
  step: 1
  content: 客户日志包与 plog 路径
  evidence:
    files: [plog/host-10.0.0.1/device-3.log]
    quotes:
      - {file: plog/host-10.0.0.1/device-3.log, line: 1234, quote: "[ERROR:DEV] device 3 ecc error ..."}
```

- `file` 用**相对日志包根目录**的路径（正斜杠，不带 `./`）——接手的人要按这个路径在原包里定位；`line` 是原件里的行号（`grep -n` 或脚本输出给的那个数）；`quote` 从原件**逐字复制**，不转述。
- **长行截断要显式标 `...`**：核对时按 `...` 切成若干段、要求各段**按顺序**出现在该行内。不带 `...` 的引文只认逐字相等。这样既不用贴整行，也不给"看起来像就能过"留口子——引文里混进原件没有的内容会被判不一致。
- **粘贴件不填 `quotes`**：没有原件就是没有，在 `evidence.inline` 里存原文、写一句"无原件可核"即可。**它不因此降级，也不主张"已验证"**。
- **核对与降级**：`python3 scripts/verify_evidence.py <trace> --root <原件根>` 逐条重读原件比对，退出非零表示至少一条不能用。按结果处理：

  | 判定 | 含义 | 处理 |
  |---|---|---|
  | `PASS` | 与原件一致（含显式截断按序命中） | 该结论可标"已验证" |
  | `MISMATCH` | 读得到但对不上 | 该结论降级为推测，或回步骤 4 重新取证，报告写明原因 |
  | `NOFILE` / `NOLINE` | 文件不在 / 行号非法或越界 | 同上——路径与行号也是引文的一部分，对不上就不能用 |
  | `READ-ERROR` | 文件解不开（utf-8 与 gbk 都不行） | 编码问题，不判成"引文错"；退回让人确认编码后再核 |
  | `NO-ORIGIN` | 没有原件 | 不进判定，也不写进报告读者视野 |

- **判据只有两种**：逐字相等（空白归一化），或显式截断的分段按序命中。**不做大小写、全半角、标点的规整**——规整越多，"核对过"越接近"看起来像"。
- **为什么要有这一层**：报告要求"每条结论都指回证据"，但"指回去了"和"引文与原件一致"是两件事。后者原先只是人审项（`report_lint.py` 只查结构：必需节、字段配对、路径存在），改写引文与行号漂移都不报错。

## 外部事实获取落盘（agent 侧，与 `user.evidence` 分开）

诊断中为**形成结论**而做的外部获取——`web_search` / `web_fetch` / `gh api` / `git clone` / 源码 `grep` 读——**记到 agent 事件**（`source_analysis` 的 `tool_calls`，或 `reference_lookup`）。

- 每条 = `[<工具/来源>: <该来源确立的关键事实 或 失败原因>]`，**记"用了哪个事实"而非"抓了整页"**（token 纪律）。
- 失败的源也记（"哪源不可达/404"是可复用教训，备选源清单由此沉淀）。
- 判据：这条外部事实是否**进入了本次诊断结论的推理链**——是 → 记；纯背景、未用 → 不必记。
- **别与 `user.evidence` 混**：外部是 agent 查到的、可再查证（记来源+事实即可）；用户**提供**的现场证据是跨 agent 必须自包含的（走 `inline`/`file`）。

## agent 事件分两层（output 给用户 / reason 记决策依据，缺一不可）

- `output`：给用户看的内容（可精简）——透明性的呈现层。
- `reason`：**决策依据/推理过程**（回放、误诊归因、知识沉淀的证据）——**关键决策必写**：triage 路由（为什么命中此分支）、quickly_check 排除（比对了哪些候选、为何排除）、hit/miss（证据链、比对结果）、reference 甄别（为何部分适用/不适用）、根因判断（证据→结论）。**output 和 reason 分开**：结论简洁，推理要完整。

### 行文口径（这两个字段同样要守）

**字段齐全不等于读得懂**：面板把顶层 `summary` 与逐事件的 `output`/`reason` 直接摊给读者。共用条目（二十二条 + 必须保留的四类原值）见同目录 `report-template.md` 的「行文规范」一节——同一 skill 内随 `references/` 一起分发，不依赖 `docs/`；完整判定口径、各面差异与核对配方另见 `docs/spec/writing-norms.md`（可选论证层）。

- **一条只说一件事**，超一个分句就拆行；不把多件事压进 `①②③` 长句——并列掩盖因果，读者读完只知道"有几条"，不知道"哪条导致哪个动作"。
- **主语用具体对象、谓语用动词**。"指南里那句『已按此拓扑验证』出自只改文档的 PR" 读得懂；"验证措辞来自文档 PR" 读不懂（抽象名词当主语）。
- **自造代称首次出现即定义**：为本次诊断临时起的简称（给某个中间状态起的别名之类），只有写的人看得懂，读者没有那段上下文。
- **不造比喻、不排比、不加强调副词、不自我评价**："如实记录""不冒充"一类删掉——如实是默认要求，不必在正文里声明。

trace 特有的一条：**读者没有会话上下文，也没读过报告**。所以字段要能独立读懂——首次出现的简称当场展开，`output`（给用户）与 `reason`（决策依据）分开写；证据原值（case/issue 编号、`文件:行号`、命令、数字、报错原文）照抄，不翻译。


## 顶层 `kb_rev`（会话级，一次写定）

建 session 时把当时那份 `knowledge/` 的版本写进去（`python3 scripts/kb_rev.py` 的末行 = 检出 HEAD 短 sha），**之后不改**。两个用途：

- **跨机接手**：一单在一台机器上做到一半、换到另一台继续时（更多日志在另一台），接手方要拿这个值比对本机知识库版本。不一致意味着 `excluded_cases` 里的 id 可能不存在、同一条 case 的 `confidence.score` 排序不同、甚至那条 case 当时还没沉淀出来——接手方会复现出一套**与上家不同的候选集而不自知**。口径与工具见 `docs/guide/handoff.md`。
- **事后归因**：判"当时为什么没命中"要能回答"当时库里有什么"，只看今天的库会把"库里当时没有"读成"检索没找到"。

拿不到 git（非检出、无 git）就如实写 `unknown`——写 `unknown` 只让版本无法比对，编一个值会让比对给出假结论。


## 值的写法（YAML 语法陷阱）

值里**含 ` #`（空格 + 井号）或 `: `（冒号 + 空格）时必须加引号**——不加的话 YAML 从那里起当注释或当新键，
值会被**静默截断**。实测：`active_case: pending-investigation (upstream #14728)` 读出来是
`pending-investigation (upstream`（少一个反括号）；读到的人以为是"面板把反括号吃了"，
而 PyYAML 与面板读到的其实是同一份被截断的值——根因在写侧。issue 号、带 `#` 的片段都属这一类，统一加引号。

顶层 `active_case` 只写**命中的 case id**，没命中写 `null`。占位串 `pending-investigation` 是
`feedback.case` 的取值（表示"没有 case 可回写 confidence"），不要写进 `active_case`——写进去面板会把它
当 case 显示，并按它生成"该 case 的 fix 生效了吗"这类指令。要记"转上游 / 上游未修"这类说明，写进
`summary` 或 `last_action`。

## 反馈闭环词表

反馈确认后，顶层 `feedback: {case, outcome, confirmed_at}` 要填——`status=resolved 且 feedback.outcome=resolved` 是该 trace 升格为 fixture（强断言基准）的资格条件（`scripts/replay_trace.py --emit-fixtures` 只看这种）。

## 词表同步纪律

`trace` 的 action 词表与 `scripts/trace_metrics.py` 的 `KNOWN_ACTIONS` 保持一致；`reference_lookup` 的 `purpose` 与 `outcome` 分别与 `KNOWN_PURPOSES` / `KNOWN_OUTCOMES` 保持一致；新增取值必须两处同步（本文 + 脚本）。user 事件无 action，不参与词表检查。
