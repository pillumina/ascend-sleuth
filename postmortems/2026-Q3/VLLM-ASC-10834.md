# VLLM-ASC-10834: qwen3-8B-W4A8 量化权重启动报 antiquantGroupSize should be 128 or 64, but actual [256]——group_size=256 的 int4 权重无法转 FRACTAL_NZ，VLLM_ASCEND_ENABLE_NZ=0 或重量化 group128

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest sed-g2 批次 2 产出（人工筛出的高质量 closed issues），进 inbox 待 groom 分诊。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/10834
**fix 跟踪**：无代码 fix PR——维护者（kunpengW-code）定论 = 算子限制（同 issue #5603，该处注明"this part of code is to be reconstructed recently"）；Solution1 `VLLM_ASCEND_ENABLE_NZ=0`、Solution2 重量化 group_size=128
**框架/平台**：vllm-ascend v0.18.0.rc1 / atlas800i a2（910B）/ Qwen3-8B W4A8 量化权重（group_size=256）
**category**：interrupt
**investigation_quality**：medium（维护者定论算子限制 + 同 issue #5603 多用户复现；两条 workaround 均为官方给出、无升级后验证记录）
**verification**：upstream-maintainer-confirmed（kunpengW-code 维护者 2026-06-23 明确 resolution + 同因 issue #5603；无 fix PR——代码重构计划中）
**novelty**：new_pattern——_index 全量比对无 int4/antiquantGroupSize/FRACTAL_NZ 算子限制族；最近似 10122(QuantBatchMatMulV3 507015)/10610(modelslim KeyError) 均不同机制

## 现象摘要

atlas800i a2 用已量化的 Qwen3-8B-W4A8 权重（group_size=256）启动 vllm serve（v0.18.0.rc1）报：

```
[ERROR] ... ERR00100 PTA call acl api failed.
AclNN_Parameter_Error(EZ1001): when weight's dtype is [int4], weight's format is [FRACTAL_NZ],
antiquantGroupSize should be 128 or 64, but actual antiquantGroupSize is [256].
```

- 同 error 出现在 issue #5603（vllm-ascend 0.13.0，单卡 910B，Qwen3-8B W4A8，group_size=256 量化后部署）。
- 部分 Qwen3-8B-W4A8 官方发布权重即 group 256（modelscope vllm-ascend/Qwen3-8B-W4A8），反量化侧代码当时也用 256——本质是算子限制而非权重发布错误。

## 一句话根因

torch_npu 反量化批 matmul（npu_weight_quant_batchmatmul）算子限制：**int4 权重转 FRACTAL_NZ 布局时只支持 antiquantGroupSize 64/128**，group_size=256 的 W4A8 权重无法转 NZ → AclNN_Parameter_Error EZ1001、启动失败。与权重/部署版本无关，是算子格式限制。

## fix

- Solution 1：启动加 `export VLLM_ASCEND_ENABLE_NZ=0`（禁权重转 NZ，走非 NZ 布局规避算子限制）。
- Solution 2：按 `--group_size 128` 重新量化权重（满足 64/128 限制）。
- 代码侧"即将重构"（维护者 kunpengW-code，#5603），当时无已合入 fix PR——请以"含该重构的版本 + 上述 workaround"为准复测。

## 建议 triage 路由症状

现有 inference_interrupt 有 `failed to start|启动失败` + 错误码兜底（`ErrCode=` 需含 AclNN_/EZ1001 变体）；若 triage 未命中建议补 `antiquantGroupSize|AclNN_Parameter_Error|FRACTAL_NZ.*int4`（随 case PR 提交，needs-review 由 groom 定夺）。
