# VLLM-ASC-11893: PCP 短请求在 rank>0 产生零 token 空段，chunk 索引错位致 AscendC kernel batchTokens 下溢、MTE 写越界（runtime 507015）

> 源是结构化 GitHub BugFix PR 线程（2 条评论，含 Gemini 代码评审摘要），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/pull/11893
**fix 跟踪**：PR #11893 merged 2026-07-14（v0.23.0 backport of #11807，upstream vllm commit ee0da84ab9e04ac7610e28580af62c365e898389）；修复 = fwd_h/fwd_o 前调用 `_compact_empty_segments` 压缩空段并对齐 compact rank，keep-mask 回填 final_state
**时间**：2026-07-13 ~ 2026-07-14（当日提出、次日合并）
**框架**：vllm-ascend v0.23.0，Qwen3.5 + PCP（prefill-context-parallel）world_size>1，混合长度并发批
**平台**：未在线程中给出（Ascend NPU；PCP/GDN chunk 自定义 kernel 层）
**category**：interrupt
**investigation_quality**：high（PR 自带完整数值推演：cu_seqlens=[0,128,128,256] 空段错位 → batchTokens=128-128=0 → 0-164 uint32 下溢 → MTE 越界；修复 no-op 语义论证）
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（batch 2，组 1）

## 结构化 case

`postmortems/inbox/VLLM-ASC-11893.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

PCP 按 `cp_kv_cache_interleave_size`（默认 128）把每个请求的 prefill 跨 rank 交错切分，短于 interleave 的请求在 rank>0 产生零 token 空段并留在该 rank 的 cu_seqlens 里；`chunk_indices` 构建时跳过空段（紧凑段号），而 `chunk_fwd_o` kernel 用含空段的原始 gmSeqlen 按紧凑段号索引 → 段号错位，batchTokens 取到空段边界差值（如 0）再减 chunk size 后 uint32 下溢成巨值 → MTE 写越界 runtime 507015。

## 弯路与级联

- **无弯路**：BugFix PR 自带根因数值推演与 no-op 论证，调查质量高。
- **触发条件窄**：PCP world_size>1 + 混合长度并发批 + 存在 token 数 < interleave size 的短请求，三者同时满足才命中；rank0/非 PCP/均匀批次不受影响（`_compact_empty_segments` no-op）。
- **级联**：错误发生在 AscendC 自定义 kernel（chunk_gated_delta_rule_fwd_h/chunk_fwd_o）与 PCP 元数据构造（gdn_attn_builder._fill_chunk_indices_cpu）的衔接处——元数据紧凑、kernel 用原始索引，两处约定不一致是根因所在。
