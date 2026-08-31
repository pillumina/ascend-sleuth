# 原文见：https://github.com/vllm-project/vllm-ascend/issues/10626（真实诊断 trace：traces/2026-08-30-10626-lora-507018.yaml）
# 沉淀：诊断面板触发 to-postmortem（2026-08-31）；预分诊 novelty=variant（VLLM-ASC-13050）

# 摘要
- 现象：v0.19.1rc1 部署 Qwen2VL，--enable-lora 启动失败：aclnnUniqueConsecutive failed,
  error code 507018 (aicpu exception)；调用链 profile_run → set_active_adapters → compute_meta
  → torch.unique_consecutive；tower-connector-lora 变体报 507057
- 根因：多模态 LoRA adapter 激活路径（unique_consecutive）aicpu 异常——与 13050（310P IndexPut）
  同 507018 签名但算子/平台不同，是独立变体
- fix：待上游多模态 LoRA 算子适配；勿套用 13050 的版本升级 fix
- 价值：507018 家族扩成员（IndexPut→unique_consecutive），签名相同 ≠ 根因相同——诊断时须读
  全 body 比对算子/路径，避免把 13050 的修复直接套用
- 诊断轨迹：triage(inference_interrupt) → index(507018→13050) → load_full 比对算子差异 → hit(variant, 0.3)
