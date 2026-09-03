# VLLM-ASC-7792: mooncake kv_both + GLM5 KV 传输报 "Transfer slice failed with status: 503900"（HcclBatchPut ret=4 Can't find remoteBuffer by key）——需 HCCL_INTRA_ROCE_ENABLE=1

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest r2-sed-g1（2026-09）产出，进 inbox 待 groom 分诊；不改正式 knowledge/ 目录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/7792
**fix 跟踪**：无 vllm-ascend fix PR。维护者 Pz1116（2026-03-30）判为 HIXL 侧配置/缺陷并给 env 解：`export HCCL_INTRA_ROCE_ENABLE=1`；参考 gitcode cann/hixl issues #133/#150；issue 当日 weiguihua2 关闭 completed（label resolved）。作者原引用的 tutorial（pd_colocated_mooncake_multi_instance）部分内容过时，维护者称将更新（以 kv_pool.md 为准）
**时间**：2026-03-28（报）~ 2026-03-30（env 修复验证后关）
**框架/平台**：vllm-ascend 0.17.0rc2.dev0+ge20f0b1a0、CANN 8.5.1、torch-npu 2.9.0；910B3 ×8（单机）；mooncake kv_both + GLM-5-w4a8（KV 经 ascend-direct/RoCE 传输）
**category**：interrupt
**investigation_quality**：medium（维护者给 env 解 + 用户复验通过；根因在 HIXL/通信配置层，未做本地代码级展开；issue 简短）
**verification**：upstream-maintainer-confirmed（无 fix PR；resolution=env 配置，维护者给出并确认）
**novelty**：new_pattern——库内 mooncake/KV pool 族 case（10532 native segfault、11343 kv_port PP 偏移、11459 lazy_init、13934 transfer group、8938 ZMQ 端口）机制/签名均不同；无 503900/HcclBatchPut remoteBuffer case

## 现象摘要

mooncake `kv_both`（同节点多实例 PD，KV pool 经 ascend-direct/RoCE 传输）+ GLM-5-w4a8，KV put 持续失败：

```
ascend_direct_transport.cpp:836] Transfer slice failed with status: 503900
mooncake_backend.py:85] Failed to put key ['...'],res:[-800]
PLOG: HCCL ... HcclBatchPut: Logic error ... hccl_one_sided_conn.cc:270,BatchWrite ... ret=4 Can't find remoteBuffer by key
GE ... operator(): ErrorNo: 503900 Failed to invoke HcclBatchPut
```

## 一句话根因

mooncake/ascend-direct（HIXL ADXL）的 KV one-sided 传输在 HCCL 层做 batch put（HcclBatchPut），需要 intra-node 通信也走 RoCE 才能匹配远端 buffer 注册（默认 intra-node 走 PCIe/HCCS，`Can't find remoteBuffer by key` ret=4 → GE 503900）；设 `HCCL_INTRA_ROCE_ENABLE=1` 后传输恢复。属部署配置要求（相关 tutorial 表述过时），不是模型/量化/mooncake 版本缺陷。

## fix

- 启动前 `export HCCL_INTRA_ROCE_ENABLE=1`（维护者 Pz1116 给出；用户实测报错消失）。
- 参考：gitcode cann/hixl issues #133 / #150；部署文档以 kv_pool.md 为准（原引 tutorial 部分过时，勿按它逐项排查）。
- 判别：503900 + `Can't find remoteBuffer by key`（HcclBatchPut ret=4）+ mooncake/ascend-direct KV 传输 → 通信拓扑配置问题。

## 弯路与级联

- mooncake_backend `Failed to put key ... res:[-800]` / client_service `TRANSFER_FAIL` 是 503900 的上层包装，别逐层追。
- "transfer failed and disconnect to:<ip>:<port>" 是断开重试副作用，非根因。
- 原引 tutorial（pd_colocated_mooncake_multi_instance）信息过时——先查 kv_pool.md 官方配置清单。

## 建议 triage 路由症状

`503900` 不在 inference_interrupt 现有正则 → 建议补 `503900|Can't find remoteBuffer by key`（随 case 一并提交，needs-review）。
