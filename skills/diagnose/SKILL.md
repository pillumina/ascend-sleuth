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
> **续接**：若存在未完成的 `traces/*.yaml`（每个并发诊断一个文件），先问“有未完成的诊断，要 `/skill:resume-diagnosis` 续接吗？”——别让工程师自己记着跑 resume。

1. **收集症状 + 确认框架**（全部来自工程师提供的信息）
   - 错误信息、`HCCL_*`/`ASCEND_*`/`NPU_*` 环境变量值、**版本组合**（引擎版本 + CANN + HDK/驱动 + 架构 A2/A3/A5）——都从客户那要来
   - **信息不全就主动问**：若没说清，主动问——①症状（什么报错/什么时候挂）②客户的版本组合（引擎/CANN/HDK/架构）③日志/profiler 在哪（贴相关 rank + 栈尾）④**是否已在最新版本/镜像复现**（升过引擎/ascend 或换过镜像没——"升级即修复"类判据；ixn #3325 型教训，2026-09）。别干等
   - **框架从提供的信息/报错判断**（日志里 mindspeed/vllm 字样等）；判断不了就直接问工程师“客户跑的什么框架”，**不要跑 `pip list`**（那是你本地环境，跟客户无关）
   - **主动裁剪日志**：让工程师只贴失败 rank + 报错栈尾，绝不灌全量 profiler——诊断 session 的 context 八成是日志，全量灌进来会滑出 smart zone（~120K token 推理最锐利），推理质量暴跌。**若工程师已贴全文：agent 自行裁剪进 context（保留失败 rank + 栈尾 + 相关段），不要求工程师重贴**——裁剪是 agent 的职责，不是让工程师反复操作

2. **分类 → 加载 `triage-tree.yaml`（Tier 1）**
   - 症状匹配分支 → 路由到 namespace（先 `training|inference/<framework>/`，再 `common/`）
   - **triage 决策记进 trace**（命中哪个分支、路由到哪些 namespace、category）
   - triage 多分支弱匹配/置信度低 → **优雅退化**：加载所有 namespace 索引让 quickly_check 筛（索引便宜，退化成本可控）
   - 框架未检测到 → 只搜 `common/`；无法分类 → 直接 Tier 3
   - **triage 未命中（无分支匹配）→ agent 语义路由兜底，不直接 Tier 3**：报错/症状里没有 triage 正则能识别的信号时，agent 用自己的语义理解判断 namespace 与 category（如"训练卡住"→ `training/<framework>/` interrupt、"投机接受率下降"→ `inference/<framework>/` performance），记进 trace `{action: triage_semantic, namespace, category, rationale}`——语义路由结果可审计、可成为 groom 学习路由错例的数据源；语义也分不出 → 才 Tier 3

3. **两阶段加载 Tier 2**
   - **阶段一**：读**命中 namespace 的索引分片** `knowledge/_index/<namespace>.yaml`（`scripts/build_index.py` 生成；文件名 `/`→`__`，如 `inference__vllm-ascend.yaml`；分片缺失时回退总表 `knowledge/_index.yaml`）——**只读命中分片、不读整库总表**（F1 EV-2026-022）。分片为**瘦身行**（F2 EV-2026-023）：含 `id/title/symptoms(首条摘要≤120字)/category/confidence.score` + `file` 定位（**无 quickly_check——已移 case 本体**；hits/misdiagnoses 也不在索引里，留 case 本体）。用 标题+症状摘要+category+score 过滤候选 ≤5（score 排序）；检查项缺信息时，记下要向客户补要什么。索引缺失或 `--check` 报过期 → 兜底：逐文件只读上述索引字段，并提醒跑 `scripts/build_index.py` 重建
   - **空库提示（冷启动）**：若命中 namespace 为空（还没 case），**不要静默退化**——告诉用户“当前 `knowledge/<ns>/` 还没有验证过的 case，你可以：①继续深度排查（步骤 5）②诊断完跑 `/skill:to-postmortem` 沉淀成第一条 case ③转人工”。别让空库的体感是“这玩意啥也不会”。
   - **quickly_check 验证在阶段二（case 本体，F2）**：阶段一已用 标题+症状摘要 筛候选 ≤5，
     阶段二加载候选全文后以 quickly_check（primary→fallback）对照信息验证——primary 不匹配
     但 fallback 匹配 → 仍进验证，标记 `low_confidence`
   - **category 决定 quickly_check 形态**：interrupt 用 grep 错误签名、precision 用数值阈值（`loss>1e3`、`has_nan`）、performance 用 profiler 指标（`comm_ratio>0.4`）——别混用
   - **双面族交叉检索（E2-1，2026-09）**：接受率/投机效率退化是"双面"——无输出内容错误 → performance 族（如 VLLM-ASC-14306）；伴随输出错误/乱码/数值损坏 → precision 族（如 11127/12723）。当命中分支的候选 quickly_check 全部无匹配、且症状属接受率/投机/输出退化族时，**交叉检索另一 category 的对应族**（performance 无匹配 → 查 precision 接受率/输出族；precision 命中但症状为纯效率退化 → 反向），并记进 trace `{action: cross_category_retrieval, from, to}`——避免精度面 case 在性能路由下不可达
   - **阶段二**：全量加载候选，按 `confidence.score` **降序**进入验证。**多条候选时明示**：“匹配到 N 条候选，先验证最可能的 `<id>`（confidence `<score>`）”，让工程师有数；工程师可说“跳过这条试下一条”

### 2.5 reference 辅助查询（先验知识层）——候选加载后、验证前

按需取先验知识辅助诊断，**只读 `status: active` 的词条**（draft / pending-review / deprecated 一律不加载——未验证知识不进上下文）：

- **① 候选 case 显式引用**：候选 case 有 `ref_knowledge` 字段 → 加载其引用的 reference 词条全文（最精准；当前 case 尚无该字段，此路为未来路径）；
- **② 平台匹配的 summary 层（只限背景类 type）**：从症状收集阶段确认的客户平台，扫 `references/<type-dir>/*.yaml` 中 type 属于**背景类**（`platform-fact` / `software-fact` / `tool` / `methodology`——承载"有哪些平台事实/工具/方法论可用"的背景）且 `applies_to.platforms` 匹配该平台且 `status: active` 的词条，**只读 `summary` + `applies_to` 字段**（每条一行，低 token）作平台背景提示，**不读全文**。**查表类（`error-code` / `fault-pattern` / `env-var-table` / `compat-matrix`）不进 summary 层**——它们是码/签名/组件名/版本检索键，按需走 ③；其 summary 只是"族/域/表有几条"的索引信息，对诊断背景无价值，且 cross 全匹配会让它随表数线性膨胀（93 词条时 summary 层 4.5K token、其中查表类占 2.8K，2026-08 实测）。**匹配语义**：`applies_to.platforms` 含客户平台标识、或含 `cross`（跨平台成立，匹配所有平台）、或词条未填 platforms（视为跨平台）即命中；平台标识开放（如 `Atlas 200I/500 A2`），按客户实际报告的平台匹配，不限定型号清单；
- **③ 签名/查表类检索（error-code / fault-pattern / env-var-table / compat-matrix，不走 summary 层——签名/名是检索键不是摘要）**：症状里出现**错误码**（E1xxxx/EIxxxx/507xxx 等）→ 查 `ascend-error-code-structure` 的 `module_files` 前缀映射定位族文件（`references/errors/<族>.yaml`），族内 grep code 读 meaning/solution；症状含**可 grep 的故障签名**（如 "0x800000"、fault kernel_name、"I2C WRITER DATA error"、event_id）→ 按主题域定位 `references/fault-patterns/<域>.yaml`，域内 grep symptoms 命中读 cause/fix；诊断涉及**具体环境变量**（如怀疑 ASCEND_GLOBAL_LOG_LEVEL 配置）→ 按模块定位 `references/env-vars/<表>.yaml`，表内 grep name 读 description/example；**版本组合需核对**（报错指向 torch-npu/CANN 版本不匹配、或框架↔依赖版本越界）→ 按传导链分层定位 `references/compat-matrices/`：framework 层（vllm-ascend↔torch-npu+torch，按组件名定位文件）→ adapter 层（torch-npu↔CANN，`torch-npu-cann.yaml`）→ base 层（CANN↔HDK），从命中的层开始、必要时沿 `related_references` 向下游传导；
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
     2. **获取源码（本地优先，按平台选工具）**：
        a. **先查本地**——问用户一句"本地是否已有 <repo> 源码？"（默认先查约定位置 `<repo根>/src-code/<org>/<repo>/`，用户也可给任意路径）。本地已有 → 直接用，并用 `git -C <path> log -1` 或版本文件**核对版本与客户环境 compat 匹配**；版本不符 → 提示切到对应 tag 或按需拉对应版本（不假设本地副本就是对的）；
        b. **本地没有 → 按需拉取（统一 git clone，公开仓库无需认证）**：
           - `git clone <url> -b <tag/commit>`——URL 按平台：GitHub `https://github.com/<org>/<repo>.git`、Gitee `https://gitee.com/...`、GitCode `https://gitcode.com/...`；git 协议通用，公开仓库直接 clone；**`-b <tag>` 拉取失败（tag 不存在）时，先 `git ls-remote --tags <url>` 查真实 tag 再试**（不同版本库 tag 命名不同，如 v0.21.0rc2 实际可能是 v0.21.0rc1 或 releases/ 前缀）；
           - 公司内网（CodeHub 等）/私有仓库：**用户提供 URL**（其环境已配置凭据则直接 `git clone`）——agent 不碰内网认证/凭据；
           - **只取单文件**（不想拉全仓）时：GitHub 用 `gh api repos/<repo>/contents/<file>?ref=<commit>`（已登录 gh），其他平台用其 API 或 raw 链接；
            - **外部资料多源获取纪律（HuggingFace 模型文件等）**：诊断需核对模型 config/权重（model_type/architectures/量化参数）等公开文件时——主站不可达**不等于数据不存在**，先多源尝试再判"客观缺失"：
              - huggingface.co 主站可能不可达/超时（本环境实测 2026-09）→ 试 **hf-mirror.com** 镜像（`curl -sL https://hf-mirror.com/<org>/<model>/resolve/main/config.json`）；
              - 模型 repo 多在 HF **不在 GitHub**（`gh api` 404 是常态，不是模型不存在）——查 GitHub 不是正确路径；
              - 每次尝试（含失败）记入 trace 的 `tool_calls`（见"每步必写 trace"）——"哪个源不可达"是可复用教训，备选源清单由此持续沉淀；≤3 种源仍拿不到才如实标缺口；
        **不维护多版本、不落库**——只拉当前分析需要的文件或 checkout 到对应版本；
     3. **grep 定位**：搜报错签名/算子名/函数名（如 `grep -rn "QuantBatchMatMulV3" vllm_ascend/`）→ 读相关文件片段 → 分析根因（为什么这么实现、什么版本引入了什么行为）；
     4. **追问用户验证**：让用户对照预期/复现/补环境信息，验证根因假设；
     5. **follow-up（定位根因后，按序做）**：
        a. **查知识库是否已覆盖**——grep `knowledge/` 与 `references/` 是否已有该根因：有 → 标注"已覆盖（复用 `<case-id>`/`<ref-id>`）"，不重复沉淀；
        b. **上游修复检查**（环境可访问 issue/PR 时，如 gh 已登录）——`gh search issues "<报错签名或根因关键词>" --repo <repo>` 与 `gh search prs`：是否已有修复、合入到哪个版本（tag/commit/PR 号）→ 更新结论：已修复 → fix = 升级到修复版本（compat 标注触发/修复区间）；未修复 → 根因 + workaround + 建议提交/跟踪；
        c. **环境不可访问上游**（内网等）→ 诚实说明"无法查证上游是否已修复"，给根因 + workaround，建议联系技术支持或手动查上游；
    6. **多层级**——根因不在本仓时：报错指向更底层开源仓（如 torch-npu）→ 用同样流程分析其源码（`source_ref` 指向该仓）；CANN 等未开源仓 → **承认局限**（无法源码分析），给根因方向 + 建议联系华为；
    7. **沉淀 case**（根因定位清楚且知识库未覆盖时）：`/skill:to-postmortem`，记 `source_ref: {repo, ref, file, line}`（ref 用分析所用版本）。trace 记 `{action: source_analysis, repo, ref, files_read, followup: fixed|unfixed|unknown}`。
        - **顺手沉淀稳定结构事实（非事故绑定的源码知识）**：若源码分析揭示的是**独立于本次事故、跨事故可复用**的稳定结构事实——仓库架构/文件布局（如"vllm-ascend 量化配置在 modelslim_config.py"）、框架自定义 env var（CANN 文档没有的 `VLLM_ASCEND_*`）、版本兼容矩阵（按传导链分层：framework 层如 vllm-ascend↔torch-npu 来自 pyproject.toml、adapter 层 torch-npu↔CANN 来自官方 COMPATIBILITY）——**顺手走 `/skill:to-reference`** 沉淀为 reference（software-fact / env-var-table / compat-matrix）。判据：这个事实"6 个月后 / 跨版本是否仍成立"——**是** → 沉淀；**否**（行为随版本变）→ 不沉淀，留给 case（source_ref 已记）或 case 归纳路径。证据用同一 `source_ref` 代码指针 + 版本 pin（ref 用分析所用版本）+ `verification` 如实标注（auto-extracted / cross-checked-source）。**沉淀与否不影响本次诊断收尾**——reference 是导航辅助（不参与本次命中判定），沉淀失败也直接继续；勿为沉淀打断定位主流程。
     **边界**：源码分析可能耗时（token/时间）——先判断"疑似源码层"再走（不是每个未命中都 clone）；用户可随时终止（"跳过源码分析"）；拿不准根因不要硬下结论，联系技术支持。
   - 都没有 → 诚实说“知识库没覆盖这个问题，需手动排查；定位完用 `/skill:to-postmortem` 沉淀，下次就能命中”。人 + agent 联合分析

6. **产出**
   - `resolution: resolved | escalated | unknown`
   - **写顶层 `summary`（问题背景段，人一眼看懂，不必逐个打开证据）**：整合多轮用户输入 + 环境 + 关键报错为 1-3 句连贯描述——"用户报告 <什么问题>。环境 <框架/平台/配置>。关键报错 <签名>。已定位 <结果>/待定位"。面板展开时直接显示；跨 agent/session 时新 agent 靠它快速重建背景（不必重读全部证据）
   - **沉淀状态（`sedimented` 字段，零推断写入）**：顶层记录沉淀状态，**所有状态在"动作发生时"写入，不靠反查 inbox 推断**：
     - `state: none`（默认，未沉淀）→ `submitted`（执行过 to-postmortem，草稿在 inbox）→ `knowledge`（已升 Tier 2 active case）/ `archived`（仅转正 Tier 3 语料，非 active case）
     - **`submitted` 由 to-postmortem 产出草稿时写**；**`knowledge`/`archived` 由用户在面板"标记已转正"（或对话确认）时写**——转正是用户/owner 的动作，动作发生时写，不推断
     - **`knowledge` vs `archived` 必须区分**（诚实退化）：knowledge=下次诊断可命中；archived=仅 Tier 3 语料（grep 兜底），**不把 Tier 3 当 active case 卖**
     - **拒绝不记录**：用户拒绝沉淀是会话内交互决策，不持久进 trace——面板无标记，用户随时可重新沉淀
   - **Tier-2 命中**：常规 postmortem 草稿
   - **Tier-2 未命中但最终解决**：postmortem 含一段你起草的**候选 case**（quickly_check + diagnosis + confidence 低），交 `/skill:knowledge-groom` 验证
   - 完整 trace 随 `traces/<session_id>.yaml` 留存（每并发诊断一文件；模板见 `diagnosis_state.yaml.example`）
   - **结果反馈闭环（闭合学习环，关键）**：给完 fix 后，**等工程师应用并回来报告结果**——问“应用后解决了吗？（解决 / 没解决 / 部分解决）”。结果写回该 case 的 confidence：解决 → `hits += 1`；没解决 → `misdiagnoses += 1`、更新 `last_hit`。**写回由 groom 周批的 `settle_trace_feedback.py` 统一结算**（只读 trace 的 feedback 事件、幂等、批量走 PR）——本 skill 只负责把反馈结果记进 trace（`{action: feedback, case, outcome}`），不直接改 case 文件。**不问这步，confidence/误诊率永远是初始值，整个学习机制空转。**
   - **反馈捕获结构化（不靠记性）**：给完 fix、session 收尾前，往 state 文件写 `feedback_pending: <case-id>`。**每次 `/skill:diagnose` 或 `/skill:resume-diagnosis` 启动时先扫活跃 state 文件**——发现该标记就先追问"上次 <case-id> 的 fix 应用后解决了吗？"，按答复回写 confidence（上条规则）、trace 记 `{action: feedback, case, outcome: resolved|not_resolved|partial}`、清掉标记。反馈捕获是整条学习环的吞吐上限——标记写在文件里，就不依赖任何人的记性
   - **误诊归因（反馈 not_resolved/partial 时必做，不靠用户提）**：答复为**没解决/部分解决**时，**当场读本 session 的 trace 归因**——判断是 **case 错**（quickly_check 按序执行、check 结果对，但 root cause 判断错 → 改库）还是**执行错**（跳过 fallback、加载错 namespace、漏标低置信 → 改 skill 流程），trace 记 `{action: attribution, verdict: case_error|execution_error, evidence: <trace 证据摘要>}`——归因结论结构化落点，是「执行-误诊归因比」指标与 E2/E5 自演进的数据源。归因结论由你在本次 session 输出给工程师（"这属于 case 错/执行错，建议改哪"），实际修改走 PR（knowledge_modification / structure 模板），**人确认后合入，你不直接改库**。没解决但 trace 缺失 → 如实说明"无法归因（无 trace）"，不猜
   - **执行错归因下沉到组件（L2 流程自演进数据源）**：归因判定为**执行错**时，进一步定位到**组件**（可寻址执行单元：triage 分支名 / quickly_check id / skill 步骤号 / script 文件名 / 提示词段），trace 的 attribution 事件加 `component: <组件ID>` 字段——归因事件是 L2 流程自演进的数据本体（**无预建台账表**：深度轮/季度需要时 `scripts/component_tally.py` 从 traces 按需聚合失败簇，有簇才考虑产修复候选，见 evolution-pipeline.md §2）。组件 ID 用稳定可寻址格式：`triage:<分支名>` / `check:<id>` / `skill:<skill名> step<N>` / `script:<文件名>`。判定不了具体组件 → 如实不填（不编造），按需聚合时以"未归因"计数
   - **反馈追问降级（体验，防骚扰）**：同一 `feedback_pending` 标记**追问 2 次未获回应 → 停止追问**，标 `feedback_stale: true`（保留标记供 trace_metrics 统计"反馈缺失"），不再每次启动骚扰工程师。工程师之后主动回报仍可回写——追问是礼貌提醒，不是逼迫
   - **沉淀已含在本步骤**：命中=常规 postmortem、未命中=含候选 case 的 postmortem，本步骤已生成。**只有当本次不是经 /diagnose 定位的**（如用 Kimi/手工查的、或没配 session-end hook 导致 postmortem 没生成），才需 `/skill:to-postmortem` 手动沉淀。

## 命中时的输出格式

命中一条 case 后，给工程师**结构化、可追溯**的输出（别只甩一句 fix）——**透明性（C）**：不只给结论，给"为什么是这条"的完整推理链，让工程师能验证而不是盲信：

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

**强度标注纪律**（诚实退化，别让工程师把推测当已验证）：
- `已验证` = 本轮 trace 实际执行过（run_check match / quickly_check 结果）
- `推测` = 依赖推断（版本软匹配降级、根因类比未直接验证）——必须标出来
- `数据` = 历史积累（confidence/hits，非本轮判断）

**confidence 校准**（给工程师判断该多信）：`>0.8` 高可信，直接应用；`0.5–0.8` 中可信，应用同时准备 plan B；`<0.5` 仅作提示，重点靠手动排查。把标尺讲出来，别让工程师猜 0.86 是高还是中等。

## severity 闸门（命中后先看这个）

读候选 case 的 `severity` 字段，决定输出策略：

- `benign` → 直接给 fix
- `service-affecting` → 给 fix，但标注 `fix_side_effects`（如 requires-restart），让人协调窗口
- `data-loss-risk`（如"checkpoint 可能被污染"）→ **不直接给 fix**，输出"先停训练、保留现场、通知 owner"。高危 root cause 的正确动作是 halt 不是 patch

每个 `fix_on_mismatch` 都带 `rollback`——人应用失败时能回退。

## 每步必写 trace（硬要求）

每个 step 后往 `traces/<session_id>.yaml`（每个并发诊断一个独立文件；模板见 `diagnosis_state.yaml.example`）的 `trace` 数组追加一条。**trace 是完整交互轨迹（trajectory）**——统一 `{role, ...}` 结构：

```yaml
# agent 决策事件（机器标签 action + 给用户的内容 output + 决策依据 reason）
# attribution 事件在 verdict=execution_error 时可选加 component: <组件ID>（执行错归因下沉，见"误诊归因"节）
# source_analysis 事件在深度排查用工具查证时必记 tool_calls（评测可复核
#   "agent 试了什么才说缺 X"）——格式 [<工具/命令>: <拿到什么关键证据/失败原因>]，如
#   ["curl hf-mirror.com/.../config.json: HTTP 200, model_type=qwen3_vl",
#    "curl huggingface.co/.../config.json: 超时"]。多次尝试不同来源/策略都要记（含失败）
#   ——失败尝试是"该源不可达"的可复用教训（副产品：备选源/镜像清单由此沉淀）
- {role: agent, step: N, action: triage|load_index|quickly_check|load_full|run_check|hit|miss|tier3|feedback|reference_lookup|triage_semantic|source_analysis|attribution|resume, output: <给用户的内容>, reason: <决策依据/推理过程>, ...}
# user 输入事件（content 摘要 + evidence 完整证据——跨 agent/session 自包含的关键）
- {role: user, step: N, content: <用户输入摘要（短，供面板快速浏览）>,
   evidence: {inline: <完整原文>, files: [<相对路径>], sources: [<URL>], missing: <已知缺口>}}
```

- **时间戳（必写，供面板排序/显示）**：建 session 时写顶层 `created_at: <ISO 时间>`；**每次写 trace 更新顶层 `updated_at: <ISO 时间>`**（含 resume 续接——续接刷新 `updated_at` 使该 session 在诊断面板置顶）。面板按 `updated_at` 倒序排列、显示"更新 X 前"。缺时间戳的历史文件回退用 session_id 日期前缀（天粒度）
- **user 事件必记（content 摘要 + evidence 完整证据，缺一不可）**：每次用户贴输入（症状、日志、回答追问），记 `{role: user, step, content, evidence}`——
  - `content`：**摘要**（短，供面板列表/快速浏览，token 纪律）
  - `evidence`：**完整证据**（跨 agent/session 自包含的唯一载体——跨 agent 时平台 memory 不可用，新 agent 只能靠 trace 里的证据重建）：
    - `inline`：完整原文（报错栈/命令/环境表，<2K 字符直接内联）
    - `files`：附件/日志文件（大文件，**相对仓库路径**，下载到 `traces/evidence/<session_id>/` 再引用——跨 agent 同一工作区可直接读）
    - `sources`：外部来源 URL（issue/文档链接）
    - `missing`：已知缺失但诊断需要的证据（诚实标注，跨 agent 时新 agent 知道还缺什么）
  - **写入纪律：用户贴的日志/报错/命令不得只写摘要**——短的内联 `inline`、长的落文件进 `files`。这是 fixture 输入（`replay_trace.py` 取 `evidence.inline`）与跨 agent resume 的基础
- **agent 事件分两层（output 给用户 / reason 记决策依据，缺一不可）**：
  - `output`：给用户看的内容（可精简）——透明性（C）的呈现层
  - `reason`：**决策依据/推理过程**（回放、误诊归因、知识沉淀的证据）——**关键决策必写**：triage 路由（为什么命中此分支）、quickly_check 排除（比对了哪些候选、为何排除）、hit/miss（证据链、比对结果）、reference 甄别（为何部分适用/不适用）、根因判断（证据→结论）。**output 和 reason 分开**：结论简洁，推理要完整（如 #13688 的最小复现矩阵是 miss 的最有力证据，必须进 reason）
- **反馈闭环**：反馈确认后，顶层 `feedback: {case, outcome, confirmed_at}` 要填——`status=resolved 且 feedback.outcome=resolved` 是该 trace 升格为 fixture（强断言基准）的资格条件
- 词表与 `scripts/trace_metrics.py` 的 `KNOWN_ACTIONS` 保持一致（词表外 action 会被指标脚本报为纪律违规）；新增 action 必须两处同步。user 事件无 action，不参与词表检查

trace 是误诊归因的唯一依据（见 references/diagnosis-procedure.md 末段"误诊归因"）：误诊时先读 trace 判断是 **case 错**（改库）还是**执行错**（改 skill）。不写 trace = 无法归因 = 可能改坏正确的 case。

## 不要做

- 不要替人决定 root cause——给结构化清单，人执行后贴回结果
- 不要连续尝试第三个 case——两次未解决即转人工（误诊保护的串联保护，见 references/diagnosis-procedure.md）
- 不要把全量 profiler 灌进 context——裁剪到相关 rank + 栈尾
- 不要用 interrupt 的 grep 思路建 precision 的 quickly_check（category 形态不同）
- 被打断 → `/skill:resume-diagnosis`
