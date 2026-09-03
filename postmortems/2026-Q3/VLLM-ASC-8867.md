# VLLM-ASC-8867: PD 分离长稳压测部分 decode engine 不再收到请求——代理负载分数在请求取消时泄漏

> 源是结构化 GitHub issue 线程（3 条评论），按 to-postmortem 优化——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/8867
**fix 跟踪**：PR #8836（https://github.com/vllm-project/vllm-ascend/pull/8836，[BugFix] [P/D] release proxy resources on stream cancellation，merged 2026-04-30 main；改 `examples/disaggregated_prefill_v1/load_balance_proxy_server_example.py`）
**时间**：2026-05-03（报）～ 2026-06-29（closed completed）
**框架**：vllm-ascend（报体 collect_env 显示 0.13.0rc3，与 fix 线 main/v0.19.1 跨度大，版本区间存疑）；DSV4-Flash w8a8
**平台**：A3-910C（910C 双机 1P1D，decode TP1 DP16 = 16 engine 副本）
**category**：interrupt
**investigation_quality**：medium（长稳现象 + per-engine 日志证据充分；机制由 fix PR 描述；报者实测闭环）
**批量导入**：sed-g3（2026-09）
**pre-triage**：new_pattern（全库无 proxy/负载均衡/流取消 case；最近邻 13964 为 engine 内部记账问题，层不同）

## 结构化 case

`postmortems/inbox/VLLM-ASC-8867.case.yaml`（Tier 2 候选，待 groom 审）

## 现象摘要

910C 双机 1P1D 跑 DSV4-Flash w8a8，decode 侧 TP1 DP16（16 个 Engine/API server）+ `load_balance_proxy_server_example.py` 分发：长稳压测正常时 16 个 engine 都有请求（`Running: 75 reqs`）。数小时后某 engine（如 Engine 013 pid=107）日志停在 `10:06:42 Running: 0 reqs` 后再无新请求——进程存活、无任何 ERROR/traceback，其余 engine 正常服务。随时间掉出分发的 engine 增多，decode 服务能力静默下降。

## 一句话根因

用户取消/断开流式请求时抛 `asyncio.CancelledError`（继承 BaseException 而非 Exception），代理脚本 `except Exception` 收尾拿不到它 → 该 D 节点（engine）的负载分数从不释放、永久偏高 → 负载均衡不再向它路由。PR #8836 让取消也走负载分数释放路径。

## fix

升级/同步含 PR #8836 的版本（或修补示例代理脚本，CancelledError 与普通异常一致释放负载分）。报者实测 OK，issue closed completed。

## verification

**upstream-fix-merged**（fix PR #8836，merged 2026-04-30；报者实测通过）
