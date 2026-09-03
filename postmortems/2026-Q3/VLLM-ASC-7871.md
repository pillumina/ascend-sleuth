# VLLM-ASC-7871: KV offloading + kv_load_failure_policy=fail 请求失败路径触发 metrics 负增量 ValueError → 表面 HTTP 500/首 token 超时

> 源是结构化 GitHub issue 线程（4 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/7871
**fix 跟踪**：PR #8959（vllm-ascend，"[P/D][BugFix] Fix for transmit kv cache failure"，merged 2026-05-08 13:32:10，与 issue 关闭 13:32:12 同刻，维护者 MengqingCao 关闭）；上游 vllm 侧另有 #37160（workaround）/ #37460（长期修复候选），见评论#2
**时间**：2026-03-31 ~ 2026-05-08（completed）
**框架**：vllm-ascend（PD 分离 + KV offload + external KV backend）；触发版本 thread 未给（vllm/v1/metrics 路径，0.18/0.19 代）
**平台**：多节点 TP16（PD 分离），具体型号 thread 未给
**category**：interrupt（运行期请求失败被升级为 HTTP 500/内部错误）
**investigation_quality**：high（issue 自带完整 traceback + TP rank 间 load 结果不一致日志 + 修复 PR #8959 合并即关闭）
**verification**：upstream-fix-merged（fix PR #8959）
**pre-triage**：new_pattern（现库无 KV load 失败路径/metrics 负增量 case；邻近 VLLM-ASC-11343/13934 是 KV 传输 timeout/索引越界，非失败路径计数 bug）

## 现象摘要

- PD 分离 + KV offloading + external KV backend，多节点 TP16，配置 `kv_load_failure_policy: fail`。
- 同一请求跨 TP rank KV load 结果不一致：[Rank1] success_blocks=173/173 SUCCESS vs [Rank0] success_blocks=6/173 SUCCESS（部分 rank 只加载了部分块却报 SUCCESS）。
- scheduler 按 policy 失败该请求：`[scheduler.py:2192] Failing 1 request(s) due to KV load failure (failure_policy=fail, 21376 tokens affected)`。
- 失败路径再触发 metrics 异常：`ValueError: Counters can only be incremented by non-negative amounts.`（vllm/v1/metrics/loggers.py 把负 delta 递给 Prometheus counter）。
- 前端表现：`request get chunk timeout ... exceeds 20.0 s` + `internal server error`（HTTP 500）——本应干净的策略失败被升级为内部错误，用户侧首 token 超时。一个 workload：1066 请求中 183 个受影响。

## 一句话根因

两层问题叠加：① KV load 跨 TP rank 不一致（部分块成功即整请求报 SUCCESS，真实加载失败未对齐）；② 失败请求路径的 metrics 记录把负增量传进 Prometheus counter 抛 `ValueError: Counters can only be incremented by non-negative amounts`，把策略性失败（kv_load_failure_policy=fail）升级成内部错误/HTTP 500。PR #8959 修复 KV 传输失败块的处理（失败块标 invalid），issue 随之关闭。

## fix

升级到含 PR #8959 的 vllm-ascend（merged 2026-05-08）。上游 vllm 侧 #37160/#37460 亦在治理同一 metrics 失败路径（workaround/长期修复）。无配置 workaround。

## 弯路与级联

- issue 无弯路；指标异常是**失败路径的次级现象**（期望行为=按 policy 干净失败），判型以 `ValueError: Counters can only be incremented` + `Failing ... due to KV load failure` 两行为准，勿当独立 metrics bug 排查。
- 级联：frontend first-token timeout / HTTP 500 均为该失败升级的对外表现。
