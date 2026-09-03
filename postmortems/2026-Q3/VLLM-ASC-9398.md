# VLLM-ASC-9398: CANN 9.0 镜像下 Mooncake KV pool put key error（res -800）——HCCP RDMA MR 注册失败 + GE 503900，Mooncake 0.3.9→0.3.10 解决

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest r2-sed-g4（2026-09）产出，进 inbox 待 groom 分诊；不改正式 knowledge/ 目录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/9398
**fix 跟踪**：无上游 fix PR——依赖版本兼容问题；reporter MarinaMiao（2026-05-26）验证升级 Mooncake 0.3.9→0.3.10 恢复；issue closed 2026-05-28
**时间**：2026-05-21 ~ 2026-05-28
**环境**：CANN 9.0.0 + HDK 25.2.1（npu-smi）+ torch_npu 2.10.0 + vLLM 0.20.2 + vllm-ascend 0.19.1rc2.dev101+ga45cdf9b9 + Mooncake 0.3.9；Ascend910 16 卡跨 2 节点，GLM5.1-w8a8 PD 分离 kv pool
**category**：interrupt
**investigation_quality**：medium（日志链完整，归因停在"版本兼容"级，0.3.10 修复点未由上游确认）
**verification**：engineer-report（现场工程师升级依赖后验证恢复）
**novelty**：variant_of VLLM-ASC-10532——同 Mooncake KV Pool ascend direct/ROCE 传输故障族（与 11459/10532/11343/13934 并列）；本条形态=kvpool put key error / MR 注册失败，fix 在 Mooncake 依赖版本，无 segfault、无 vllm-ascend 代码缺陷

## 现象摘要

CANN 9.0.0 + HDK 25.2.1 + Mooncake 0.3.9 下 GLM5.1-w8a8 PD 分离 kv pool 服务无法工作，三层日志链：

```
# vllm 日志（mooncake_backend）
(Worker_DP0_TP1_EP1 pid=577570) ERROR ... [mooncake_backend.py:88] Failed to put key ['glm5.1-w8a8@pcp0@dcp0@...'],res:[-800, -800, ...]
E... ascend_direct_transport.cpp:1111] Failed to connect to target: <host>:<port>, status: 503900

# device log（hccp_service.bin，~/ascend/log/debug/device-*）
[ERROR] HCCP ... [rs_rdma.c:697] rs_init_typical_mr_cb: rs_drv_exp_mr_reg addr is NULL len[32212254720] fail
[ERROR] ROCE ... [hns_roce_u_ai.c:155] hns_roce_u_reg_ai_mr: reg ai mr failed, ret[12]

# plog（GE）
[ERROR] GE ... CreateChannel: ErrorNo: 503900 ... Call hccl api failed, ret: 0x4
```

（IP 与 key sha 已脱敏，原文 URL 见源文档。）

## 一句话根因

CANN 9.0.0 + HDK 25.2.1 + **Mooncake 0.3.9** 组合下跨机 kv pool 建不起传输：HCCP RDMA MR 注册 30GiB 缓冲失败（`rs_drv_exp_mr_reg addr is NULL`，ret -13 / hns_roce ret[12]）→ HCCL channel init 失败（GE 503900）→ ascend_direct 无法连接远端 → put key 全失败（Mooncake res -800）。**升级 Mooncake 0.3.9→0.3.10 后同环境恢复**——版本兼容问题（0.3.10 具体修复点未在 thread 内确认）。

## fix

- 升级 Mooncake 至 **0.3.10**（或最新 release），重启 kv pool 服务；CANN 9.0.0/HDK 25.2.1 保持不变。
- 复现验证：回退 0.3.9 即复现。
- 若再次遇到，建议向 Mooncake 上游提供 CANN/HDK/Mooncake 版本组合寻求兼容矩阵说明（issue 内维护者亦在追问版本匹配指引）。

## 判别

- 与 VLLM-ASC-10532（Mooncake transfer timeout → native segfault）区分：本条无 segfault，put 阶段即失败、伴随 MR 注册/channel init 错误。
- 触发特征：升级 CANN 9.0 后出现 → 先查 Mooncake 版本是否配套。

## 建议 triage 路由症状

新形态签名（kvpool put key / Mooncake / 503900）未被 inference_interrupt 现网正则覆盖；建议在 inference_interrupt 分支补 `mooncake|kv.?pool|kv pool|Failed to put key|ErrorNo: 503900`（可选，needs-review）。
