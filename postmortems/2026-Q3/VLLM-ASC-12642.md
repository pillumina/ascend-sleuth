# VLLM-ASC-12642: triton-ascend 3.2.1 对 K 归约路径生成错误设备代码，RMSNorm variance 算成 0

> 源是结构化 GitHub issue 线程（4 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/12642
**fix 跟踪**：无 PR——官方确认与 triton-ascend 版本相关，升级 3.2.2（3.2.2+dev20260711140232）验证通过
**时间**：2026-07-22 ~ 2026-08-15
**框架**：vllm-ascend 0.21.0rc2.dev + triton-ascend 3.2.1 + CANN 9.0.0 + torch_npu 2.10.0，Qwen3.5-4B (bf16, partial RoPE)
**平台**：A5-950（Ascend 950PR）
**category**：precision
**investigation_quality**：high（最小可复现 triton kernel + 逐表达式拆分定位 0 的产生点 + 官方确认修复版本）
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md

## 结构化 case

`postmortems/inbox/VLLM-ASC-12642.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

triton-ascend 3.2.1 的 CANN 后端设备代码生成缺陷：`split_qkv_rmsnorm_mrope` 对 [4,256] 的 K 做 head reduction（`tl.sum(squares, axis=1) / head_size`）后，又接入 `extract_slice`（取前 64 维）+ cos 广播相乘的 RoPE 计算时，编译器为 K RMSNorm 生成另一套布局/归约代码，把平方和 `square_sums` 错误生成 0 → variance=0 → `reciprocal_std=1/sqrt(1e-6)=1000` → K 被放大 1000 倍 → 模型输出错误。升级 triton-ascend 3.2.2 修复。

## 弯路与级联

- **弯路（先排除后确认）**：先怀疑 RMSNorm 数学/eps/表达式拆分——把 `variances = tl.sum(squares, axis=1) / head_size` 拆成 `square_sums` + 除法两步后 `square_sums` 仍为 0，排除数值精度问题；最小复现 kernel 证明：**加入 `orig_qk * cos_tensor` 这条后续计算后编译器才生成错误代码**（不加则正确）→ 根因是编译器的布局/归约路径与后续 RoPE 计算的耦合，而非算子逻辑。
- **平台/形状特异性**：Ascend 950PR (A5) + partial RoPE（rope_dim=64 < head_size=256，num_q_heads=16/num_kv_heads=4）触发；诊断时按此形状与 triton-ascend 版本判别。
