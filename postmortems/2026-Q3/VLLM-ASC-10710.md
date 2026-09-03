# VLLM-ASC-10710: DSV4-Flash-w8a8-mtp 完全相同串行请求 Prefix Cache 命中率恒 0%——混合压缩 KV（compression_ratio 128）把最小命中长度放大为 block_size×128（block128→16k），10k 级前缀永不命中

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest sed-g2 批次 1 产出（人工筛出的高质量 closed issues），进 inbox 待 groom 分诊。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/10710
**fix 跟踪**：无单 issue 绑定的合入 PR——维护者（MengqingCao）机制定论 + 配置建议（block_size=32）；残案由升级 v0.23.0rc1 解决（用户 Li-ft/milkyfun0 实测）；跟踪 RFC #10517（上游 vllm PR #43447 等）
**框架/平台**：vllm-ascend 0.20.2rc1（复现）/ 0.22.1rc1（残案）/ 0.23.0rc1（解决）；A3 8×NPU
**category**：performance
**investigation_quality**：medium（维护者给出命中粒度数值机制 + 用户两个版本点的实测；block_size=32 建议本身未在 0.20.x 上单独闭环验证——0.22.1rc1 上 block32 仍失败）
**verification**：upstream-maintainer-confirmed（维护者 MengqingCao 线程确认机制与解决方向；无指向本 issue 的单一 fix PR，版本升级 + RFC 系列合入解决）
**novelty**：new_pattern——库内无"混合压缩 KV prefix 命中粒度/最小命中长度"族；相近 13356(memcache 重叠)/13973(P 节点回归) 机制不同（见 yaml pre-triage）

## 现象摘要

DeepSeek-V4-Flash-w8a8-mtp（A3 8NPU，DP2×TP4 + EP，CANN 9.0.0）启用本地 Prefix Cache（`--enable-prefix-caching`，`--block-size 128`，非 PD 分离、非 MTP、非 chunked-prefill、串行请求）：

- cache_config 显示 `enable_prefix_caching="True"`，`prefix_cache_queries_total` 正常增长；
- `prefix_cache_hits_total` 恒 0、`prompt_tokens_by_source_total{source="local_cache_hit"}` 恒 0——完全相同请求（≈10.1k prompt）串行 8 次、及 system-prompt 复用对照组，命中率全部 0.00%；
- 请求均 HTTP 200 正常返回，服务无崩溃——纯性能问题（前缀全量重算）。

## 一句话根因

DSV4-Flash 属混合压缩 KV（compression_ratio=128）：最小可命中前缀长度被放大为 **block_size × 128**——block_size=128 时下限 16k（开启投机解码/MTP 再翻倍为 32k），而线程内请求前缀仅 ≈10.1k，永远低于命中下限 → 即便完全相同请求也 0 命中、每次全量 prefill。

## fix

- **配置**：`--block-size 32` → 最小命中长度降为 4k（MTP/投机开则 8k）——维护者推荐（0.20.x 代码已支持 block_size=32）。
- **版本**：0.22.1rc1 上即便 block_size=32 仍复现（用户 32k 用例）→ 升级 **v0.23.0rc1** 后消失（prefix-cache/混合 KV 系列修复合入，见 RFC #10517：vllm-ascend #10009 等）。
- 跟踪：RFC #10517（hybrid 模型 prefix caching，PD 场景为主）+ 上游 vllm #43447/#45845（retention interval）。

## 建议 triage 路由症状

现有 inference_performance 已有 `cache.*hit.*0|prefix.*cache.*miss|缓存命中.*0` 可路由——本 case 命中率 0 属该正则，无需新增。
