# VLLM-ASC-13356: PD 分离开启 memcache 性能劣化（lookup 与本地 prefix cache 完全重叠 → 零边际收益仍付 RPC 开销）

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/13356
**fix 跟踪**：PR #12783（https://github.com/vllm-project/vllm-ascend/pull/12783 ）及后续优化，官方建议测 23.0 分支最新 commit；用户未回测，线程 stale 关闭
**时间**：2026-08-03 ~ 2026-08-25（wait-feedback 后 stale 关闭）
**框架**：vllm-ascend 0.23.0rc1 + torch_npu 2.10.0.post2 + HDK 26.1（npu-smi 26.1.0.b087）
**平台**：A3 (910C)，DeepSeek-V4 PD 分离 + memcache
**category**：performance
**investigation_quality**：medium
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（Phase B 批量 to-postmortem）

## 结构化 case

草稿：`postmortems/inbox/VLLM-ASC-13356.case.yaml`（Tier 2 入库前待 groom 分诊）。

## 一句话根因

PD 分离开启 memcache（AscendStoreConnector）后，每请求 `lookup()` 命中但 load 0 token：memcache 命中与 vLLM 本地 prefix cache 完全重叠（`num_external_hit_tokens <= num_computed_tokens`）时 `pool_scheduler.py` 算出 `need_to_allocate = 0`。前缀复用 workload 下 memcache 零边际收益、仍付 lookup RPC 开销，吞吐相对"仅本地 prefix cache / 仅 Mooncake"基线回退——官方确认是优化点而非 bug，PR #12783 及后续已优化。

## 弯路与级联

- 官方立即定性"optimization, not a bug"（上游 vLLM 同行为），无根因辩论；issue 停在 wait-feedback 无人回测即 stale 关闭——闭环证据止于官方定性 + PR 链接，未获用户实测确认。
- 定性局限：线程无 profiler 数值（只有截图），"吞吐回退"无量化对比数据，quickly_check 只能用代码条件作为检索信号。
