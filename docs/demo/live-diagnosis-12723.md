# 演示：首次真实诊断闭环（vllm-ascend #12723）

> **演示 PR——不合入。** 真实 trace 文件 `diagnosis_state-2026-08-27-glm5-rope-a3.yaml` 留在本地（含真实运行信息，`.gitignore` 设计上挡在仓库外）；本文件是**脱敏演示副本**，展示从真实用户输入到反馈闭环的完整流程。

## 一、这个演示展示了什么

运行性闭环（理论 §4.3）第一次被真实数据点亮——不是构造输入、不是回放，而是一条真实用户首帖走完 diagnose 全流程，产出真实 trace、真实反馈、真实 confidence 更新、真实指标：

```
真实输入（issue #12723 首帖）→ triage → 阶段一 → 阶段二 → 命中
  → trace 落盘 + feedback_pending → 工程师回报已解决
  → hits 0→1、score 0.6→0.73 → feedback_pending 清除 → 索引重建 → 指标回流
```

## 二、真实输入（脱敏摘录）

来源：[vllm-ascend issue #12723](https://github.com/vllm-project/vllm-ascend/issues/12723) 用户首帖。环境与症状关键信息：

- **平台**：Ascend A3（16 dies），driver 25.5.1
- **框架**：vllm 0.23.0 + vllm-ascend nightly-0.23.0-a3，torch_npu 2.10.0.post2，triton 3.2.0
- **症状**：GLM-5.2 DSpark speculative decoding（DP2/TP8/EP, eager）下，平台分发的 rotary embedding 路径返回非范数保持的 Q/K；`forward_native()` 在同一对象上输出正确，accept_len 从 ~3.0 恢复到 5.4-5.5
- **关键签名**：`accept_len`（标题即含判别信号）

## 二·五、模拟交互实录（工程师 ↔ agent）

> **形态声明**：本次诊断流程由 agent 按 SKILL.md 执行（非真实对话界面），以下实录为**演示化呈现**——输入与命中结果真实，对话措辞为演示格式。真实调用请按第三·五节脚本在装了 skill 的 agent 环境跑。

```
工程师：/skill:diagnose

客户 A3 (16 dies) 上 GLM-5.2 DSpark speculative decoding，driver 25.5.1，
vllm 0.23.0 + vllm-ascend nightly-0.23.0-a3，torch_npu 2.10.0.post2，triton 3.2.0。
platform-dispatched rotary embedding 路径返回非范数保持的 Q/K，accept_len ~3.0；
同一对象调 forward_native() 输出正确，accept_len 恢复到 5.4-5.5。

agent（step 1 triage）：检测到 vllm-ascend + precision 症状（accept_len/范数损坏），
路由到 inference/vllm-ascend/ + common/，category=precision。✓

agent（step 2 阶段一）：读索引该 namespace 19 条，用 quickly_check 对照已提供信息。
VLLM-ASC-12723 primary 命中（accept_len 签名）；VLLM-ASC-12642 primary/fallback 均不匹配，跳过。✓

agent（step 3 阶段二）：候选 1 条（VLLM-ASC-12723），按 score 降序验证。

agent（step 4 验证）：diagnosis 检查项对照——
  ① 症状判别：accept_len 异常 + forward_native 对照恢复？→ 匹配 ✓
  ② 版本/环境：A3-910C + triton 3.2.0 + vllm-ascend 0.23.0？→ 匹配 ✓
  命中确认，输出：

────────────────────────────────────────
命中 VLLM-ASC-12723（confidence 0.6，历史命中 0 次 / 误诊 0 次）
版本匹配：完全匹配（A3-910C，vllm-ascend 0.23.0）
匹配症状：Triton rope sin 偏移 → Q/K 范数损坏（accept_len 3.06 → 5.55）
root cause：vllm_ascend/ops/triton/rope.py 的 sin 缓存偏移用 pad 后 rotary dim，RoPE 退化
fix：升级到含 PR #12963 的版本，或修改 rope.py 两处——
     sin_offsets = cos_offsets + (rope_dim // 2)（锚定真实 rope_dim/2）
     （fix_type: code-patch，severity: service-affecting）
rollback：revert PR #12963 / 回退到修复前版本
应用后检查：accept_len 应回到 ~5.4-5.5
────────────────────────────────────────

agent：应用这个 fix 后，请回来告诉我结果——解决 / 没解决 / 部分解决。
（feedback_pending: VLLM-ASC-12723 已写入状态文件）

[工程师应用 fix，accept_len 恢复到 5.5，回报：已解决]

agent：反馈已记录——VLLM-ASC-12723 命中数 0→1，confidence 0.6→0.73。
下次同类问题将优先验证它。trace 已落盘。
```

## 三、诊断流程 trace（演示副本，与真实 trace 一致）

```yaml
session_id: "2026-08-27-glm5-rope-a3"
status: resolved
detected_framework: vllm-ascend
detected_platform: A3-910C
detected_category: precision

trace:
  - {step: 1, action: triage, branch: inference_precision, category: precision, routed: [inference/vllm-ascend/, common/]}
  - {step: 2, action: load_index, namespaces: [inference/vllm-ascend], n_cases: 19}
  - {step: 3, action: quickly_check, case: VLLM-ASC-12723, primary: pass}
  - {step: 3, action: quickly_check, case: VLLM-ASC-12642, primary: fail, fallback: fail, marked: skipped}
  - {step: 3, action: load_full, candidates: [VLLM-ASC-12723], order: by_confidence_score}
  - {step: 4, action: run_check, case: VLLM-ASC-12723, step: 1, result: match}
  - {step: 4, action: run_check, case: VLLM-ASC-12723, step: 2, result: match}
  - {step: 4, action: hit, case: VLLM-ASC-12723, confidence: 0.6}
  - {step: 5, action: feedback, case: VLLM-ASC-12723, outcome: resolved}
```

## 四、命中输出（diagnose 结构化产出）

```
命中 VLLM-ASC-12723（confidence 0.6 → 0.73，历史命中 1 次 / 误诊 0 次）
版本匹配：完全匹配（A3-910C，vllm-ascend 0.23.0）
匹配症状：Triton rope sin 偏移 → Q/K 范数损坏（accept_len 3.06 → forward_native 恢复 5.55）
root cause：vllm_ascend/ops/triton/rope.py 的 sin 缓存偏移用 pad 后 rotary dim，RoPE 退化
fix：合入 PR #12963（rope.py sin_offsets 锚定真实 rope_dim/2）
rollback：revert PR #12963
severity：service-affecting（精度输出错误，需重启窗口）
```

## 五、反馈闭环（学习环的关键动作）

| 事件 | 变化 |
|---|---|
| fix 应用，工程师回报"已解决"（accept_len 3.06 → 5.55 恢复） | trace 记 `feedback: resolved`，feedback_pending 清除 |
| confidence 回写 | hits 0→1，score 0.6→0.73（Beta 后验，last_hit 2026-W35） |
| 索引重建 | `build_index.py` 反映新 score（排序用） |

## 六、指标回流（trace_metrics.py 首次真实消费）

| 指标 | 值 |
|---|---|
| 诊断 session 数 | 1 |
| Tier 2 命中 | 1 |
| 路由准确率 | 1/1 (100%) |
| 结果反馈捕获 | 1/1（resolved） |
| trace 完整性 | 1/1 |
| trace 词表合规 | 9/9 |
| Tier 3 兜底 | 0/0 |

## 七、演示中抓到的真实缺口（最有价值的部分）

跑这条真实 trace 时，`trace_metrics.py` 直接崩溃：`'str' object has no attribute 'get'`——它还在读 ADR-0004 之前的平铺索引结构（`ns → [entries]`），而索引已改为格子结构（`ns → category → [entries]`）。**这是"结构性闭环"与"运行性闭环"的差别：机制建起来是一回事，真实跑一遍才会暴露消费方没同步。** 已修复（trace_metrics 适配格子遍历）并合入 main。

## 八、演示要点（对观众说）

1. **输入是真实的**（issue 首帖），不是构造的——`quickly_check` 在真实文本上 primary 命中
2. **每步都可追溯**（trace 词表固定、落盘、历史不删）——这是误诊归因和数据指标的前提（原则八）
3. **反馈是学习环的发动机**：不问"解决了吗"，confidence 永远是初始值，整个机制空转（diagnose SKILL.md 原话）
4. **真实运行会暴露结构债**：索引格子化后消费方没同步——闭环的价值正是让这类债在演示时被看见，而不是上线后

## 八·五、现场演示脚本（在真实 agent 环境跑）

> 给"装了 ascend-sleuth skill 的 agent"（Claude Code / pi）的精确现场脚本。观众看到的是真 agent 在跑，不是文档回放。每步附预期响应，用于演示者核对。

**前置**：本地 checkout 本仓库，确认 `knowledge/_index.yaml` 含 VLLM-ASC-12723（`python3 scripts/build_index.py --check` 绿）。

**第 1 步 — 触发诊断**（约 5 分钟，核心）：
```
/skill:diagnose

客户 A3 (16 dies) 上 GLM-5.2 DSpark speculative decoding，driver 25.5.1，
vllm 0.23.0 + vllm-ascend nightly-0.23.0-a3，torch_npu 2.10.0.post2，triton 3.2.0。
platform-dispatched rotary embedding 路径返回非范数保持的 Q/K，accept_len ~3.0；
同一对象调 forward_native() 输出正确，accept_len 恢复到 5.4-5.5。
```
预期响应序列（按 SKILL.md 流程）：
1. triage 路由 → 明确"inference/vllm-ascend + precision"
2. 阶段一加载索引 → 明确候选（预期 1 条：VLLM-ASC-12723）
3. 命中输出（CASE-ID + confidence + fix + rollback + severity + 应用后检查）
4. 结束时**主动问反馈**（"应用后解决了吗？"）——这是关键观察点

**核对点**：
- [ ] agent 是否标注了版本匹配（A3-910C + vllm-ascend 0.23.0）
- [ ] 命中输出含 fix_type / severity / rollback 完整字段
- [ ] 结束时问了反馈（若没问，说明该 agent 会话没加载最新 SKILL.md）

**第 2 步 — 反馈闭环**（可选，展示学习环）：
```
已解决。accept_len 恢复到 5.5。
```
预期：agent 更新 confidence（hits 0→1、score 0.6→0.73）、清理 feedback_pending、明确"下次同类问题优先验证"。

**第 3 步 — 指标**（可选，展示可观测）：
```bash
python3 scripts/trace_metrics.py
```
预期：本次 session 出现在表中（命中 1、反馈捕获 1、词表合规）。

**失败预案**：若 agent 未命中（比如没识别 vllm-ascend）→ 演示优雅退化：`rg -l 'accept_len' postmortems/` 走 Tier 3 兜底，或提示补环境信息——这正是"诚实退化"的现场演示，不算翻车。

---

**边界说明**：真实 trace 文件含运行现场信息，按设计留在本地（`.gitignore` 的 `diagnosis_state*.yaml`）；需要演示复盘时用本文件副本 + 本地原文件对照。
