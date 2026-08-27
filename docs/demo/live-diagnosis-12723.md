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

---

**边界说明**：真实 trace 文件含运行现场信息，按设计留在本地（`.gitignore` 的 `diagnosis_state*.yaml`）；需要演示复盘时用本文件副本 + 本地原文件对照。
