# 全流程演示：从一次诊断到知识演化

这份文档带你把系统完整走一遍：一次真实诊断开始，到知识沉淀、批量导入、门控审核，最后知识反哺诊断。**读者视角**——你不需要操作，跟着每一步的输入与输出理解系统做什么、为什么。

> 示例输出基于真实知识库（42 条 case、94 条 reference）构造，标注「示例输出」；实际运行结果因输入而异。交互式架构图可随时打开对照：[ascend-sleuth-architecture.html](diagrams/ascend-sleuth-architecture.html)。

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
[示例输出] 候选比对（_index.yaml 19 条 interrupt）：
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

拿到版本后，agent 综合 case 的 fix 与 reference 的 solution 输出结论：

```
[示例输出] 版本 9.1.0.beta1 → 命中修复判定（< beta2）：
severity: service-affecting（推理中断，升级需重启）
fix: 升级 CANN ≥9.1.0.beta2（QuantBatchMatMulV3 修复合入 beta2），同步升级 vllm-ascend 镜像
⚠️ fix 是建议，由人应用到客户环境；agent 不自动改生产

[trace] 已记录 diagnosis_state-*.yaml（路由/候选/reference_lookup/追问/验证每一步）
```

**如果候选未命中**，agent 不会硬套——走 Tier 3 检索，**问题疑似源码层时进入源码分析**（常见场景：报错签名指向框架代码/算子）：

```
[示例输出] 候选全部未命中 → 深度排查：
  检索 postmortems/（Tier 3）→ 无覆盖
  判断：报错 KeyError: 'model.layers.N.self_attn.indexer.wq_b.weight'，
        指向量化描述表（modelslim_config）→ 疑似源码层，进入源码分析
  ① 确认版本：vllm-ascend 0.21.0rc2（需要向客户确认，不猜）
  ② 获取源码（本地优先）：
     "本地是否已有 vllm-ascend 源码？（默认我查 src-code/vllm-project/vllm-ascend/，也可以告诉我路径）"
     - 客户本地已有 → 直接用它，git log 核对版本（不符则切对应 tag）
     - 本地没有 → git clone（公开仓库无需认证）：
       git clone https://github.com/vllm-project/vllm-ascend.git -b <0.21.0rc2 tag>
       （或只取单文件：gh api contents/vllm_ascend/quantization/modelslim_config.py?ref=<commit>；
       Gitee/GitCode/内网 → git clone 对应 URL，内网 URL 由客户提供）
  ③ 读码定位：get_linear_quant_type → quant_description[prefix + '.weight']
     → GLM-5.2 新增 indexer 注意力层的权重 key 未在量化描述表中覆盖 → KeyError
  ④ 追问验证：请客户确认该版本 modelslim 描述表是否含 indexer 权重 → 确认缺失
  ⑤ 根因定位 → 沉淀 case（/skill:to-postmortem，
     source_ref: vllm_ascend/quantization/modelslim_config.py:<commit>）

  边界：源码分析可能耗时（token/时间）——agent 先判断"疑似源码层"才走；
  客户可随时说"跳过源码分析"；拿不准根因不硬下结论，转技术支持。
```

**读到这里你会看到**：未命中不是终点——agent 会按需取源码、读代码定位、再追问验证，最后把定位沉淀成 case（带 source_ref 代码指针）。这正是"知识随使用变厚"的来源：**很多问题都要基于源码看为什么，看懂了就变成 case，下次同类直接命中**。

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

先验知识（独立于事故的事实/方法论）走 `to-reference`：

```
/skill:to-reference --ingest-cases "[VLLM-ASC-12461, VLLM-ASC-14166, VLLM-ASC-10944, VLLM-ASC-10122]"

[示例输出] 识别共性：MoE 通信/路由/量化算子故障族（4 条 case 同 tag: moe）
→ 提炼 methodology：ascend-moe-comm-triage（4 形态分流排查）
→ draft 直进 references/methodologies/（status: draft，PR review 即审核闸门）
```

批量吸收上游 issue 走 `issue-ingest`：

```
/skill:issue-ingest --repo vllm-project/vllm-ascend --labels triaged

[示例输出] 拉取 555 条 triaged issue（精简元数据，≈0 token）
[示例输出] 硬过滤：已处理 191 / 评论少 138 / 标题规则 45 → 20 条候选
[示例输出] 按评论数启发式排序，top 候选：
  #8938 [13评论][kv-cache-pool] P0/P1 同时拉起 ZMQ 端口抢占
  #6774 [13评论] qwen3.5 A2 双机启动失败（启动脚本路径）
  #10954 [12评论] GLM-5.2 工具调用传参错误（工具幻视）
[示例输出] 评估 3 条 → 沉淀 3 条 draft（new_pattern）→ 标记已导入（processed 196）
  同一仓库下次不再问配置（config 已固化：triaged 主池）
```

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

转正的知识走 PR，门控由 CI 强制：

```
[示例输出] knowledge_intake PR（参考真实 PR #45/#47）：
  预分诊结论（groom 产出）· 脱敏自查 · CI：build_index --check / verify_references
  kb-checks 三检查绿 → merge → 索引重建 → case 进入 Tier 2
```

**关键**：`inbox` 是本地待审队列（草稿不进 git/PR）；**转正才走 PR**——PR 审核看的是已分诊的变更，不是裸草稿。

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

---

## 收尾：回到架构图

打开交互架构图，你已经走完了上面两个循环的每一环：

- **诊断循环**：第 1 节（diagnose → 路由 → 候选 → 2.5 参考 → 验证 → trace）
- **演化循环**：第 2-3 节（沉淀 → inbox → groom 预分诊 → PR 门控 → 转正）
- **连接**：第 4 节（转正的 case/reference 回到诊断，R8 提炼共性）

系统的核心设计：**检索只负责提名，验证决定放行**；**建议与决定分离**（agent 产出建议，人审转正）；**知识随使用变厚**（每次兜底后沉淀，下次命中）。

---

## 附录：示例中的真实对应物

| 示例 | 真实位置 |
|---|---|
| 诊断场景（507015 / QuantBatchMatMulV3）| `knowledge/inference/vllm-ascend/interrupt/VLLM-ASC-10122.yaml` + `references/errors/cann-runtime.yaml` 507015 |
| 预分诊 variant 示例（9503 并入 12461）| PR #45 |
| 提炼示例（MoE 方法论）| `references/methodologies/ascend-moe-comm-triage.yaml` |
| issue-ingest 输出格式 | `docs/issue-ingest-pipeline.md` |
| 交互架构图 | `docs/diagrams/ascend-sleuth-architecture.html` |
