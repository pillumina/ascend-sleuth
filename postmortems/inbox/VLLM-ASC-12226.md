# VLLM-ASC-12226: sleep mode wake_up 对 MoE 专家权重多 transpose 一次，纯推理 wake_up 后维度错位（grouped_matmul 161002/EZ1001）

> 源是结构化 GitHub issue 线程（3 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/12226
**fix 跟踪**：无合并修复 PR——维护者（yjyang62，评论#1）确认根因并给出可用调用序列 workaround；官方计划将 sleep/wakeup 与模型布局转换解耦以支持 Level 1 直接恢复推理（设计进行中，未落地）；issue 由 He1pa 以 completed 关闭（2026-08-12）
**时间**：2026-07-17 ~ 2026-08-12
**框架**：vllm-ascend releases/v0.18.0（0.1.dev100+g45068b082）+ vLLM 0.18.1.dev42，Qwen/Qwen3.5-122B-A10B，TP4/DP4/EP，--enable-sleep-mode
**平台**：A2-910B（npu-smi 显示 Ascend910 ×16，CANN 8.5.0）
**category**：interrupt
**investigation_quality**：high（AI 辅助代码级根因 + 维护者确认 + 与 vllm 主仓 CuMemAllocator 设计对照）
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（batch 2，组 1）

## 结构化 case

`postmortems/inbox/VLLM-ASC-12226.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

camem 的 sleep/wake 是字节级 memcpy（不改 shape/stride），wake_up 后权重已是 forward 的 READY 方向；`NPUWorker.wake_up`（worker.py:208-236）却又对 MoE w13/w2 transpose(1,2) 一次（该循环是为 RL 权重更新把权重转回 HF/checkpoint 方向），构成双重转置——纯推理 wake_up 后 K 维错位（3072 vs 2048），`npu_grouped_matmul` 报 `aclnnGroupedMatmulV5 failed, error code is 161002` / `EZ1001`。

## 弯路与级联

- **影响面窄**：dense 模型权重名为 gate_up_proj/down_proj，transpose 循环只匹配含 `w13_weight`/`w2_weight` 的参数 → dense 全程 no-op、不受影响；只有 MoE 纯推理 + `--enable-sleep-mode` 触发。
- **无显式误导报错之外的第二陷阱**：线程首条评论即给出完整代码级推演（camem 字节拷贝 → 恢复后已是 READY → wake_up 再转置 = 双重转置），维护者评论#1 更正了文档中 "original (untransposed) memory" 表述并确认根因，没有走弯路。
- **状态**：`wait-feedback` 挂起一个月后由作者自行 completed 关闭；官方解耦设计未合入任何 PR，升级版本前此 workaround 仍有效。
