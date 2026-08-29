# VLLM-ASC-10122 —— 310P Qwen3.6-27B-W8A8 推理 507015 aicore exception

- **来源**：[vllm-ascend issue #10122](https://github.com/vllm-project/vllm-ascend/issues/10122)（triaged，2026-06-09 closed，completed）
- **导入管道**：issue-ingest skill（triaged 池，评论数启发式排序候选）
- **状态**：draft（postmortems/inbox/ 待审，groom 周批三分类）

## 现象

310P 上 vllm serve 跑 Qwen3.6-27B-W8A8（nightly-releases-v0.20.2rc-310p-openeuler 镜像），推理报：

```
[rank1]:[E606] operator():.../op_api_common.h:192 NPU function error: call failed, error code is 507015
[ERROR] ERR00100 PTA call acl api failed
[Error]: The aicore execution is abnormal.
AclNN_Runtime_Error(EZ9903): aclrtLaunchKernelWithHostArgs failed: 507015
Kernel task happen error, retCode=0x26, [aicore exception]
Aicore kernel execute failed, ... fault kernel_name=QuantBatchMatMulV3_NZ_NZ_int8_int8_fp16_high_performance_21
```

关键签名：**507015**（aicore execution 异常）+ **QuantBatchMatMulV3**（量化 matmul 算子）+ error code 0x26。

## 根因

社区（维护者）确认：**量化运算的 QuantBatchMatMulV3 算子在该 CANN 版本存在 bug**，执行时报 aicore exception（507015）。修复已合入 **CANN 9.1.0.beta2** 分支，但需等待 CANN 社区版发布后才能通过镜像升级生效。

## 处理

- 升级 CANN 到含修复版本（≥9.1.0.beta2），同步升级 vllm-ascend 镜像；
- 社区版发布前：等待维护者升级仓库 CANN 镜像后重试。

## 评估

- 沉淀判定：**可沉淀**（症状签名明确 + 根因定论（维护者确认）+ fix 方向明确）——但 fix 是"等待社区版"，属版本等待型，验证闭环待社区发布后补（case confidence 初始 0.4 medium）
- 新错误码 507015 未入 cann-runtime 表——可选后续补入（error-code 表"追加不新建"）

## 同批评估（issue-ingest 首轮，3 条 top 候选）

| issue | 判定 | 理由 |
|---|---|---|
| #10122 | ✅ 沉淀 | 根因定论（维护者确认 CANN 量化算子 bug）+ fix 明确（升级）|
| #10720 | ⏭ 跳过 | MTP 过度思考 + 启动失败双问题，根因未定论（转维护者）|
| #10640 | ⏭ 跳过 | MTP 启动失败为 CANN 版本等待型，无独立可复用诊断逻辑（与 #10720 同域待社区结论）|
