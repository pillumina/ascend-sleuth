---
name: diagnose
description: >
  昇腾训练/推理问题（中断 / 精度 / 性能）要定位根因时用：按知识库 case 匹配给修复建议
  （高危只提示停机保留现场），未命中转深度排查；最终解决时若库里没有同类 case，起草候选 case。需要能执行命令的 agent。
---

# Diagnose

昇腾问题的核心诊断循环。你是辅助定位工具——**fix 是你给的建议，由人手动应用到客户环境，你不自动改生产**。

> **本文是骨架**：只放六步与每单一律要守的规则。每步的展开在 `references/steps/`，按该步「何时读」的条件打开，不整组读——快路需要步骤 1 / 2 / 3 / 4 / 6 五份，全路再加 5。分支路径（紧急、深度排查、源码分析、数据探询）各有一个入口文件。skill 支撑文件一律放本 skill 的 `references/`，**不放仓库根 `references/`**（那是知识库/先验层）。

## 何时用

出现训练或推理问题（中断 / 精度 / 性能），且你在能执行 bash 的 agent 中。被打断后续接 → `/skill:resume-diagnosis`。

**只问思路的咨询不是接单**：工程师问"这类问题怎么定位"、手上没有报错原文或日志、不需要你给出这次的具体结论时，按已有知识直接答方法（可读先验层的流程词条），**不开 session、不写 trace**：trace 要回放的是"看了哪些候选、给了什么修复、结果如何"，没有现场证据的会话记录提供不了这两样。等对方贴出证据、要往下定结论时再开 session。

## 流程选择（开屏一次，决定这次走到多深）

**何时问**：确认这不是"只问思路的咨询"（见上一节）之后、开始收集症状之前。这时工程师已经在场，问一次的成本是十秒；拖到后面再问，等于让他为一条他已经不想要的路径跑完深度排查与报告。

**问什么**（三个口子，按他答的走）：

| 选择 | 走到哪一步为止 | 明确不做 |
|---|---|---|
| **快路**「先给最可能的结论 + 验证命令」 | 候选加载 → 命中即给结论 | 深度排查不在命中后自动展开；步骤 6 只出对话输出 + 一条最短 trace，报告与沉淀候选都不产 |
| **全路**「完整排查到根因」 | 未命中继续深度排查 → 位置报告 → 沉淀候选 | —— |
| **紧急**「生产中断，先恢复」 | 按 `references/emergency.md` 先 stabilize | 不钻深度排查、不写 postmortem |

**怎么写进过程**：把选择记进 trace 的顶层 `summary` 与首条 user 事件，让续接的人一眼看到这单的目标。路径不同不改变下面骨架的**前四步**（收集、路由、候选加载与验证、探询）——路由质量与证据采集三条路都要，省掉它们会让快路变成瞎猜。真正的分叉在两处：**步骤 5 深度排查**与**步骤 6 产出**。

**别把它做成问卷**：三个选项给编号，工程师回一个数字即可；他一开始就贴了完整的报错与日志、又没说要快速结论时，默认按**全路**走，只在结论交付时问一次要不要再往下（深挖 / 沉淀 / 都不用）。

**改向不重来**：走到一半他说"先给结论就行"或"继续挖"，就切路径——已跑完的步骤不重跑，已写的 trace 不改写，新路径从当前步继续。

## 紧急情况（生产中断）

客户说「紧急 / 生产挂了 / 先恢复」时读 `references/emergency.md`：先查知识库，无匹配就给 stabilize 建议，不钻根因、不写 postmortem。

## 流程（骨架）

> 核心循环 = 收集 →（数据缺口则取采集面）→ 路由 →（键触发 + 背景：证据里的码/签名/名/平台组件词当场查）→ 两阶段加载 + 2.5 reference → 验证 →（未命中）深度排查 → 产出。每步只写「做什么 / 完成判据 / 读哪个文件」；步骤细节只写在对应文件里，本文不重复。

> **开单先同步知识基线**（诊断读知识库的那一版 commit 坐标）：`trace_begin.py` 建单时读 `.local/settings.json` 的 `sync` 段，fetch 远端知识库（超时 10 秒），落后时按 ff-only 合并；失败不阻塞开单。一次合并对 `knowledge/` 立即生效，对 `skills/` 下次会话生效；带进 `dsh-plugins/` 的面板代码要重启 DSH 后生效。

> **先验 trace 相似检测**（收集症状后、路由前）：扫 `traces/*.yaml`（**全部 status**——进行中 + 已结单都留在 `traces/`），按症状里的模型/框架/配置名/category 对每个 state 文件的 `summary`/`detected_framework`/`detected_category` 做**词法 grep 匹配**。
> - **陈述，不提问**：命中就**说一句**——"本地有 `<session_id>`，停在 <哪一步 / 结论一行>"——然后**在同一条消息里继续按本次问题往下走**。工程师回"就是这个"再切 `/skill:resume-diagnosis`。**不要写成"要续接吗？"**：那是把判断推给一个手上没有上下文的人，还把新问题卡在路由之前等答复。
> - **有判据才提**：命中单的 `summary` 为空、或 trace 只有寥寥几步（裸 stub）时不提——念一个没有内容的 session，等于让工程师替你判断哪一单。
> - **一轮最多提一次**，不随步骤重复。
> - **只提同类**：匹配维度是模型/框架/配置名/category，同框架下的无关问题命中就是噪音；已 `resolved`/`escalated`/`archived` 的同类单同样只陈述（给结论一行供参考），不拦路、不泛泛问"有未完成诊断要续接吗"。
> - **不在这里追旧单的反馈**：`feedback.outcome: pending` 是上一单的事，与本次问题无关——它挂在续接启动与面板待办上（规则见 `references/steps/6-deliver.md` 步骤 6）。开屏先审旧单是审讯，不是诊断。
> - 状态词表见仓库根 `trace-status.yaml`。

1. **收集症状 + 确认框架 + 落负载类型**：从材料里提取覆盖表的十行与环境变量，提取不到的行留空；缺口一次问全、逐值标来源；同时把现场事实按发生顺序写进 `incident_timeline`、环境一行写 `incident_env`。
   **完成判据**：覆盖表每行有值或列为待问项；现场时间线已写进 trace。
   → **必读** `references/steps/1-collect.md`
2. **分类 → `triage-tree.yaml`（Tier 1，路由树）**：先落负载类型、再在负载类型内判性质；`triage` 事件必写 `workload_type` / `workload_type_source` / `routed`（未命中写 `routed: []`，不省略）；本步收尾做键触发与背景层两半查询。
   **完成判据**：triage 字段齐；键触发与背景层各留一条 `reference_lookup`（含 `skipped` 理由）。
   → **必读** `references/steps/2-route.md`
3. **两阶段加载 case 层（Tier 2）**：阶段一读命中 `(namespace × category)` 的读侧视图筛候选（≤5，排序由你按相关性判断，`score` 只破平）；阶段二载全文跑 `quickly_check`；阶段 2.5 候选命中后读 `ref_knowledge` 取修复依据。
   **完成判据**：候选 ≤5 且逐条有 `quickly_check` 结论；阶段 2.5 已取依据或记 `skipped` 加理由。
   → **必读** `references/steps/3-cases.md`
4. **验证 diagnosis checks**：对照已提供信息顺序验证；mismatch 且有 `fix_on_mismatch` → 提示 fix（**先看 severity**）；无 `fix_on_mismatch` → 标 `excluded_cases` 试下一个；版本按软匹配，不硬排除。
   命中前用已查到的背景事实反证一次修复前提：事实明确排除前提才否决，适用面对不上记 `unknown` 并写进第 0 步核验。`hit` 事件记支撑 fix 的 `ref_ids`。
   **完成判据**：命中进入步骤 6，全部排除进入步骤 5。
   → 读 `references/steps/4-verify.md`
5. **深度排查（未命中）**：**先取方法流程**（默认一条），并拿步骤 2 的背景先验框定方向；有整包现场证据时先跑内置分析器（入口与选择见 `references/analyzer-dispatch.md`，只在已启用时执行）；证据不足且现有采集器能补齐时按 `references/collector-dispatch.md` 推荐脚本（只推荐，不执行）；Tier 3 grep `postmortems/`；疑似框架/算子层且 Tier 3 未覆盖走源码分析；都没有 → 诚实说「知识库未覆盖」并建议 `/skill:to-postmortem`。
   **完成判据**：流程取用与 Tier 3 各留事件（含 `miss` 理由）；结论能指回证据或明确未覆盖。
   → 读 `references/steps/5-deep-dive.md`
6. **产出**：`status` + 顶层 `summary` + 定位报告（**全路**）+ `sediment_candidates`（**全路**）+ `feedback` 挂账与回报指令 + `severity` / `fix_emitted`；`summary` 与三段内容字段走 content 写入口，报告同步修订。
   **完成判据**：上述字段齐；trace 收尾字段（`ended_at` / `stop_reason`）写齐。
   → **必读** `references/steps/6-deliver.md`

## 先验消费点（五个触发点）

先验层由流程里的**缺口**触发，不是第四检索层（不参与候选路由 / 排序）。五个触发点的时点、trace 的 `purpose` 与探询纪律见 `references/reference-gaps.md`；**每个触发点都留 `outcome: hit|miss|skipped`**（`skipped` 必写理由）——不查不记录时，「查了没有」与「根本没查」在数据上同形。

## 始终要避的坑（内联，不必读 reference 就知道）

- **两种缺信息，两个时机**：①路由信息（症状/框架/版本/平台/部署形态）不全 → 步骤 1 问，**按步骤 1 那张固定行覆盖表逐行核，"提取不到"就是待问项**（不靠当场自评"我是不是漏问了什么"——平台、触发位置、已试过什么这三行的漏问都发生在自评上）；②验证候选所需的精确配置值（某 `--additional-config` 字段/量化档/硬件型号）→ 本步按需问。别混、别让用户全量倒；**别在确认该字段前把 provisional 结论写成 `hit`**（先给低置信假设 + 明确要什么来验证）。
- **版本软匹配**：compat 不符只降排序分数、不硬排除（soft match）；没填的维度跳过。
- **category 决定 quickly_check 形态**：interrupt→grep 签名；precision→数值阈值；performance→profiler 指标；**别混**。
- **活锁 ≠ 组件故障**：同一请求/实体以固定节奏（~1s）重复打同一条日志、且计数冻结 → 判"控制循环活锁"（调度/接纳/抢占在反复重试却无法推进），**向控制循环上游走**——别把"发日志的组件"当故障组件（load/传输后端常只是表象，真实支点在调度/接纳/抢占层）。
- **判别优先追问**：多假设并存时，先问能二分命中的那个问题（如"PD prefill 节点是否禁用了抢占？"这类**控制/调度**维度，而非数据流细节），再补数据流/传输细节——一刀命中，避免在错误维度上堆证据。
- **类别冲突不得二选一（但有先后）**：日志/报错签名指向的方向与**症状性质**冲突时（例：症状是"输出乱码"→ precision，日志却是 store/BM 初始化失败 → interrupt 味），**按症状的性质定 category——症状是工程师手上那个现象，日志签名只是线索**；自动单选先走症状那条线，**在同一屏里说明另一条线的存在**（它需要哪些信息才走得通）。给一句覆盖点：「若你更关心 X，说一声我就切过去」——**不要停下来问他"你觉得这是哪类问题"**：他答不了这个判断，那正是要找你的原因。日志签名一侧的证据不丢：它作为备选线写明换向条件，不因为当前没走就删掉。
- **日志要成过程，不要只摘一行**：材料里有日志、且读出了状态转折与重复区间 → 写进 `failure_process`（`nodes` 最多 8 条、`window` 起止；日志原文留证据文件，`clock_note` 记日志与墙钟时差）。面板第二层时间线与报告附录都用它；只摘一行会让「怎么一步步坏掉的」无从回看。
- **反馈要挂账，不靠记性**：给完 fix **不在这里反问结果**（他还没应用）；立即写 `feedback`（`feedback_pending_since` 一并写）并给一条可复制的回报指令。反馈捕获是学习环的吞吐上限，而它原先只有一个**人在新会话里想起来**的入口。
- **采集只推荐，不操作客户环境**：缺现场证据时按 `references/collector-dispatch.md` 给脚本与说明；不执行采集脚本、不代客户上传，也不临时手写采集脚本。`cpu-trace` 这类需要 root 或会短时改变内核采集状态的脚本要写明授权与影响。
- **连续失败 ≤2（只计 fix 未解决）**：同一个问题给过两次 fix、客户应用后都未解决 → 转人工，不试第三个。**候选被 quickly_check 排除不计入**（那是候选穷尽，不是失败）。
- **跨机比时间先核时钟**：拿多机日志排先后（"哪个 rank 先挂""哪台先断"）之前，取各机都会记的**同一个事件**（任务启动 / HCCL 初始化 / 集群心跳）比时间差——秒级以内可直接排序，明显漂移或先后颠倒就把顺序结论**降级为不确定**并写明。时钟漂移不报错，它只是让"最早的那个"换成另一个节点。时间戳整体差整数小时多是单机时区配置，不是漂移（展开与记录见 `references/steps/5-deep-dive.md` 的「跨机时间线」一节）。

## severity 闸门（命中后先看这个）

读候选 case 的 `severity` 字段，决定输出策略：

- `benign` → 直接给 fix
- `service-affecting` → 给 fix，但标注 `fix_side_effects`（如 requires-restart），让人协调窗口
- `data-loss-risk`（如"checkpoint 可能被污染"）→ **不直接给 fix**，输出"先停训练、保留现场、通知 owner"。高危 root cause 的正确动作是 halt 不是 patch

每个 `fix_on_mismatch` 都带 `rollback`——人应用失败时能回退。

## 每步必写 trace（硬要求）

trace 是完整交互轨迹（trajectory）＋误诊归因的唯一依据：不写 trace 就无法分 **case 错**（改库）与 **执行错**（改 skill），硬改可能弄坏本来正确的 case。字段全集、词表与行文要求见 `references/diagnosis-trace.md`；本节只放每步都要守的规则。

- **建单用脚本起 header，别照模板手打**：`python3 scripts/trace_begin.py --slug <日期>-<issue 号>-<短名> --framework <…> --platform <…> --category <…>`；派生字段由机器填，同时建 `traces/evidence/<slug>/`。**没有这个脚本的旧克隆**（内网没 sync）才照 `diagnosis_state.yaml.example` 手写，且必须自己写 `harness_session`。`external_evidence`（on|off）仍由你按工具有没有写。
- **先解析 trace 目录（一次，之后全程用它）**：`python3 scripts/shared_dir.py traces` 打印的绝对路径就是本次要读写的 `traces/`——它锚在**主检出**，从 worktree 干活也不会写进一个主检出看不到的地方。**本 skill 里所有 `traces/…` 的读写（含最前面的相似检测）都以这个路径为准**。
- **随手写三样，否则读数恒空**：每条 agent 事件带 `ts`（epoch 毫秒，**每一步至少第一条**），步骤 6 写顶层 `ended_at`，建 session 时写顶层 `harness_session`（DSH 里是 `$DSH_SESSION_ID`）。没有 `ts` 就切不出每步窗口与成本；单次耗时用 `created_at` → `ended_at`，缺 `ended_at` 就退到 `updated_at` 并在面板标明。
- **非 DSH 的 agent 补三个值**：Claude Code / Codex 等没有 DSH 会话库的 agent 建单时显式传 `--harness-session`、`--model`、`--tokens-start`，收尾用 `python3 scripts/trace_usage.py --trace <trace> --tokens <本次总数>` 写顶层 `tokens`；不传就按历史单的回退规则，读数为空（不影响命中与工具计数）。模型名由 `trace_begin.py` 从 `harness_session` 对应的 DSH 会话记录写进顶层 `model`；取不到就留空，不猜。
- **收尾核对顶层 `harness_session`**：跑 `ascend_trace_status` 时，本单那一行带 `⚠缺会话号` 就是漏了——当场补 `python3 scripts/link_harness_sessions.py --trace <本单文件名> --session-id "$DSH_SESSION_ID" --apply`。要的是 `$DSH_SESSION_ID`，不是本单的 `session_id`；更早的历史漏写单用不带 `--session-id` 的跑法（脚本去会话日志里认名字）。
- **每条 agent 事件必带 `output`**（哪怕一句）：核验了谁 / 用什么判据 / 结果 pass|fail|conflict。只写 `reason` 的人读视图是空白。
- **`hit` 的 `case` 只写真 case id**：未命中、上游定案、跨队案例这类说明写进 `output`，不要写成 `case: "上游案在：#19191（…）"`——面板与条目使用记录都会把它当成 case id。
- **agent 事件**：`{role: agent, step, action, output, reason, ...}`，`action` 词表见 `references/diagnosis-trace.md`；`triage` 必带 `routed`；`report` 记 `report_file`（全路必写，快路不产报告也不写）；`reference_lookup` 必带 `purpose` 与 `outcome` 三态；`source_analysis` 必记 `tool_calls`，另记 `repo` / `ref` / `fetch_exit` / `verify`；`parallel_group` 记同批并发，`load_full` / `load_index` 记 `considered_candidates`。
- **user 事件**：`{role: user, step, content, evidence}`——`content` 摘要（短）+ `evidence` 完整证据（`inline` 原文 / `files` 相对路径 / `sources` URL / `missing` 缺口）。
- **`last_action`（每次提问后更新）**：以提问结束的一轮，顶层 `last_action` 写一句话，说明在等哪份材料、哪个决定或哪条命令输出；下一轮拿到回答后改写或清空。`evidence.missing` 只记那一轮缺的材料，历史事件不改写。面板与续接按 `last_action` 判断「等什么」，不按事件顺序推断。
- **证据落盘铁律（必走，无例外）**：短原文 → `inline` 存完整原文；长命令/配置/日志块/附件 → **先写 `traces/evidence/<session_id>/<名>.txt`** 完整原文、`evidence.files` 用相对路径引用、`inline` 只留一行"完整原文见 evidence.files" + 关键指纹。**禁止**只写摘要、或把原文压成指纹塞 `inline`。
- **写前自检**：问"用户贴的原文现在在哪？"——答不出"已存在文件"的相对路径或完整 `inline` → 证据未落，先落盘再写 trace。
- **原件引文要核（有原件时）**：工程师交来**原件**时，引用原文另落 `evidence.quotes: [{file, line, quote}]`，写报告前跑 `python3 scripts/verify_evidence.py <trace> --root <原件根>`；核不过的引文不能支撑结论——对应结论**降级为推测**或回步骤 4 重新取证。对话里粘贴的片段不填 `quotes`，写一句"无原件可核"。
- **时间戳**：建 session 写顶层 `created_at`；**每次写 trace 刷新顶层 `updated_at`**（含 resume 续接）。
- **停止原因（收尾写一次）**：顶层 `stop_reason` 记这一单为什么停（`resolved_confirmed` / `halted_ask_user` / `budget_exhausted` / `escalated_tier3` / `abandoned` / `unknown`）。漏写按未记录统计。
- **`kb_rev`（建 session 时写定，之后不改）**：`python3 scripts/kb_rev.py` 的末行 = 检出 HEAD 短 sha；拿不到 git 就写 `unknown`。跨机接手与事后误诊归因都要它。
- **trace 边界（只记诊断轨迹 + 误诊归因，别混自演进）**：诊断中途的流程改进 / 设计讨论走 `traces/evidence/<session_id>/<session_id>_evnote.md`；`attribution` 执行错归因**仅限"确实影响本次结论"**。别把改进讨论写成 trace 的 user/agent 事件。

## 不要做

- 不要替人决定 root cause——给结构化清单，人执行后贴回结果
- 不要连续尝试第三个 case——**两次 fix 未解决**即转人工（误诊保护的串联保护；候选被排除不计入）
- 不要把全量 profiler 灌进 context——裁剪到相关 rank + 栈尾
- 不要用 interrupt 的 grep 思路建 precision 的 quickly_check（category 形态不同）
- **不要直接改本 skill / triage / reference 等会进诊断上下文的资产——改进动作先记录信号**：把观察交给 `python3 scripts/evolve_intake.py record …`；收尾不产 EV 卡、不跑实验。诊断中发现的流程改进（执行错/摩擦）走 `attribution`（执行错归因喂 component_tally），行为质量候选留给显式的 `/skill:self-evolve` 分诊，**不混入本诊断 trace**。
- 被打断 → `/skill:resume-diagnosis`
