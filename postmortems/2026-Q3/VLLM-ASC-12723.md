# VLLM-ASC-12723: Triton rope sin 缓存偏移用 pad 后 rotary dim，非 2 的幂 rope_dim 下 RoPE 退化

> 源是结构化 GitHub issue 线程（8 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/12723
**fix 跟踪**：PR #12963（https://github.com/vllm-project/vllm-ascend/pull/12963，3 行 diff + 回归测试）
**时间**：2026-07-23 ~ 2026-08-18
**框架**：vllm-ascend 0.23.0 nightly（A3 镜像）+ torch_npu 2.10.0.post2 + triton 3.2.0 + CANN 9.0.1，驱动 25.5.1
**平台**：A3-910C（16 dies）
**category**：precision
**investigation_quality**：high（maintainer 代码级根因 + 3 行修复 + Q/K 范数实测 0.73 + 回归测试覆盖非 2 的幂形状）
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md

## 结构化 case

`postmortems/inbox/VLLM-ASC-12723.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

`vllm_ascend/ops/triton/rope.py` 的 sin 缓存偏移用了 padding 后的 rotary dim（`sin_offsets = tl.arange(pad_rope_dim // 2, pad_rope_dim)`）。rope_dim=192（非 2 的幂，pad 256）时 sin 段实际起点 96、代码从 128 开始，错位 32 元素且尾部越界 → sin≈0 → RoPE 退化为 `out=in*cos`，Q/K 范数降至 ~0.73，DSpark 投机 accept_len 从 5.6 崩到 3.0。

## 弯路与级联

- **弯路（先排除后确认）**：报告方先排除 checkpoint / config / acceptance-logic（对照 #12262：Markov logits input、anchor sampling、QuaRot weight rotation 是不同根因）；用同一 rope 对象/worker/输入调 `forward_native()` 结果正确、accept_len 恢复 5.4-5.5 → 确认是 **dispatched Triton rope 执行路径本身的数值错误**，而非配置或权重。
- **次级细节**：cos 偏移同样用了 pad 值（`cos_offsets = tl.arange(0, pad_rope_dim // 2)`），但因 cos 段物理起点恒为 0 且被 `cos_mask = cos_offsets < (rope_dim // 2)` 过滤，净效果正确——排查时不必怀疑 cos 侧。
