# VLLM-ASC-9167: GLM5.1-w4a8 拉起报 AssertionError：FlashAttnPrefillBackend requires flash_attn_varlen_func（vLLM 0.20.1 MLA prefill backend patch 分支不匹配）

> 源是结构化 GitHub issue 线程（4 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/9167
**fix 跟踪**：PR #9835（main 修复，ZhangwenTaoHW 确认）；vLLM 0.20.1 版本用 PR #9231 workaround；zhaomingyu13 确认最新 release/rc 已解决；issue completed 关闭
**时间**：2026-05-14 ~ 2026-08-10（completed）
**框架**：vllm-ascend 0.19.1rc2.dev45+g8486a744f + vLLM 0.20.1（失败环境）；GLM5.1-w4a8
**平台**：昇腾 NPU（npu-smi 仅标 Ascend910）
**category**：interrupt
**investigation_quality**：medium（官方确认修复 PR + workaround，闭环完整；根因在 patch 层版本分支判断）
**批量导入**：批次 2 组 4（2026-08）

## 一句话根因

vllm_ascend/patch/platform/patch_mla_prefill_backend.py 用版本分支选择 MLA prefill backend：对 vLLM 0.20.1 的判断分支不匹配，未替换成昇腾 MLA prefill backend，上游默认选中 FlashAttnPrefillBackend；昇腾环境无 flash_attn，且未先查 is_available() 即断言失败（flash_attn.py:60）。

## 弯路与级联

- **版本耦合**：同一报错只出现在 vLLM 0.20.1 + 该 vllm-ascend 版本的组合——问题在 patch 层对上游版本演进的适配，排查时先对 vLLM/vllm-ascend 版本组合。
- **Workaround 与修复并存**：0.20.1 用 PR #9231 临时适配，main 由 PR #9835 正式修复——升级 vs 打补丁二选一，groom 记录两条路径。
- **忽略多进程级联**：WorkerProc failed to start → EngineCore init failed → APIServer 退出是一串级联，根因只在断言那一行（flash_attn.py:60）。
