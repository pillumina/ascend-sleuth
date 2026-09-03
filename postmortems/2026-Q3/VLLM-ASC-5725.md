# VLLM-ASC-5725: Qwen3-Embedding 同串二次请求向量不一致（Cosine ~0.58）——prefix cache 命中路径把 embedding 引入不支持 prefix caching 的注意力算子（静默错输出）

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest r2-sed-g1（2026-09）产出，进 inbox 待 groom 分诊；不改正式 knowledge/ 目录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/5725
**fix 跟踪**：PR #7452 [BugFix][APC] Fix prefix caching support for embedding models（merged 2026-03-28）→ main；cherry-pick #7894 进 v0.18.0（merged 2026-04-01）。issue 2026-06-04 关闭 completed
**时间**：2026-01-08（报）~ 2026-06-04（关）
**框架/平台**：vllm-ascend v0.13.0rc1（复测至 v0.14.0rc1/v0.15.0rc1 仍现）；910B（单卡 TP1）；Qwen3-Embedding-0.6B（--convert embed）
**category**：precision
**investigation_quality**：medium（reporter 给出可复现单测 embedding_test.py + 关 prefix cache 对照；根因代码级解释来自 fix PR #7452，非 issue 线程）
**verification**：upstream-fix-merged（fix PR #7452 + backport #7894）
**novelty**：new_pattern——库内 prefix-cache 相关 case 均为命中率/性能面（10710 命中率恒 0%、10970 retention、13356 memcache 重叠），无"prefix cache 命中致 embedding 输出静默错误"精度 case

## 现象摘要

Qwen3-Embedding-0.6B 起 embedding 服务，同一字符串**第一次**与**第二次**请求返回的向量不一致：

- 首算 vs 原生 vLLM：Cosine ~0.9997（首算是对的）
- 二次及以后（命中 prefix cache）结果稳定但错：与首算 Cosine ~0.585、与原生 vLLM ~0.581
- 显式关闭 prefix cache 后不一致消失（dv0 实测 workaround 有效）

## 一句话根因

attention 路由条件过宽：pooling/embedding 模型一律走 `_forward_encoder_attention()` → `npu_fusion_attention`，而该算子**不支持 prefix caching**——命中缓存后数值错乱，embedding 输出静默错误。fix（PR #7452，`vllm_ascend/attention/attention_v1.py`）：条件加 `and not causal`，非因果 encoder 才走 npu_fusion_attention，causal 的 embedding 走支持 prefix caching 的 `npu_fused_infer_attention_score`。

## fix

- 升级 vllm-ascend ≥ v0.18.0（main 由 PR #7452 修复，v0.18.0 由 #7894 backport；<0.18.0 均有风险，0.13–0.15 rc 实测复现）。
- 旧版本 workaround（reporter 实测）：显式关闭 prefix cache（CLI `--no-enable-prefix-caching`，v0.11 起默认开启）。
- 判别：同模型原生 vLLM（GPU）首算一致、缓存命中后偏差 >1e-2 → 本 case；不要当量化/权重/模型问题排查。

## 弯路与级联

- "首算对、缓存命中后错" 是该类 bug 的判别特征——命中缓存路径与首算路径走了不同算子。
- 0.13–0.15 三个 rc 都复现，别反复升级旧主线（修复 2026-03-28 才进 main）。
- vLLM 自身 embedding 输出正常 → 不是模型/API 用法问题。

## 建议 triage 路由症状

precision 数值比对 case 无独立路由正则；症状文本含 "embedding"/"向量不一致"，可考虑在 inference_precision 补 `向量不一致|embedding.*inconsistent`（可选，needs-review）。
