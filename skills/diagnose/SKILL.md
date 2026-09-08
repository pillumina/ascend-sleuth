---
name: diagnose
description: >
  昇腾训练/推理问题的核心诊断循环：收集症状、按 triage-tree 路由、两阶段加载
  并验证 Tier 2 case、命中给 fix（高危 root cause 改提示 halt）或转深度排查。
  Tier-2 未命中但最终解决时起草候选 case。全程写 trace。
  仅在能执行命令的 agent（Claude Code / Codex / pi）中可用。
---

# Diagnose

昇腾问题的核心诊断循环。你是辅助定位工具——**fix 是你给的建议，由人手动应用到客户环境，你不自动改生产**。

> **本文是「可执行脊梁」**：只保留**始终要跑**的骨架与权威规则。步骤的**展开机制**（子步骤/边界/判定细节）见本 skill 的 `references/diagnosis-procedure.md`；**trace 细节**（词表/时间戳/证据落盘完整展开）见 `references/diagnosis-trace.md`，二者**按需加载**。skill 支撑文件一律放本 skill 的 `references/`，**不放仓库根 `references/`**（那是知识库/先验层）。

## 何时用

出现训练或推理问题（中断 / 精度 / 性能），且你在能执行 bash 的 agent 中。被打断后续接 → `/skill:resume-diagnosis`。

## 紧急情况（生产中断）

客户说“紧急 / 生产挂了 / 先恢复”时，诊断目标从“查根因”变成“**先 stabilize**”：

1. **还是先查知识库**——有匹配的 case（比如已知的安全回滚）直接给，这最快。
2. **无快速匹配时**，按已提供的信息一步步给 stabilize 建议：问最近 24-48h 改过什么；`npu-smi info`/`hccl top` 健康；看日志栈尾定位哪层炸；能否先恢复（回滚 checkpoint / 降配 / 重启 daemon）。
3. **不钻深度排查、不写 postmortem**——事后用 `/skill:to-postmortem` 补。

## 流程（骨架）

> 每步只写「做什么 + 何时用」；**子步骤与判定细节**见 `references/diagnosis-procedure.md` 对应「步骤 N」。核心循环 = 收集 → 路由 → 两阶段加载+2.5 reference → 验证 → (未命中)深度排查 → 产出。

> **先验 trace 相似检测**（收集症状后、路由前）：扫 `traces/*.yaml`（**全部 status**——进行中+已闭环都留在 `traces/`），按症状里的模型/框架/配置名/category 对每个 state 文件的 `summary`/`detected_framework`/`detected_category` 做**词法 grep 匹配**。命中且 `status: in_progress`(或 `feedback_pending`) → "本地有同问题进行中 `<session_id>`（<summary>）。要 `/skill:resume-diagnosis` 续接吗？"；命中且已 `resolved`/`escalated` → "上次同类 `<session_id>` 已定位（<summary>）。参考其结论还是重新定位？"；无匹配 → 正常从路由开始。**不再泛泛问"有未完成诊断要续接吗"**（旧提示对无关 session 是噪音）。

1. **收集症状 + 确认框架**（全部来自工程师提供）：错误/环境变量/版本组合(引擎+CANN+HDK+架构)；**信息不全就主动问**；**主动裁剪日志**（失败 rank + 栈尾，绝不灌全量 profiler）。→ 展开见 reference 步骤 1。
2. **分类 → `triage-tree.yaml`（Tier 1）**：症状匹配分支 → 路由 namespace；triage 决策记 trace；未命中 → 语义兜底 `triage_semantic`；无法分类 → Tier 3。→ 展开见 reference 步骤 2。
3. **两阶段加载 Tier 2**：阶段一读命中 category 分片索引筛候选(≤5)；阶段二按 `confidence.score` 载全文 + `quickly_check`(primary→fallback) 验证；**阶段 2.5** 按需取先验 reference（只读 `active`）。→ 展开见 reference 步骤 3。
4. **验证 diagnosis checks**：顺序**对照已提供信息**验证；缺信息→追问；mismatch 且有 `fix_on_mismatch`→提示 fix（**先看 severity**）；无 `fix_on_mismatch`→标 `excluded_cases` 试下一个。→ 展开见 reference 步骤 4。
5. **深度排查（未命中）**：Tier 3 grep `postmortems/`；**源码分析**（疑似框架/算子层且 Tier 3 未覆盖）走 `scripts/src_fetch.py`（见源码分析小节）；都没有→诚实说"知识库未覆盖"，建议 `/skill:to-postmortem`。→ 展开见 reference 步骤 5。
6. **产出**：`resolution` + 顶层 `summary` + 沉淀状态(`sedimented`) + trace；**结果反馈闭环**（问 fix 结果回写 confidence + 写 `feedback_pending`）。→ 展开见 reference 步骤 6。

**始终要避的坑（内联，不必读 reference 就知道）**：
- **两种缺信息，两个时机**：①路由信息（症状/框架/版本/平台/部署形态）不全 → 步骤 1 问；②验证候选所需的精确配置值（某 `--additional-config` 字段/量化档/硬件型号）→ 本步按需问。别混、别让用户全量倒；**别在确认该字段前把 provisional 结论写成 `hit`**（先给低置信假设 + 明确要什么来验证）。
- **版本软匹配**：compat 不符只降 confidence、不硬排除（soft match）；没填的维度跳过。
- **引用完整性**：结论里的 `<CASE-ID>` 必须真实存在于 `knowledge/`，fix 命令必须能回到该 case 的 `fix`/`fix_on_mismatch`/`source_ref`——**不得输出不存在的 id、不得自造命令**（编造 id 会被 `trace_metrics.py` 的引用完整性检查检出）。**但这不是"必须从候选里挑一个"**：候选集是阶段一 regex 过滤的产物、**不完备**；一条候选都验证不过时，正确动作是 `out_of_set` → 步骤 5 深度排查，不是硬选最像的那条（硬选 = 误诊，比诚实 miss 贵得多）。
- **category 决定 quickly_check 形态**：interrupt→grep 签名；precision→数值阈值；performance→profiler 指标；**别混**。
- **活锁 ≠ 组件故障**：同一请求/实体以固定节奏（~1s）重复打同一条日志、且计数冻结 → 判"控制循环活锁"（调度/接纳/抢占在反复重试却无法推进），**向控制循环上游走**——别把"发日志的组件"当故障组件（load/传输后端常只是表象，真实支点在调度/接纳/抢占层）。
- **判别优先追问**：多假设并存时，先问能二分命中的那个问题（如"PD prefill 节点是否禁用了抢占？"这类**控制/调度**维度，而非数据流细节），再补数据流/传输细节——一刀命中，避免在错误维度上堆证据。
- **连续失败 ≤2**：两次未解决即转人工，不试第三个。

## severity 闸门（命中后先看这个）

读候选 case 的 `severity` 字段，决定输出策略：

- `benign` → 直接给 fix
- `service-affecting` → 给 fix，但标注 `fix_side_effects`（如 requires-restart），让人协调窗口
- `data-loss-risk`（如"checkpoint 可能被污染"）→ **不直接给 fix**，输出"先停训练、保留现场、通知 owner"。高危 root cause 的正确动作是 halt 不是 patch

每个 `fix_on_mismatch` 都带 `rollback`——人应用失败时能回退。

## 命中时的输出格式

命中一条 case 后，给工程师**结构化、可追溯**的输出（别只甩一句 fix）——**透明性**：不只给结论，给"为什么是这条"的完整推理链，让工程师能验证而不是盲信：

```
命中 <CASE-ID>（confidence <score>，历史命中 <hits> 次 / 误诊 <misdiagnoses> 次）

为什么是这条（推理链，各点标强度）：
├─ 路由依据（已验证）：症状命中 triage 分支 <branch> → <category>（trace step <N>）
├─ 排除链（已验证）：<N 条候选被 quickly_check 排除>——<case-id> 主检查 <pass/fail>、备检查 <pass/fail>（trace step <N>）
├─ 匹配症状（已验证）：<本轮匹配到的 symptoms>——对应 case 的 quickly_check 主/备
├─ 版本匹配（推测/已验证）：<完全匹配 | version_mismatch：本 case 在 <versions> 验证、客户是 <customer versions>——慎用>
└─ 历史表现（数据）：hits <hits> / misdiagnoses <misdiagnoses>（feedback 闭环积累）

root cause：<root_cause>
fix：<fix>（fix_type: <env-var|config-change|code-patch|pending-investigation>，severity: <benign|service-affecting|data-loss-risk>，<fix_side_effects>）
  → fix_type 决定呈现：env-var/config-change 直接给可执行命令；code-patch 给改动文件+diff 要点（不可直接执行）；pending-investigation 给排查建议
rollback：<rollback>
应用后检查：<怎么验证 fix 生效>
```

**强度标注纪律**（诚实退化，别让工程师把推测当已验证）：`已验证`=本轮 trace 实际执行过；`推测`=依赖推断（版本软匹配降级、根因类比未直接验证）——必须标出来；`数据`=历史积累（confidence/hits，非本轮判断）。

**confidence 校准**：`>0.8` 高可信直接应用；`0.5–0.8` 中可信，应用同时备 plan B；`<0.5` 仅作提示，重点靠手动排查。把标尺讲出来，别让工程师猜。

### 结论呈现（对工程师的输出——专业/细致/严谨/清楚）

> 结论是给人看的。**去AI味 ≠ 删机制**：源码已钉清原理时必须把源码流程/机制原理讲清楚（用户才可能 follow-up / 做下一步判断）——只把内部词表/交叉引用翻译成因果白话、理清结构；**机制与可核对性必须保留**。涉及源码分析或深度排查的结论，按下述结构呈现（命中 case 时"为什么是这条"的推理链仍按上一节给，本结构用于"给结论/给 fix"层）：

1. **结论先行**：一句话＝现象＋根因＋改哪个开关；无内部词表。
2. **时间线（现象）**：按日志校准时间排，只放可观察事实，不夹判断。
3. **机制原理（源码流程）**：分段讲——①触发前置条件（版本/角色/配置守卫）；②每步动作的"为什么"；③因→果闭环。**强制完整**，不得压成一句（这是用户 follow-up 的依据）。
4. **证据对照**：每行＝一条日志/源码行 → 支撑的机制环节（每个结论都能回到一条证据，无处悬空）。
5. **根因与影响面**：明确"什么条件触发 / 什么条件不触发"（版本/角色/配置/载荷），让用户判断"我这边是否属这个面"。
6. **修复方案**：精确 diff（文件:行 ＋ 改前/改后）＋ 备选并列 ＋ side-effect（需重启/可能回归）。
7. **验证与复测**：可执行判定——复测条件 ＋ 看什么信号变/不变。
8. **风险与 follow-up**：改后要重测什么、有哪些依赖；哪些只是规避（非根治）。
9. **可靠度**：confidence ＋ 证据强度；推测/已验证分开标（同上"强度标注纪律"）。

## 每步必写 trace（硬要求）

每个 step 后往 `traces/<session_id>.yaml`（每个并发诊断一文件；模板见 `diagnosis_state.yaml.example`）的 `trace` 数组追加一条。**trace 是完整交互轨迹（trajectory）**——统一 `{role, ...}` 结构：

- **agent 事件**：`{role: agent, step, action: triage|load_index|quickly_check|load_full|run_check|hit|miss|tier3|feedback|reference_lookup|triage_semantic|source_analysis|attribution|resume, output, reason, ...}`。`output` 给用户（可精简）、`reason` 记决策依据（**关键决策必写**）；`source_analysis` 必记 `tool_calls`；`attribution` 执行错可加 `component`。
- **user 事件**：`{role: user, step, content, evidence}`——`content` 摘要（短）+ `evidence` 完整证据（`inline` 原文 / `files` 相对路径 / `sources` URL / `missing` 缺口）。
- **证据落盘铁律（必走，无例外）**：短原文 → `inline` 存完整原文；长命令/配置/日志块/附件 → **先写 `traces/evidence/<session_id>/<名>.txt`** 完整原文、`evidence.files` 用相对路径引用、`inline` 只留一行"完整原文见 evidence.files" + 关键指纹。**禁止**只写摘要、或把原文压成指纹塞 `inline`。
- **写前自检**：问"用户贴的原文现在在哪？"——答不出"已存在文件"的相对路径或完整 `inline` → 证据未落，先落盘再写 trace。
- **时间戳**：建 session 写顶层 `created_at`；**每次写 trace 刷新顶层 `updated_at`**（含 resume 续接——置顶诊断面板）。
- **trace 边界（只记诊断轨迹 + 误诊归因，别混自演进）**：用户中途提出的**流程改进/设计讨论**不是本诊断输入（自演进信号）——走 `traces/evidence/<session_id>/<session_id>_evnote.md`（渐进式披露，正常定位不披露，真要改 SKILL/脚本时才升级为 EV 卡）；`attribution` 执行错归因**仅限"确实影响本次结论"**，纯流程改进走 EV 卡。**别把改进讨论写成 trace 的 user/agent 事件**，也别用 `source_analysis` 记 skill 编辑。

> 完整细节（`KNOWN_ACTIONS` 词表、外部事实获取落盘、agent 事件两层、反馈闭环格式、词表同步纪律）见 `references/diagnosis-trace.md`。trace 是误诊归因的唯一依据：误诊先读 trace 断 **case 错**（改库）还是**执行错**（改 skill）。不写 trace → 无法归因 → 可能改坏正确的 case。

## 源码分析（深度排查的子步骤，入口在步骤 5）

报错签名指向框架代码/算子名/量化描述表（如 `fault kernel_name=QuantBatchMatMulV3`、`modelslim_config.py` 相关 KeyError）且 Tier 3 未覆盖时：

1. **按报错背景确定是哪个源码仓，再向其确认版本**（`scripts/src_fetch.py --list` 看已支持仓库：如 vllm-ascend / torch-npu / CANN / mindspeed-* / verl 等，取决于报错签名指向哪——源码分析依赖对应版本，不要猜）。
2. **获取源码（统一走 `scripts/src_fetch.py` 确定性入口——本地优先、复用优先）**：`python3 scripts/src_fetch.py <repo> --ref <tag>`（`--list` 看已知仓库与 host：vllm-ascend=GitHub、mindspeed-*=GitCode、torch-npu=GitCode、verl=GitHub；未知/私有 → `--url`）。脚本把「clone 到哪 / 同版本复用 / URL 来自哪」从 agent 自觉变成**确定性操作**——本地 `src-code/<org>/<repo>/` 已有则**复用**（`git -C log -1`/`describe` 核对版本），没有则按已知 host 拉取。**「不落库」= 源码不随仓库提交、也不写进知识库**；分析仍要保留源码（`src-code/` 本地缓存），知识库只记 `source_ref` 代码指针。
3. **grep 定位**：搜报错签名/算子名/函数名（如 `grep -rn "QuantBatchMatMulV3" vllm_ascend/`）→ 读相关文件片段 → 分析根因。
4. **追问用户验证**：对照预期/复现/补环境信息，验证根因假设。
5. **follow-up**：查知识库是否已覆盖；`gh search issues/prs` 看上游是否已修复（已修复→fix=升级到修复版本；未修复→根因+workaround）；内网不可达→诚实说明无法查证。
6. **多层级**：根因指向更底层开源仓（torch-npu）→ 同样流程分析其源码（`source_ref` 指向该仓）；CANN 等未开源 → **承认局限**，给方向 + 建议联系华为。
7. **沉淀**：根因清楚且知识库未覆盖 → `/skill:to-postmortem` 记 `source_ref: {repo, ref, file, line}`；**顺手**沉淀跨事故稳定的结构事实 → `/skill:to-reference`（software-fact / env-var-table / compat-matrix，判据："6 个月后/跨版本是否仍成立"）。

## 不要做

- 不要替人决定 root cause——给结构化清单，人执行后贴回结果
- 不要连续尝试第三个 case——两次未解决即转人工（误诊保护的串联保护）
- 不要把全量 profiler 灌进 context——裁剪到相关 rank + 栈尾
- 不要用 interrupt 的 grep 思路建 precision 的 quickly_check（category 形态不同）
- **不要直接改本 skill / triage / reference 等会进诊断上下文的资产——改进动作必须先产 EV 卡**（`scripts/ev_proposal.py --new`）再涉及。诊断中发现的流程改进（执行错/摩擦）走 `attribution`（执行错归因喂 component_tally）或 EV 卡（主动设计改进），**不混入本诊断 trace**。
- 被打断 → `/skill:resume-diagnosis`
