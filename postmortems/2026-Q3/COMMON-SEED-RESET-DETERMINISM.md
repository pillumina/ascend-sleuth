# COMMON-SEED-RESET-DETERMINISM: 重复训练 loss/grad_norm 不一致（确定性开关被业务代码重置）

> 源是结构化文档（msprobe 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprobe/blob/tag_MindStudio_26.2.0.B050_003/docs/zh/best_practices/ascend_qwen25_omni_determinism_troubleshooting.md
**时间**：2026-09-09（沉淀）
**框架**：cross（根因在业务代码，与框架/CANN 版本无关）
**category**：precision
**investigation_quality**：high（dump 两次比对 → 单算子复现 → plog 查 aclnn deterministic 标识 → 全局搜 seed 设置，链条完整）
**namespace 建议**：common/（框架无关；注：common/ 目前为空，见 triage-tree 头注）

## 结构化 case

`knowledge/common/precision/COMMON-SEED-RESET-DETERMINISM.yaml`（已转正 Tier 2）

## 一句话根因

业务装饰器 fix_randn 内重复调用无参 seed_all()，把已置 True 的 torch.use_deterministic_algorithms 重置为 False，aclnn 算子 deterministic 标识由 1 变 0、切到非确定路径 —— 并非昇腾算子本身的非确定性缺陷。

## 弯路与级联

- **先排除**：先怀疑算子非确定性；to cpu 对齐后第一步 loss 一致但 grad_norm 仍偶现不一致；单算子重复跑多遍都不变化（整网才概率性变化）——单算子复现失败是本 case 的显著特征，说明干扰来自业务代码而非算子。
- **分水岭证据**：plog 显示 aclnn deterministic 中途由 1 改 0。
