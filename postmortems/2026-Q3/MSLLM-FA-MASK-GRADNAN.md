# MSLLM-FA-MASK-GRADNAN: 256卡 Qwen3-235B 长序列 SFT GradNorm NaN（FA causal mask 退化为 band）

> 源是结构化文档（msprobe 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprobe/blob/tag_MindStudio_26.2.0.B050_003/docs/zh/best_practices/ascend_complex_dump_gradnorm_nan_analysis.md
**时间**：2026-09-09（沉淀）
**框架**：mindspeed-llm（文档记录 2.1.0 / CANN 8.2.RC1 / TorchNPU 2.6.0）
**category**：precision
**investigation_quality**：high（256 卡 dump 逐层反查 + 调用栈对照 + 算子入参核对，定位到 sparsemode/pre_tockens）
**namespace 建议**：training/mindspeed-llm/

## 结构化 case

`knowledge/training/mindspeed-llm/precision/MSLLM-FA-MASK-GRADNAN.yaml`（已转正 Tier 2）

## 一句话根因

sparsemode=0 下 MindSpeed 把 pre_tockens 默认值设为 65536，而序列长度 131072 超过该值，本应传 causal mask 做三角下全计算却退化为 band，attention 只能看到有限数据 → FA 反向逐层放大 → GradNorm NaN。

## 弯路与级联

- **先排除的假设**：`ASCEND_LAUNCH_BLOCKING=1` 仍 NaN（排除流同步时序）；关闭 overlap_grad_reduce / overlap_param_gather / use_cp_send_recv_overlap / moe_alltoall_overlap_comm / overlap_p2p_communication 后仍 NaN（排除 overlap 类）。
- **定位手法**：按 PP 组顺序（rank0 → 64 → 128 → 192）搜首个 NaN/Inf；过滤 empty 张量与通信占位节点；对照调用栈与代码行逐算子回溯；FA 与 RMSNorm 反向均见放大，选一层逐行分析后落到 FA 入参。
