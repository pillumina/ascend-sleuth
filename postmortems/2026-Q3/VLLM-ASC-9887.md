# VLLM-ASC-9887: GLM-5.1-w8a8 PD 分离 decode 节点运行期崩溃（507034 / MoeDistributeDispatchV2）——MTP 阶段 MC2 容量不足致不同 DP 走不同 MoE 分发分支

> 源是结构化 GitHub issue 线程（用户 plog/栈定位 + 收尾给出根因与规避），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest sed-g1 批次 1 产出，进 inbox 待 groom 分诊。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/9887
**框架/平台**：客户内仓 vllm-ascend（base v0.18.0，2026-04-17 commit）/ A3 双机 decode（DP + EP + MTP/deepseek_mtp + FusedMC2 + MLAPO + Mooncake KV），CANN 8.5.0、驱动 25.2.1
**category**：interrupt
**investigation_quality**：medium（用户 plog aicore MTE 定位 + 收尾给出参数级根因（MC2 容量 104 vs 配置 272）与规避方案；无官方 fix PR、无维护者代码级确认）
**verification**：investigation（无 upstream fix；issue closed completed 基于用户根因结论 + 规避配置）
**novelty**：variant_of VLLM-ASC-12461——同"多机 MoE 通信分发（MoeDistributeDispatchV2/MC2）+ speculative(MTP) decode"代码路径族崩溃（12461=ROCE 兼容 0.20.2rc1+ 修复；本条=MC2 容量/分支不一致的运行期崩溃 v0.18 base），机制不同、路径同族

## 现象摘要

GLM-5（-w8a8）双机 A3 PD 分离 decode 节点（DP、EP、MTP speculative、FusedMC2、MLAPO、cudagraph FULL_DECODE_ONLY）上线后运行期崩溃：

- 崩溃栈尾：EAGLE/MTP drafter layer 78 MoE forward → token_dispatcher._preprocess → `torch.repeat_interleave` → AllGather → **RuntimeError: error code 507034**。
- plog：device0 先错 `errType=0x1`（task exception，MTE DDR 越界 + SMMU fault）；其余设备 `errType=0x4`（communication timeout）为 device0 退出后 AllGather ring 断裂的连锁反应（**cascade，勿当独立根因**）。
- 社区排查建议：驱动 ≥25.5.2（npu-smi 版本 25.2.1）或关闭 EP——先试探性建议，非本根因。
- **用户收尾根因**：MTP 阶段某个 DP 的 token 数超过 MC2 容量（按 cudagraph 最大捕获 102 计算容量 ≈104）时，该 DP 走了 alltoallv 分支、其余 DP 走 MC2——不同 DP 走不同 MoE 分发分支 → 崩溃。配置 `max-num-batched-tokens=272` 是触发条件。
- 规避：`num_batch_tokens = max_num_seqs×3`（≤ cudagraph 最大捕获尺寸，避免 DP token 超 MC2 容量导致分支不一致），且保持 32 的倍数（避免 fusedmoe 算子 tiling 报错）。

## 一句话根因

多 DP + FusedMC2 + MTP 的 decode 中，`max-num-batched-tokens`（272）超过按图捕获尺寸推算的 MC2 单次容量（≈104）：MTP 阶段某 DP 的 token 超容量后落入 alltoallv 分发分支，与其余走 MC2 的 DP 形成**分支不一致** → MoE 分发路径崩溃（device0 MTE DDR 越界，上抛 507034/连锁超时）。

## fix（规避方案，无官方 fix PR）

- `num_batch_tokens = max_num_seqs×3`（≤ cudagraph 最大捕获尺寸），且 num_batch_tokens 保持 32 的倍数（线程原话），避免不同 DP 走不同 MoE 分支 + fusedmoe tiling 报错；
- 社区早期建议（低代价可试）：驱动升级 ≥25.5.2、或关 EP——未证实为本根因，作为先试手段记录。
