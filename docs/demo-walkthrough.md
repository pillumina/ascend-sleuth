# 全流程演示：从一次诊断到知识演化

这份文档带你把系统完整走一遍：一次真实诊断开始，到知识沉淀、批量导入、门控审核，最后知识反哺诊断。**读者视角**——你不需要操作，跟着每一步的输入与输出理解系统做什么、为什么。

> 示例输出基于真实知识库构造，标注「示例输出」；实际运行结果因输入而异（实时 case/reference 条数以 `knowledge/_index.yaml` 头注与 `verify_references.py` 为准，不在此硬编码）。交互式架构图可随时打开对照：[ascend-sleuth-architecture.html](diagrams/ascend-sleuth-architecture.html)。

---

## 0. 准备：clone 即用

```bash
git clone https://github.com/pillumina/ascend-sleuth.git
cd ascend-sleuth
```

仓库已跟踪 `.dsh/skills`（指向 `skills/` 的相对链接）。用 DSH 打开仓库目录，`/skill:` 列表直接出现六个 skill：

```
[示例输出] 可用 skills：
diagnose · to-postmortem · to-reference · issue-ingest · knowledge-groom · resume-diagnosis
```

其他 agent（Claude Code / Cursor / Codex…）跑一次 `bash scripts/enable-agent-skills.sh`，自动为已安装的 agent 建 symlink。

---

## 1. 一次诊断（诊断循环）

工程师把客户症状交给 agent：

```
/skill:diagnose

客户 310P 推理机，vllm serve 跑 Qwen3.6-27B-W8A8，推理时报错：
ERR00100 PTA call acl api failed, error code is 507015
AclNN_Runtime_Error(EZ9903): aclrtLaunchKernelWithHostArgs failed: 507015
Kernel task happen error, retCode=0x26, [aicore exception]
fault kernel_name=QuantBatchMatMulV3_NZ_NZ_int8_int8_fp16_high_performance_21
```

agent 先做**症状归一**——把原始报错提炼成可检索的签名，同时留意缺什么信息：

```
[示例输出] 症状理解：
  - 报错签名：507015（aicore execution 异常）+ QuantBatchMatMulV3（量化 matmul 算子）
    + retCode=0x26（aicore exception）——interrupt 类
  - 已给信息：平台 310P、框架 vllm serve、模型 Qwen3.6-27B-W8A8、w8a8 量化
  - 缺信息：CANN 版本（修复判定的关键）——先按已有信息走，验证阶段会问
```

**① Tier 1 路由**——triage-tree 把症状映射到命名空间：

```
[示例输出] 症状路由：interrupt（aicore exception / 算子执行失败）
→ namespace: inference/vllm-ascend/interrupt
```

**② Tier 2 候选**——读 `_index.yaml` 过滤候选（≤5），按 confidence 排序。agent 比对 quickly_check 与已提供信息，排除不匹配的：

```
[示例输出] 候选比对（_index.yaml 命中 namespace 的 interrupt 条目）：
  VLLM-ASC-10122  confidence 0.4  ← 症状签名命中（507015 / QuantBatchMatMulV3）
  其余候选：错误码/算子不匹配（507018 aicpu、507057 MTE、561000 缺二进制…）→ 排除
匹配到 1 条候选：VLLM-ASC-10122
```

**③ 2.5 层 reference 辅助**——报错里的错误码走签名检索，命中先验知识（agent 判断这条先验是否相关、怎么辅助）：

```
[示例输出] 错误码 507015 → references/errors/cann-runtime.yaml：
  507015：aicore execution 异常（QuantBatchMatMulV3 量化算子在该 CANN 版本 bug，
  310P w8a8 推理触发；升级 CANN ≥9.1.0.beta2 修复）
  → 与候选 case 的根因方向一致，先验佐证：量化算子版本问题，不是用户用法错误
```

**④ 验证 → 输出**——diagnosis checks 逐条对照客户信息。**缺信息时 agent 会停下问你**，不跳步：

```
[示例输出] 验证：
  1. 症状判别：QuantBatchMatMulV3 + 507015？ → 是（报错栈已确认）
  2. 版本判别：需要确认——客户当前 CANN 版本是多少？
     （升级修复判定依赖它：<9.1.0.beta2 触发，≥9.1.0.beta2 修复）
     → 请向客户补：cat /usr/local/Ascend/ascend-toolkit/latest/version.cfg
```

**用户回应**（agent 追问后，工程师向客户要到版本）：

```
版本确认了：9.1.0.beta1（客户回填 cat /usr/local/Ascend/ascend-toolkit/latest/version.cfg）
```

agent 综合 case 的 fix 与 reference 的 solution 输出结论：

```
[示例输出] 版本 9.1.0.beta1 → 命中修复判定（< beta2）：
severity: service-affecting（推理中断，升级需重启）
fix: 升级 CANN ≥9.1.0.beta2（QuantBatchMatMulV3 修复合入 beta2），同步升级 vllm-ascend 镜像
⚠️ fix 是建议，由人应用到客户环境；agent 不自动改生产

[trace] 已记录 traces/*.yaml（路由/候选/reference_lookup/追问/验证每一步）
```

**如果候选未命中**，agent 不会硬套——走 Tier 3 检索，**问题疑似源码层时进入源码分析**（常见场景：报错签名指向框架代码/算子）：

```
/skill:diagnose（续）
客户：8×Ascend，vllm-ascend 0.22.1rc1，NPU Graph 开启（默认）。
32 并发请求（~39K token 上下文）时 EngineCore 崩溃，全 8 rank 同时报：
aclnnScatterNdUpdate error 507011
[补] --enforce-eager（关 Graph）后 32 并发稳定（3200/3200 成功）

[示例输出] ① 症状归一：
  报错签名：aclnnScatterNdUpdate（KV cache 写入算子）+ 507011
  关键线索：只在 NPU Graph 开启时崩溃、--enforce-eager 后稳定 → 问题在 Graph
  capture 路径，不是算子本身
② 路由 → 候选：interrupt；knowledge grep "ScatterNdUpdate|507011|graph" → 无命中
③ reference：507011 未收录错误码表 → 先验不足，进深度排查
④ 判断疑似源码层：scatter + graph 指向 KV cache 写入源码路径 → 进入源码分析
   （会拉对应版本源码，可以吗？也可以说"跳过"）

用户回应：可以，继续（客户确认愿意等源码分析）
⑤ 版本 v0.22.1rc1 → src-code/ 无 → git clone -b v0.22.1rc1
⑥ grep 定位：vllm_ascend/device/device_op.py:528  dsa_kv_compress_scatter
   → npu_scatter_nd_update_v2(cache, slot_mapping, x)
   读码：SWA/Compressor 的 KV 压缩写入路径——长上下文（39K）触发 compressor
   scatter 写回 cache，graph capture 模式下内部调用 rtMemcpy（graph 不支持
   memcpy）→ 底层 aclnnScatterNdUpdate 报 507011 → EngineCore 崩溃
⑦ 追问验证：--enforce-eager 稳定是否复现？是否只在长上下文时触发？→ 确认
⑧ follow-up（按序）：
   a. 查知识库是否已覆盖 → grep 无（507011 刚补录为错误码表条目，但无完整 case）
   b. 上游修复检查：gh search issues/prs "ScatterNdUpdate graph" → 未查到已合入
      修复 → 结论：上游未修复，给根因 + workaround（--enforce-eager，牺牲性能
      需权衡）+ 建议提交/跟踪上游
⑨ 结论 + source_ref：
   root cause: NPU Graph capture 下执行 KV scatter 写入（dsa_kv_compress_scatter），
     graph 不支持内部 rtMemcpy → 507011 崩溃
   mitigation: --enforce-eager（当前）
   source_ref: vllm-project/vllm-ascend@5f6faa0c: vllm_ascend/device/device_op.py:528
   trace: {action: source_analysis, repo, ref, files_read, followup: unfixed}
```

**多层级**：根因不在 vllm-ascend 时，agent 会继续往下看——torch-npu 等底层开源仓用同样流程分析（`source_ref` 指向该仓）；CANN 未开源则**承认局限**，给根因方向 + 建议联系华为。

**读到这里你会看到**：未命中不是终点——agent 按需取源码、读码定位、追问验证、**follow-up 检查知识库与上游是否已覆盖/修复**，最后把定位沉淀成 case（带 source_ref 代码指针）。这正是"知识随使用变厚"的来源：**很多问题都要基于源码看为什么，看懂了就变成 case，下次同类直接命中**。**读到这里你会看到**：未命中不是终点——agent 会按需取源码、读代码定位、再追问验证，最后把定位沉淀成 case（带 source_ref 代码指针）。这正是"知识随使用变厚"的来源：**很多问题都要基于源码看为什么，看懂了就变成 case，下次同类直接命中**。

**读到这里你会看到**：诊断是「词法检索提名 + agent 语义判断放行」——路由/候选/签名 grep 是结构化的，但症状归一、候选比对、缺信息追问、验证逐条、fix 综合、未命中转深度排查，全部是 agent 的理解与判断。**它是一个会追问、会解释、会承认不知道的排查协作者，不是查表器。**

---

## 2. 沉淀（诊断结束 → 知识入库预备）

任何来源的调查都能汇入。诊断完说「沉淀一下这次」，agent 自动触发：

```
[示例输出] /skill:to-postmortem 产出：
postmortems/inbox/VLLM-ASC-10122.case.yaml   # 结构化 case 草稿（draft）
postmortems/inbox/VLLM-ASC-10122.md         # 原始记录（指针式）
  状态：draft（待审队列，不进诊断上下文）
  pre-triage: new_pattern（507015 新错误码 + QuantBatchMatMulV3，与现有 case 无重叠）
```

先验知识（独立于事故的事实/方法论）走 `to-reference`——**与 case 沉淀不同，reference 产出即 `status: active`，PR review 即审核闸门，合入即生效**（无 draft 中间态：未合入的 PR 分支不 main，天然不进诊断上下文；深审门槛如 case-derived methodology ≥3 条 case 引用在产出时即由 CI 把关）：

```
/skill:to-reference --ingest-cases "[VLLM-ASC-12461, VLLM-ASC-14166, VLLM-ASC-10944, VLLM-ASC-10122]"

[示例输出] 识别共性：MoE 通信/路由/量化算子故障族（4 条 case 同 tag: moe）
→ 提炼 methodology：ascend-moe-comm-triage（4 形态分流排查）
→ active 直进 references/methodologies/（status: active，PR review 即审核闸门——合入即生效）
→ 深审门槛已满足：case-derived 4 条 case ≥ 3 ✓
```

批量吸收上游 issue 走 `issue-ingest`——**支持多源**（GitHub `gh` / GitCode `gitcode` CLI，缓存格式统一，框架差异参数化）：

```
/skill:issue-ingest --repo vllm-project/vllm-ascend --labels triaged

[示例输出] 拉取 500+ 条 triaged issue（精简元数据，≈0 token）
[示例输出] 硬过滤：已处理 191 / 评论少 138 / 标题规则 45 → 20 条候选
[示例输出] 按评论数启发式排序，top 候选：
  #8938 [13评论][kv-cache-pool] P0/P1 同时拉起 ZMQ 端口抢占
  #6774 [13评论] qwen3.5 A2 双机启动失败（启动脚本路径）
  #10954 [12评论] GLM-5.2 工具调用传参错误（工具幻视）
[示例输出] 评估 3 条 → 沉淀 3 条 case 草稿（进 inbox 待 groom 转正）→ 标记已导入
  同一仓库下次不再问配置（config 已固化：triaged 主池）
```

> GitCode 源差异（实测 mindspeed-llm）：不返回 `closed_at`（游标用 `updated_at` 近似）、无 `state_reason`（`resolved` label 映射为 completed）、`number` 为字符串需转 int——`fetch_issues.py` 以 GitHub 为例，其他源换 CLI 命令，缓存格式保持一致。

---

## 3. Groom 预分诊 + PR 门控（演化循环）

`knowledge-groom` 处理待审队列——**agent 给建议，人决定**：

```
[示例输出] inbox 预分诊（每条约 30 秒人确认）：
  VLLM-ASC-10122 → new_pattern（证据：507015 新码 + 根因不重叠）✅
  VLLM-ASC-9503  → variant_of: VLLM-ASC-12461
    证据：同算子（MoeDistributeDispatchV2）× 同网络（ROCE）高度重叠；
    增量 = 维护者确认 0.20.2rc1+ 修复（修正 12461 过时的"无官方修复"结论）
  → 建议并入 12461（扩 compat、补 fix），⚠️ 改 active case 的 compat → kb/high-risk 双签
```

**维护者确认**（人决定，30 秒/条）：

```
[示例输出] 维护者：accept 10122（new_pattern，证据成立）→ 升格 knowledge/
         accept 9503（variant_of 12461，同算子×同网络）→ 并入 12461（扩 compat、补 fix）
         12461 改动涉 compat → 双签：owner1 ✓ owner2 ✓
```

转正的知识走 PR，门控由 CI 强制：

```
[示例输出] knowledge_intake PR（参考真实 PR #45/#47）：
  预分诊结论（groom 产出）· 脱敏自查 · CI：build_index --check / verify_references
  kb-checks 三检查绿 → merge → 索引重建 → case 进入 Tier 2
```

**关键**：`inbox` 是本地待审队列（草稿不进 git/PR）；**转正才走 PR**——PR 审核看的是已分诊的变更，不是裸草稿。groom 周批先跑反馈结算（`settle_trace_feedback.py` 把上一周期用户反馈累积进 case 置信度），再做预分诊与转正——置信度重算的输入来自真实反馈，不是初始值（见第 4 节学习环）。

---

## 4. 知识反哺诊断（闭环）

转正后，新 case 进入 Tier 2、新 reference 进入 2.5 层。下一次同类问题：

```
[示例输出] 客户报 507015 aicore exception：
  候选命中 VLLM-ASC-10122（confidence 0.4，随 hits 反馈校准）
  → 直接给出 root cause + fix（升级 CANN ≥9.1.0.beta2）
  → 不用再走一遍深度排查
```

groom 的 R8 信号让共性提炼不靠人肉发现：

```
[示例输出] R8：同 tag case ≥3 → 建议 --ingest-cases
  moe 标签 4 条 case → 建议提炼（已产出 ascend-moe-comm-triage）
```

观测回写（groom R6）：reference 命中统计来自 trace 的 `reference_lookup` 事件——没有数据如实显示 0，等使用积累。

**置信度学习环（case 层，与 R6 对称）**——case 的 `confidence.hits/misdiagnoses` 来自**用户可信反馈**，不是系统命中：

```
[示例输出] 诊断后用户反馈（一次问答）：
  agent：升级 CANN 后应用了，解决了吗？
  用户：解决了 ✓（trace 记 {action: feedback, case: VLLM-ASC-10122, outcome: resolved}）

[示例输出] groom 周批结算（scripts/settle_trace_feedback.py）：
  结算：VLLM-ASC-10122 hits 0→1（resolved 才 +1；命中本身不计入——
    命中是系统检索行为，不代表 case 有效，可信反馈才是置信度信号）
  not_resolved / partial → misdiagnoses += 1
  幂等：按 session+事件序列 hash 记录在 ingest-state.json，重复跑不重复累积
  产出 diff → knowledge_modification PR（confidence 字段变更，走审核）
  → groom §4 再按 hits/misdiagnoses/last_hit 重算 score（时间衰减）
```

**为什么 resolved 才 +1**：命中是检索行为（可能碰巧加载、也可能候选未用），只有用户确认"这个诊断解决了我问题"才证明 case 真实有效。置信度从"初始先验"（新 case 按调查质量设 0.6/0.3/0.1）走向"实测后验"（反馈累积校准）——这正是 Beta 先验的意义：冷启动公平起点由先验，长期校准靠数据。

---

## 4.5 DSH 面板：诊断全流程的可视化操作台

在 DSH 中可通过动态 Cordis 插件把诊断面板挂进会话视图环（`conversation.view` 加"诊断"tab），将上面第 1-4 节的所有环节变成**可视化、可操作**的界面——这是本系统在 DSH 中的载体形态。

**面板提供的能力（与流程各环节对应）：**

| 面板能力 | 对应流程环节 | 说明 |
|---|---|---|
| 会话列表（状态徽章/更新时间/计数） | 诊断入口 | 按 `updated_at` 倒序，resume 续接后置顶 |
| 搜索框（session/状态/框架/命中 case） | 诊断入口 | 会话多时快速过滤定位 |
| 轨迹展开（summary/evidence/reason） | 诊断过程可视化 | summary=问题背景段；evidence=完整证据（inline 原文/文件引用/缺口）；reason=决策依据 |
| 参考层标注 | 2.5 层先验知识 | `reference_lookup` 步骤带紫色"参考层"徽章 + 使用统计 |
| 继续诊断（指令 copy → 对话触发） | resume | 未解决会话的续接入口，与 resume skill 闭环 |
| 沉淀此案例（指令 copy → 对话触发） | 沉淀（第 2 节） | 已解决未沉淀会话触发 to-postmortem |
| 沉淀状态（submitted/knowledge/archived） | groom 转正跟踪 | 零推断：动作发生时写，不反查 inbox |
| 证据文件点击打开 | 跨 agent 自包含 | `traces/evidence/<session_id>/` 本地文件 |
| 指标 tab（timeline 快照/kind 过滤/实时计算） | 自演进观测（第 3 节） | 展示 `metrics/timeline.yaml` 各期快照（live/replay/example 可过滤）+ 运行 trace_metrics.py 实时对照 |

**trace 自包含化**（面板 + 跨 agent/session resume 的数据基础）——user 事件升级为 `content`（摘要）+ `evidence`（完整证据）：

```yaml
# traces/<session_id>.yaml 顶层
summary: "用户报告 <什么问题>。环境 <框架/平台/配置>。关键报错 <签名>。已定位 <结果>"
sedimented: {state: submitted}   # none→submitted→knowledge/archived（零推断写入）

# trace 数组（user 事件）
- {role: user, step: 1, content: <摘要>, evidence: {inline: <原文>, files: [<相对路径>], sources: [<URL>], missing: <缺口>}}

# agent 事件：output（给用户）+ reason（决策依据，关键决策必写）
```

**为什么自包含**：跨 agent/session 续接时平台 memory 不可用，新 agent 只能靠 trace 重建——`summary`（背景）+ `evidence`（原始证据）+ `reason`（推理）三者齐备，新 agent 才能继续诊断而不丢上下文。证据大文件落 `traces/evidence/<session_id>/`（gitignored，跨 agent 同工作区可读）。

**沉淀状态语义**（区分三层，诚实退化）：
- `submitted`：执行过 to-postmortem，草稿在 inbox 待审
- `knowledge`：已升 Tier 2 active case——**下次诊断可命中**
- `archived`：仅转正 Tier 3 语料（covered/语料）——**grep 兜底，非 active case**
- **拒绝不记录**：用户拒绝沉淀是交互决策，不持久进 trace，随时可重新沉淀

**交互原则**：面板只生成指令（copy → 粘贴对话 → agent 执行），**最终交互始终在 agent 与用户之间**——面板是"指令生成器"，不做决策。沉淀/续接都要用户确认。

---

## 收尾：回到架构图

打开交互架构图，你已经走完了上面两个循环的每一环：

- **诊断循环**：第 1 节（diagnose → 路由 → 候选 → 2.5 参考 → 验证 → trace）
- **演化循环**：第 2-3 节（沉淀 → inbox → groom 预分诊 → PR 门控 → 转正）
- **连接**：第 4 节（转正的 case/reference 回到诊断，R8 提炼共性，置信度学习环结算反馈）
- **DSH 载体**：第 4.5 节（面板可视化操作台——诊断/resume/沉淀/证据全流程可视可操作，trace 自包含支撑跨 agent 续接）

系统的核心设计：**检索只负责提名，验证决定放行**；**建议与决定分离**（agent 产出建议，人审转正）；**知识随使用变厚**（每次兜底后沉淀，下次命中）；**置信度来自可信反馈**（resolved 才 +1，系统命中不计数）；**trace 自包含**（跨 agent/session 不依赖平台 memory，证据/推理完整可重建）。

---

## 附录：示例中的真实对应物

| 示例 | 真实位置 |
|---|---|
| 诊断场景（507015 / QuantBatchMatMulV3）| `knowledge/inference/vllm-ascend/interrupt/VLLM-ASC-10122.yaml` + `references/errors/cann-runtime.yaml` 507015 |
| 预分诊 variant 示例（9503 并入 12461）| PR #45 |
| 提炼示例（MoE 方法论）| `references/methodologies/ascend-moe-comm-triage.yaml` |
| 置信度学习环（反馈结算）| `scripts/settle_trace_feedback.py`（groom §3.5 结算 → §4 重算 score）|
| issue-ingest 输出格式 | `docs/issue-ingest-pipeline.md`（GitCode 源差异见 skill 文档）|
| 交互架构图 | `docs/diagrams/ascend-sleuth-architecture.html` |
| DSH 面板（诊断/resume/沉淀/证据）| 动态 Cordis 插件（`conversation.view`"诊断"tab）——traces/ 为数据源；trace schema 见 `diagnosis_state.yaml.example` |
