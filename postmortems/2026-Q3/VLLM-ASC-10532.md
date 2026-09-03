# VLLM-ASC-10532: Mooncake KVPool（ascend direct/ROCE）传输超时后 pod segmentation fault——Mooncake native AscendDirectTransport 数据竞争，升级 Mooncake ≥ PR#1624

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest sed-g2 批次 2 产出（人工筛出的高质量 closed issues），进 inbox 待 groom 分诊。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/10532
**fix 跟踪**：fix 在**依赖仓库**——kvcache-ai/Mooncake PR #1624（[TE] remove target segment desc cache when disconnect，merged 2026-03-09）；vllm-ascend 侧无代码修复
**框架/平台**：vllm-ascend v0.18.0 + Mooncake（K8s 跨 2 节点、ROCE、ascend direct、Qwen3-8B）
**category**：interrupt
**investigation_quality**：medium（Pz1116 对 native 栈做了源码级定位（帧→函数→变更 PR），但用户未能复现、未做升级后验证，issue 无 before/after 闭环）
**verification**：upstream-fix-merged（fix PR #1624 在 kvcache-ai/Mooncake merged 2026-03-09）
**novelty**：variant_of VLLM-ASC-11459——同"Mooncake KV Pool/Ascend 传输路径故障"族；增量=11459 是 vllm-ascend backend python lazy_init AssertionError（线程 config 可见性），本条是 Mooncake native transport 数据竞争 segfault（timeout/disconnect 触发）、fix 在依赖仓库

## 现象摘要

4 个 Qwen3-8B pod（vllm-ascend v0.18.0 + Mooncake Store，K8s 跨 2 节点，ROCE）跑推理：前几个请求正常，随后 KVCachePool 出现 transfer timeout，pod crash `segmentation fault`。调大 TP 后出现频率降低。日志：

```
ascend_direct_transport.cpp:859] Transfer timeout to: <host>:<port>, ... ASCEND_TRANSFER_TIMEOUT ...
ascend_direct_transport.cpp:871] transfer failed and disconnect to:<host>:<port>
client_service.cpp:1181] Transfer failed for key Qwen3-8B@pcp0@dc...
!!! Segfault encountered !!!
File ..., in std::_Hashtable<...>::erase(...)      # std::unordered_set<SegmentID> 的 erase
File ..., in mooncake::AscendDirectTransport::processSliceList(...)
```

（IP 已脱敏；原文 URL 见源文档。）

## 一句话根因

Mooncake native `AscendDirectTransport::processSliceList()` 与传输 worker 池可并发，且 timeout/disconnect 失败路径也更新同一 `need_update_metadata_segs_`（`std::unordered_set<SegmentID>`）——find/erase/emplace 无锁 → transfer timeout/disconnect 反复触发时原生数据竞争 → `_Hashtable::erase` segfault。该共享 update set 由 Mooncake PR #1624 移除（disconnect 时改为直接删 stale target segment desc cache）。

## fix

**升级 Mooncake 到含 PR #1624 的版本**（merged 2026-03-09；建议直接升最新 Mooncake release）。`ASCEND_TRANSFER_TIMEOUT` 调大/网络稳定性改善只能降低 timeout 触发频率，**不能消除**旧实现的 native race。

- issue 由用户 2026-07-09 关闭（"问题随机出现、未能复现验证上述方案，先关，再遇到按方案处理"）。
- 前置逻辑：transfer timeout 是触发条件，segfault 落在 Mooncake Ascend direct transport 原生路径——不是 vllm-ascend python 层问题。

## 建议 triage 路由症状

现有 inference_interrupt 有 `internal error|crash|died` 可兜底，但**无 segfault/原生栈签名**——建议补 `segmentation fault|Segfault encountered|processSliceList|_Hashtable.*erase`（随 case PR 提交，needs-review 由 groom 定夺）。
