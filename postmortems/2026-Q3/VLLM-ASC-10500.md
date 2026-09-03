# VLLM-ASC-10500: 含 ViT 的多模态/VL 模型开启 FlashComm1+FlashComm2 报错——ViT 层被 FC1/FC2 dispatch 误路由进 forward_context 依赖算子

> 源是结构化 GitHub issue 线程 + 修复 PR，按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest 批量流水线 sed-g3（2026-09，第 7/7 条）产出，待 knowledge-groom 周审。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/10500（closed 2026-07-25，state_reason=completed）
**修复 PR**：https://github.com/vllm-project/vllm-ascend/pull/10941（[BugFix] Skip FlashComm1/2 For ViT，merged 2026-07-10）
**时间**：issue 2026-06-15 创建 → 修复 PR #10941 2026-07-10 merged main → issue 2026-07-25 closed completed
**框架版本**：issue env torch 2.9.0 / torch-npu 2.9.0 / CANN 9.0.0-beta.1 / triton-ascend 3.2.0（env dump 未列 vllm-ascend 版本）；PR 在 vLLM v0.23.0 / vLLM main（commit 1f486d96a17303ce8db8e02be39545b2be338446）上验证
**平台**：issue 未注明芯片型号（8× Ascend NPU、TP=8）→ YAML 不设 platforms，按跨平台处理
**category**：interrupt
**investigation_quality**：medium（issue 作者自定位 + 修复 PR 合入闭环完整：PR 给出根因 + 三条 dispatch guard 语义 + TP8 实测，无自动化单测）
**verification**：upstream-fix-merged（detail: 'fix PR #10941'）

## 现象（用户首帖）

含 ViT 的多模态/VL 模型（如 Step3p7 flash w8a8，TP=8）+ FlashComm1（`VLLM_ASCEND_ENABLE_FLASHCOMM1=1`）+ FlashComm2（`VLLM_ASCEND_FLASHCOMM2_PARALLEL_SIZE=1`）+ MTP 投机时：

- **A-1 — FC1 ViT 初始化崩溃**：`AssertionError: Forward context is not set. Please use `set_forward_context` to set the forward context.`，栈在 `vllm_ascend/ops/linear_op.py` 的 `SequenceRowParallelOp.apply_impl` → `torch.ops.vllm.matmul_and_reduce` → `_ExtraForwardContextProxy.__getattr__` → `get_forward_context()` 断言。
- **A-2 — FC2 ViT 初始化崩溃**（同场景不同算子）：`Flashcomm2OProjRowParallelOp.apply_impl`（`_EXTRA_CTX.pad_size`）同断言；运行期 fallback 后报 `aclnnAddmm failed, error code 161002 / AclNN_Parameter_Error(EZ1001): The k-axis of the two inputs are different`。
- **B — decode 阶段 NPU 硬件崩溃**（FC1+MTP）：`LaunchCopyTask: aclrtMemcpyAsync, error code 507035 / The DDR address of the MTE instruction is out of range / retCode=0x31 [vector core exception]`，栈到 `eagle_proposer._clamp_mtp_seq_lens_to_allocated_blocks` 的 `max_seq_lens_cpu.to(device)`——memcpy 失败前 NPU 内存已被损坏。

## 一句话根因

vLLM 对多模态模型在 `forward_context` 之外预计算 `inputs_embeds`；vllm-ascend 的 FlashComm1/2 dispatch 未排除 ViT 层（模块 prefix 含 `"vision_model"`），把 ViT 前向路由到依赖 forward context 的 SP 线性算子（`SequenceRowParallelOp` / `Flashcomm2OProjRowParallelOp`）——此时 `_EXTRA_CTX` 为空、FC1/FC2 flags 不可用，`get_forward_context()` 断言崩溃。

## fix

升级到含 PR #10941 的版本（merged main 2026-07-10，v0.23.0 验证；受影响区间 = FlashComm1/2 dispatch 覆盖 ViT 的版本，即 PR 合入前的 <v0.23.0 线）：对三条 dispatch 路径——SP column-parallel（`SequenceColumnParallelOp`）、SP row-parallel（`SequenceRowParallelOp`）、FlashComm2 row-parallel（`Flashcomm2OProjRowParallelOp`）——加 `"vision_model" not in prefix` guard，ViT 层跳过 FC1/FC2 dispatch；文本-only 模型（prefix 不含 vision_model）不受影响。修复由 issue 作者 wangyichao1999 提交（先以 vllm_ascend_fix.patch 附于评论验证，后正式提 PR 合入）。

## 弯路与级联

- B（decode 507035/vector core exception）与 A-2 的 `aclnnAddmm 161002(EZ1001)` 都是 ViT 误路由导致 NPU 内存损坏后的级联报错，不是独立根因，勿逐个追查。
- MTP 投机只是放大/提前暴露场景，不是根因（PR 测试即 FC1+FC2+MTP 组合）；先对"含 ViT × 开启 FC1/FC2"两个开关判断，文本-only 模型同配置不触发。
