# VLLM-ASC-7659: 双机 A2（DP>1，多 ApiServer）部署看不到 Engine 统计日志/KV cache 利用率——vLLM 在 api_server_count>1 时静默禁用 stats logger（可观测性缺失）

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest r2-sed-g1（2026-09）产出，进 inbox 待 groom 分诊；不改正式 knowledge/ 目录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/7659
**fix 跟踪**：无 merged fix PR。维护者 MengqingCao（2026-03-26）确认根因在 vLLM：DP 下 api_server_count>1 时 stats logging 被禁用（"will try to fix it in vLLM later"）；作者本地 patch vLLM（去掉该 guard）后日志恢复并自行关闭 issue（2026-03-27）。上游 vLLM 修复状态：PR #35291（2026-02）/ #37950（2026-03）均 closed-unmerged，#44390（2026-05，enable per-engine stats logging when api_server_count>1）仍 open
**时间**：2026-03-26（报）~ 2026-03-27（本地 patch 验证后自关）
**框架/平台**：vllm-ascend（报告环境 0.17.x/0.18.0 开发版）；A2 双机 DP2（每机 TP8+EP）；DeepSeek / Kimi-K2.5 w4a8
**category**：interrupt（按清单；实际为可观测性缺陷——功能/日志静默缺失，非崩溃）
**investigation_quality**：medium（维护者源码级确认根因；fix=本地 patch 作者验证，无上游合并代码）
**verification**：upstream-maintainer-confirmed（维护者确认根因与修复方向；上游 vLLM 修复未合入）
**novelty**：new_pattern——库内无 stats logger/DP 多引擎可观测性 case（KVPool/metrics 相关 case 均不同机制）

## 现象摘要

双机 A2 DP 部署（--data-parallel-size 2，出现 2 个 ApiServer/Engine）DeepSeek 或 Kimi2.5 时，服务端**不再输出** `Engine 000: Avg prompt throughput ... GPU KV cache usage: x%` 统计日志；单机（DP=1）正常。请求/服务本身正常，纯可观测性缺失。

## 一句话根因

vLLM AsyncLLM 构建 stats logger 时的 guard 过宽：`client_count > 1`（DP>1 → 多 ApiServer）就禁用 stats logging（原意避免多引擎统计不完整），直接把默认 stat logger 工厂整体跳过 → DP 部署无任何 Engine 统计/KV cache 利用率输出。vllm-ascend 双机 DP 正落在这个分支。上游 vLLM 修复尝试（#35291/#37950）均未合入、#44390 仍 open。

## fix

- 本地 patch（issue comment 4 给出，作者验证）：在 vLLM loggers 构建处把 `if client_count > 1: ... 禁用` 分支去掉/注释，恢复默认 logger 工厂（per-engine 统计出现）。
- 等待上游 vLLM 修复合入（当前 #44390 open）；升级前检查该 guard 是否仍存在。
- 注意（已知次生噪声，勿当本 case 未解决）：patch 后 DP 下每 Engine 各自打印 prefix cache hit rate、多 ApiServer 间数值不聚合（qaz2883383），Prometheus/grafana 双机聚合也不完美——需要聚合口径时按官方 metrics（curl /metrics grep prefix_cache）为准。

## 弯路与级联

- 现象"单机有、双机无"是指向 DP 多 ApiServer 分支的直接线索，不是配置漏开。
- 恢复日志后出现的 per-Engine 命中率/监控数值不聚合是**另一个已知缺陷**（metrics 聚合口径），与"日志缺失"分开跟踪。

## 建议 triage 路由症状

无报错文本（缺失型症状），无新正则可加；靠 symptoms 文本（DP/双机 + 无 Engine 统计日志）路由，needs-review 给 groom。
