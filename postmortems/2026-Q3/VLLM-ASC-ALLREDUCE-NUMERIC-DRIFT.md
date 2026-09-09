# VLLM-ASC-ALLREDUCE-NUMERIC-DRIFT: CANN 升级后推理回复乱码（all_reduce 数值偏差）

> 源是结构化文档（msprobe 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprobe/blob/tag_MindStudio_26.2.0.B050_003/docs/zh/best_practices/problem_of_garbled_response_after_cann_upgrade.md
**时间**：2026-09-09（沉淀）
**框架**：vllm-ascend（Ascend 950 PR；CANN 9.0.0 正常 / 9.1.0 异常）
**category**：precision
**investigation_quality**：high（Dump → 比对 → 单算子复现三段收敛）
**namespace 建议**：inference/vllm-ascend/

## 结构化 case

`knowledge/inference/vllm-ascend/precision/VLLM-ASC-ALLREDUCE-NUMERIC-DRIFT.yaml`（已转正 Tier 2）

## 一句话根因

CANN 9.1.0 的 all_reduce 算子存在数值偏差（9.0.0 无此问题），表现为推理回复乱码；升级到已修复的 9.1.0 B037 解决。

## 弯路与级联

- **收敛依据**：升级前后模型结构、API 调用逻辑均未改变，且回退 CANN 版本问题消失 → 把范围收敛到「新版本数值行为变化的算子」。
- **方法论价值**：这是「CANN 升级后精度异常」的标准定位范式——Dump → 比对 → 单算子复现，可复用。
