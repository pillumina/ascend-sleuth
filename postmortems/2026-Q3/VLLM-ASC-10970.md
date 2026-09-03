# VLLM-ASC-10970: DSV4-Flash PD 分离 P 节点加 VLLM_PREFIX_CACHE_RETENTION_INTERVAL 后 prefix cache 命中归 0——eagle/MTP bit 未传播到 hybrid cache sibling manager，写读路径 block 差一 → min-over-groups 命中坍缩

> 源是结构化 GitHub issue 线程 + 修复 PR（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest sed-g2 批次 2 产出（人工筛出的高质量 closed issues），进 inbox 待 groom 分诊。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/10970
**fix 跟踪**：PR #11107（[Performance] DSV4 prefix cache hit rate optimize，merged 2026-07-01，由本 issue 提出人 HF-001 提交）；issue 2026-07-07 closed
**框架/平台**：vllm-ascend v0.23.0 / NPU-A2 四机 PD 分离（P 节点）；DeepSeek-V4-Flash（bf16 或 HW-w8a8）+ MTP(num_speculative_tokens=2)
**category**：performance
**investigation_quality**：medium（issue 现象与观察充分 + fix PR 含机制与单测；PR 初提时"初步测试、进一步测试中"，合入后 issue 关闭）
**verification**：upstream-fix-merged（fix PR #11107 merged 2026-07-01）
**novelty**：variant_of VLLM-ASC-13356——同"PD 分离 P 节点 DSV4 prefix cache 收益退化"族；增量=13356 是 memcache lookup 与本地 cache 重叠（pool_scheduler need_to_allocate=0），本条是 retention/async-scheduling 配置面 + hybrid cache 管理器 use_eagle 传播缺失（写读 block 差一）——机制不同、修复不同（PR #11107）

## 现象摘要

A2 四机 PD 分离（P 节点 DP2×TP8 + EP + MTP2）跑 DeepSeek-V4-Flash：多并发时 P 节点 prefix hit rate 仅 ~10%；参考上游 vllm PR #43447 加 `VLLM_PREFIX_CACHE_RETENTION_INTERVAL=16384` 后，**连两条相同请求都不命中 prefix cache**（命中归 0，未得优化反恶化）。

- 线程观察（s-jiayang）：移除 P 节点异步调度后该变量"似乎起作用"——但这不是正解，只是暴露调度/执行路径差异。
- 维护者（MengqingCao）：该特性当时未在 vllm-ascend 完全适配，请 HF-001 基于最新 main 适配；HF-001 提 PR #11107 修复 DSV4 prefix cache hit rate 0%。

## 一句话根因

DeepSeek-V4 混合 KV cache 中 EAGLE/MTP 层所在 attention group 的 manager 需要 `use_eagle=True`：写路径（`cache_blocks → reachable_block_mask`）按 `use_eagle` 保留 checkpoint tail，读路径（`find_longest_cache_hit`）对合并组应用 `drop_eagle_block`。vllm-ascend 的 `AscendHybridKVCacheCoordinator.verify_and_split_kv_cache_groups` 只按 `eagle_group_ids` 标记、未传播给同 spec 的 sibling manager → manager 保持默认 False → 写侧保留 tail 比读侧 eagle peek 边界少一个 block → SWA group 永不命中 → min-over-groups 混合命中坍缩为 0%（PR #11107 机制与单测）。

## fix

PR #11107（merged 2026-07-01）：`patch_kv_cache_coordinator.py` 在 `verify_and_split_kv_cache_groups` 中把 `use_eagle=True` 传播到 eagle 所在 attention group 的全部 sibling manager（对齐上游 HybridKVCacheCoordinator 语义；上游只标单组、vllm-ascend 读路径按合并组 drop）。

- 修复版本：含 PR #11107 的版本（main 2026-07-01 后）。
- retention interval（VLLM_PREFIX_CACHE_RETENTION_INTERVAL）后续由上游 vllm #45845 支持（RFC #10517 记录"no adaptation required"于 vllm-ascend）——本 case 的核心故障是 eagle bit 传播，不是 retention 变量本身。

## 建议 triage 路由症状

现有 inference_performance 已有 `cache.*hit.*0|命中.*为0|prefix.*cache.*miss` 可路由（命中归 0 属该正则），无需新增。
