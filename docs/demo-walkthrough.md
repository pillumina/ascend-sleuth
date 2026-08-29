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

agent 分四步处理，每步都有明确输出：

**① Tier 1 路由**——triage-tree 把症状映射到命名空间：

```
[示例输出] 症状路由：interrupt（aicore exception / 算子执行失败）
→ namespace: inference/vllm-ascend/interrupt
```

**② Tier 2 候选**——读 `_index.yaml` 过滤候选（≤5），按 confidence 排序：

```
[示例输出] 匹配到 1 条候选：
VLLM-ASC-10122  confidence 0.4
  310P + w8a8 推理 507015 aicore exception：QuantBatchMatMulV3 量化算子 CANN 版本 bug
```

**③ 2.5 层 reference 辅助**——报错里的错误码走签名检索，命中先验知识：

```
[示例输出] 错误码 507015 → references/errors/cann-runtime.yaml：
  507015：aicore execution 异常（QuantBatchMatMulV3 量化算子在该 CANN 版本 bug，
  310P w8a8 推理触发；升级 CANN ≥9.1.0.beta2 修复）
```

**④ 验证 → 输出**——diagnosis checks 对照客户信息，过 severity 闸门后给 fix：

```
[示例输出] 验证：
  1. 症状判别：QuantBatchMatMulV3 + 507015？ → 是
  2. 版本判别：CANN < 9.1.0.beta2？ → 需要客户确认
  3. 修复：升级 CANN ≥9.1.0.beta2（修复合入 beta2 分支）

severity: service-affecting（推理中断，升级需重启）
fix: 升级 CANN 到含 QuantBatchMatMulV3 修复的版本（≥9.1.0.beta2），同步升级 vllm-ascend 镜像
⚠️ fix 是建议，由人应用到客户环境；agent 不自动改生产

[trace] 已记录 diagnosis_state-*.yaml（路由/候选/reference_lookup/验证每一步）
```

**读到这里你会看到**：诊断是「词法检索 + 语义判断」的组合——路由/候选是结构化的，参考命中是签名 grep，语义归一和验证由 agent 完成。

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
