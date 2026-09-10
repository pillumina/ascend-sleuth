# VLLM-ASC-14121 —— AscendStore MemCache 首请求懒初始化把 TP rank 时序撕裂

**源是结构化 issue（含完整生产证据链与同拓扑复测）——按 to-postmortem 只写指针，不重写。**

- **原文**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/14121
- **入库时间**：2026-09-10（issue-ingest 批次：拉取 17 / 候选 9 / 通过 1）
- **框架**：vllm-ascend（推理）
- **category**：interrupt
- **verification**：`upstream-maintainer-confirmed`（维护者确认成因与修复版本；报告人同拓扑复测通过）
  - 注意：issue 状态是 `closed not_planned`，但那是 **stale 机器人自动关单**，不是"无定论"——维护者 bowgneo 已确认"懒初始化是 HDK <26.1 的驱动规避手段，HDK 26.1+ 已解决"，报告人 ZhengDeL 随后在同拓扑复测通过。
- **结构化 case**：`knowledge/inference/vllm-ascend/interrupt/VLLM-ASC-14121.yaml`（已升格 Tier 2）
- **pre-triage**：`variant_of VLLM-ASC-11459`（同族 = kv-pool store 懒初始化路径缺席守卫；增量 = backend 不同 / 失效形态不同 / 根因含驱动规避语义）
- **升格**：2026-09-10 groom（issue-ingest 批次唯一通过项，owner 指示直接并入）

## 一句话根因

DSV4 压缩 KV 路径上 MemCache backend 以 `lazy_init=True` 创建（该懒初始化本是 HDK <26.1 的驱动规避手段），
首请求时才 `store.init()` 且失败即 `assert res == 0`——TP 各 rank 初始化完成/失败/重试时刻不一致，
先完成的 rank 进入模型集合通信而 peer 仍在 BM 组重入，集合通信序分叉 → EI0002/507034 → EngineCore 退出。

## fix

升 HDK/driver 至 26.1.1（firmware 9.0.0.9.220）+ Prefill/Decode 两侧显式 `backend_kwargs[lazy_init] = False`
（让 MemCache 在引擎启动期完成初始化）。两步需同时做。

## 沉淀时保留的 open point

报告人提到测试镜像/build **仍默认 `backend_kwargs[lazy_init] = True`**（body 在此处被截断）——
即框架侧默认值可能尚未改，后续同环境仍可能复现。转正时建议作为跟进项保留。
