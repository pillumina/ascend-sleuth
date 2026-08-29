---
name: diagnose
description: >
  昇腾训练/推理问题的核心诊断循环：收集症状、按 triage-tree 路由、两阶段加载
  并验证 Tier 2 case、命中给 fix（高危 root cause 改提示 halt）或转深度排查。
  Tier-2 未命中但最终解决时起草候选 case。全程写 trace。
  仅在能执行命令的 agent（Claude Code / Codex / pi）中可用。
disable-model-invocation: true
---

# Diagnose

昇腾问题的核心诊断循环。你是辅助定位工具——**fix 是你给的建议，由人手动应用到客户环境，你不自动改生产**。

## 何时用

出现训练或推理问题（中断 / 精度 / 性能），且你在能执行 bash 的 agent 中。被打断后续接 → `/skill:resume-diagnosis`。

## 紧急情况（生产中断）

客户说“紧急 / 生产挂了 / 先恢复”时，诊断目标从“查根因”变成“**先 stabilize**”：

1. **还是先查知识库**——如果有匹配的 case（比如已知的安全回滚），直接给，这最快。知识库里的具体解药永远优于通用急救口诀。
2. **没有快速匹配时**，根据客户已提供的信息，一步步给 stabilize 建议：
   - 问客户最近 24-48h 改过什么（脚本/配置、框架版本、驱动/固件/CANN、数据、模型代码）——事故多半源于最近的改动
   - 基础健康检查：`npu-smi info`（卡活着吗）、`hccl top`（通信拓扑正常吗）
   - 看日志栈尾，定位哪层炸的
   - 能否先恢复：回滚上个 checkpoint 重启 / 降配（关 EP、降 batch）/ 重启 daemon
3. **不钻深度排查、不写 postmortem**——事后用 `/skill:to-postmortem` 补。

## 流程（核心循环详见 references/diagnosis-procedure.md）

> **执行模型**：你不访问任何环境。所有信息——日志、版本、报错、环境变量——都由工程师从客户那提供（粘贴进来）。你的主动角色是**信息不够时，明确提示工程师需要向客户要什么**。case 里的 `command` 是“要确认的检查”：对照已提供的信息判断，或让客户跑后把输出贴回来——不是你直接执行 `pip`/`env`/`grep`。
>
> **续接**：若存在未完成的 `diagnosis_state-*.yaml`（每个并发诊断一个文件），先问“有未完成的诊断，要 `/skill:resume-diagnosis` 续接吗？”——别让工程师自己记着跑 resume。

1. **收集症状 + 确认框架**（全部来自工程师提供的信息）
   - 错误信息、`HCCL_*`/`ASCEND_*`/`NPU_*` 环境变量值、**版本组合**（引擎版本 + CANN + HDK/驱动 + 架构 A2/A3/A5）——都从客户那要来
   - **信息不全就主动问**：若没说清，主动问——①症状（什么报错/什么时候挂）②客户的版本组合（引擎/CANN/HDK/架构）③日志/profiler 在哪（贴相关 rank + 栈尾）。别干等
   - **框架从提供的信息/报错判断**（日志里 mindspeed/vllm 字样等）；判断不了就直接问工程师“客户跑的什么框架”，**不要跑 `pip list`**（那是你本地环境，跟客户无关）
   - **主动裁剪日志**：让工程师只贴失败 rank + 报错栈尾，绝不灌全量 profiler——诊断 session 的 context 八成是日志，全量灌进来会滑出 smart zone（~120K token 推理最锐利），推理质量暴跌。**若工程师已贴全文：agent 自行裁剪进 context（保留失败 rank + 栈尾 + 相关段），不要求工程师重贴**——裁剪是 agent 的职责，不是让工程师反复操作

2. **分类 → 加载 `triage-tree.yaml`（Tier 1）**
   - 症状匹配分支 → 路由到 namespace（先 `training|inference/<framework>/`，再 `common/`）
   - **triage 决策记进 trace**（命中哪个分支、路由到哪些 namespace、category）
   - triage 多分支弱匹配/置信度低 → **优雅退化**：加载所有 namespace 索引让 quickly_check 筛（索引便宜，退化成本可控）
   - 框架未检测到 → 只搜 `common/`；无法分类 → 直接 Tier 3

3. **两阶段加载 Tier 2**
   - **阶段一**：读 `knowledge/_index.yaml`（`scripts/build_index.py` 生成的一次性索引，含 `id/title/symptoms/quickly_check/category/confidence.score` + `file` 定位——hits/misdiagnoses 不在索引里，它们是学习环动态字段留在 case 本体），取命中 namespace 的条目，用 `quickly_check`（primary→fallback）**对照已提供的信息**过滤候选 ≤5；检查项缺信息时，记下要向客户补要什么。索引缺失或 `--check` 报过期 → 兜底：逐文件只读上述索引字段，并提醒跑 `scripts/build_index.py` 重建
   - **空库提示（冷启动）**：若命中 namespace 为空（还没 case），**不要静默退化**——告诉用户“当前 `knowledge/<ns>/` 还没有验证过的 case，你可以：①继续深度排查（步骤 5）②诊断完跑 `/skill:to-postmortem` 沉淀成第一条 case ③转人工”。别让空库的体感是“这玩意啥也不会”。
   - primary 不匹配但 fallback 匹配 → 仍进验证，标记 `low_confidence`
   - **category 决定 quickly_check 形态**：interrupt 用 grep 错误签名、precision 用数值阈值（`loss>1e3`、`has_nan`）、performance 用 profiler 指标（`comm_ratio>0.4`）——别混用
   - **阶段二**：全量加载候选，按 `confidence.score` **降序**进入验证。**多条候选时明示**：“匹配到 N 条候选，先验证最可能的 `<id>`（confidence `<score>`）”，让工程师有数；工程师可说“跳过这条试下一条”

### 2.5 reference 辅助查询（先验知识层）——候选加载后、验证前

按需取先验知识辅助诊断，**只读 `status: active` 的词条**（draft / pending-review / deprecated 一律不加载——未验证知识不进上下文）：

- **① 候选 case 显式引用**：候选 case 有 `ref_knowledge` 字段 → 加载其引用的 reference 词条全文（最精准；当前 case 尚无该字段，此路为未来路径）；
- **② 平台匹配的 summary 层（只限背景类 type）**：从症状收集阶段确认的客户平台，扫 `references/<type-dir>/*.yaml` 中 type 属于**背景类**（`platform-fact` / `software-fact` / `tool` / `methodology`——承载"有哪些平台事实/工具/方法论可用"的背景）且 `applies_to.platforms` 匹配该平台且 `status: active` 的词条，**只读 `summary` + `applies_to` 字段**（每条一行，低 token）作平台背景提示，**不读全文**。**查表类（`error-code` / `fault-pattern` / `env-var-table`）不进 summary 层**——它们是码/签名检索键，按需走 ③；其 summary 只是"族/域/表有几条"的索引信息，对诊断背景无价值，且 cross 全匹配会让它随表数线性膨胀（93 词条时 summary 层 4.5K token、其中查表类占 2.8K，2026-08 实测）。**匹配语义**：`applies_to.platforms` 含客户平台标识、或含 `cross`（跨平台成立，匹配所有平台）、或词条未填 platforms（视为跨平台）即命中；平台标识开放（如 `Atlas 200I/500 A2`），按客户实际报告的平台匹配，不限定型号清单；
- **③ 签名/查表类检索（error-code / fault-pattern / env-var-table，不走 summary 层——签名/名是检索键不是摘要）**：症状里出现**错误码**（E1xxxx/EIxxxx/507xxx 等）→ 查 `ascend-error-code-structure` 的 `module_files` 前缀映射定位族文件（`references/errors/<族>.yaml`），族内 grep code 读 meaning/solution；症状含**可 grep 的故障签名**（如 "0x800000"、fault kernel_name、"I2C WRITER DATA error"、event_id）→ 按主题域定位 `references/fault-patterns/<域>.yaml`，域内 grep symptoms 命中读 cause/fix；诊断涉及**具体环境变量**（如怀疑 ASCEND_GLOBAL_LOG_LEVEL 配置）→ 按模块定位 `references/env-vars/<表>.yaml`，表内 grep name 读 description/example；
- **④ 按需全文**：验证某条具体事实需要细节时（如对照 A5 950DT 内存规格、日志路径表、方法论流程步骤），再读对应词条全文；
- **token 纪律**：reference 查询只在命中候选后发生，不是每次诊断都读；summary 层只限背景类（②）、查表类只按签名/名 grep（③）——**查表类文件（族/域/表）只 grep 不 read 全文**（如 ge.yaml 120 码 30KB，read 全文 ≈7.5K token，grep 只返回匹配行）；平台不匹配的词条不加载；
- **trace 必记**：每次查询记 `{action: reference_lookup, ref_id, platform, purpose: signature|fix|background}`——这是 reference 命中统计（hits/last_hit）的数据源，不记则先验知识层的学习环空转。

4. **验证 diagnosis checks**
   - 顺序验证候选 case 的 `diagnosis` 检查项（**对照已提供的信息**，不跳步）；某步缺信息 → 提示工程师向客户要（或让客户跑该 command 贴回输出）；mismatch 且有 `fix_on_mismatch` → 提示 fix（**先看 severity**，见下）
   - **版本软匹配**：把候选 case 的 `compat`（framework/cann/hdk，**填了的维度**）逐维对照客户的版本组合——任一维不匹配 → 标 `version_mismatch`、confidence 临时下调，**case 仍是候选**（不硬排除）；没填的维度跳过
   - 命中 → 输出 root cause + fix，进入步骤 6
   - 所有候选未命中 → 深度排查（步骤 5）

5. **深度排查（Tier 2 未命中）**
   - **若 Script 工具已接入**（见 references/script-integration.md），按 category 用：interrupt→日志/core dump、precision→`mem-analyze`、performance→`ascend-profile-analyze`/`bench-run`。**当前骨架阶段这些 Script 多半还没接**——别假装能调，诚实告诉工程师。
   - Tier 3 关键词检索 `postmortems/`（`rg -l '<keyword>' postmortems/`，top-3 读片段；含 `postmortems/inbox/` 未审草稿——可用但标注未经人审）。trace 记 `{action: tier3, keyword, files_read}`——Tier 3 挽救率指标（docs/metrics.md）靠这条统计。这是骨架阶段真正能用的兜底
   - **源码分析（问题疑似框架/算子层时，常见且高价值）**——报错签名指向框架代码/算子名/量化描述表等（如 `fault kernel_name=QuantBatchMatMulV3`、`modelslim_config.py` 相关 KeyError）且 Tier 3 未覆盖时：
     1. **向用户确认版本**（vllm-ascend / CANN / torch-npu——源码分析依赖对应版本，不要猜）；
     2. **按需取对应版本源码**：`gh repo clone --branch <tag/commit>`，或稀疏拉取指定文件（`gh api repos/<repo>/contents/<file>?ref=<commit>` 取单文件）——**不维护多版本、不落库**，只拉当前分析需要的；
     3. **grep 定位**：搜报错签名/算子名/函数名（如 `grep -rn "QuantBatchMatMulV3" vllm_ascend/`）→ 读相关文件片段 → 分析根因（为什么这么实现、什么版本引入了什么行为）；
     4. **追问用户验证**：让用户对照预期/复现/补环境信息，验证根因假设；
     5. **定位清楚 → 沉淀 case**（`/skill:to-postmortem`，记 `source_ref: {repo, ref, file, line}`——ref 用分析所用版本）。trace 记 `{action: source_analysis, repo, ref, files_read}`。
     **边界**：源码分析可能耗时（token/时间）——先判断"疑似源码层"再走（不是每个未命中都 clone）；用户可随时终止（"跳过源码分析"）；拿不准根因不要硬下结论，联系技术支持。
   - 都没有 → 诚实说“知识库没覆盖这个问题，需手动排查；定位完用 `/skill:to-postmortem` 沉淀，下次就能命中”。人 + agent 联合分析

6. **产出**
   - `resolution: resolved | escalated | unknown`
   - **Tier-2 命中**：常规 postmortem 草稿
   - **Tier-2 未命中但最终解决**：postmortem 含一段你起草的**候选 case**（quickly_check + diagnosis + confidence 低），交 `/skill:knowledge-groom` 验证
   - 完整 trace 随 `diagnosis_state-<session_id>.yaml` 留存（每并发诊断一文件；模板见 `diagnosis_state.yaml.example`）
   - **结果反馈闭环（闭合学习环，关键）**：给完 fix 后，**等工程师应用并回来报告结果**——问“应用后解决了吗？（解决 / 没解决 / 部分解决）”。结果回写该 case 的 confidence：解决 → `hits += 1`；没解决 → `misdiagnoses += 1`、更新 `last_hit`。**不问这步，confidence/误诊率永远是初始值，整个学习机制空转。**
   - **反馈捕获结构化（不靠记性）**：给完 fix、session 收尾前，往 state 文件写 `feedback_pending: <case-id>`。**每次 `/skill:diagnose` 或 `/skill:resume-diagnosis` 启动时先扫活跃 state 文件**——发现该标记就先追问"上次 <case-id> 的 fix 应用后解决了吗？"，按答复回写 confidence（上条规则）、trace 记 `{action: feedback, case, outcome: resolved|not_resolved|partial}`、清掉标记。反馈捕获是整条学习环的吞吐上限——标记写在文件里，就不依赖任何人的记性
   - **反馈追问降级（体验，防骚扰）**：同一 `feedback_pending` 标记**追问 2 次未获回应 → 停止追问**，标 `feedback_stale: true`（保留标记供 trace_metrics 统计"反馈缺失"），不再每次启动骚扰工程师。工程师之后主动回报仍可回写——追问是礼貌提醒，不是逼迫
   - **沉淀已含在本步骤**：命中=常规 postmortem、未命中=含候选 case 的 postmortem，本步骤已生成。**只有当本次不是经 /diagnose 定位的**（如用 Kimi/手工查的、或没配 session-end hook 导致 postmortem 没生成），才需 `/skill:to-postmortem` 手动沉淀。

## 命中时的输出格式

命中一条 case 后，给工程师**结构化、可追溯**的输出（别只甩一句 fix）：

```
命中 <CASE-ID>（confidence <score>，历史命中 <hits> 次 / 误诊 <misdiagnoses> 次）
版本匹配：<完全匹配 | version_mismatch：本 case 在 <versions> 验证、客户是 <customer versions>——慎用>
匹配症状：<本轮匹配到的 symptoms>
root cause：<root_cause>
fix：<fix>（fix_type: <env-var|config-change|code-patch|pending-investigation>，severity: <benign|service-affecting|data-loss-risk>，<fix_side_effects>）
  → fix_type 决定呈现：env-var/config-change 直接给可执行命令；code-patch 给改动文件+diff 要点（不可直接执行）；pending-investigation 给排查建议
rollback：<rollback>
应用后检查：<怎么验证 fix 生效>
```

**confidence 校准**（给工程师判断该多信）：`>0.8` 高可信，直接应用；`0.5–0.8` 中可信，应用同时准备 plan B；`<0.5` 仅作提示，重点靠手动排查。把标尺讲出来，别让工程师猜 0.86 是高还是中等。

## severity 闸门（命中后先看这个）

读候选 case 的 `severity` 字段，决定输出策略：

- `benign` → 直接给 fix
- `service-affecting` → 给 fix，但标注 `fix_side_effects`（如 requires-restart），让人协调窗口
- `data-loss-risk`（如"checkpoint 可能被污染"）→ **不直接给 fix**，输出"先停训练、保留现场、通知 owner"。高危 root cause 的正确动作是 halt 不是 patch

每个 `fix_on_mismatch` 都带 `rollback`——人应用失败时能回退。

## 每步必写 trace（硬要求）

每个 step 后往 `diagnosis_state-<session_id>.yaml`（每个并发诊断一个独立文件，按 session_id 区分）的 `trace` 数组追加一条：
```yaml
- {step: N, action: triage|load_index|quickly_check|load_full|run_check|hit|miss|tier3|feedback|reference_lookup, ...}
```
trace 是误诊归因的唯一依据（见 references/diagnosis-procedure.md 末段"误诊归因"）：误诊时先读 trace 判断是 **case 错**（改库）还是**执行错**（改 skill）。不写 trace = 无法归因 = 可能改坏正确的 case。

## 不要做

- 不要替人决定 root cause——给结构化清单，人执行后贴回结果
- 不要连续尝试第三个 case——两次未解决即转人工（误诊保护的串联保护，见 references/diagnosis-procedure.md）
- 不要把全量 profiler 灌进 context——裁剪到相关 rank + 栈尾
- 不要用 interrupt 的 grep 思路建 precision 的 quickly_check（category 形态不同）
- 被打断 → `/skill:resume-diagnosis`
