# VLLM-ASC-13964: Decode DP rank 静默停滞（async scheduling 下 SWA/chunked-local KV block 提前剪枝复用）

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/13964
**fix 跟踪**：https://github.com/vllm-project/vllm-ascend/pull/13518（作者确认 "Closing as resolved by #13518"，修复后不复现）
**时间**：2026-08-11 ~ 2026-08-20
**框架/平台**：vllm-ascend 0.23.0rc1 + torch-npu 2.10.0.post2 + CANN 9.0.1；A3 (910C)，DeepSeek-V4-Flash W8A8 + MTP + Mooncake PD 分离
**category**：interrupt
**investigation_quality**：high
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（Phase B，第 2 批）

## 结构化 case

草稿：`postmortems/inbox/VLLM-ASC-13964.case.yaml`（Tier 2 入库前待 groom 分诊）。

## 一句话根因

async scheduling 下 `num_computed_tokens` 可能包含已调度但输出尚未被处理的批次 token，SWA/chunked-local KV block 按这个乐观计数被提前剪枝复用，in-flight attention step 仍引用已回收 block → decode 各 DP rank 静默停滞（running>0 但 generation/completion 计数冻结，健康检查仍 200）；PR #13518 修正生命周期记账后不再复现。

## 弯路与级联

- 先怀疑 MTP sampling NaN（关联 #12725）、#13648 dummy-batch、#13826 DP ACLGraph 模式同步，均被作者排除——本 case 是 KV 生命周期记账问题。
- 线程内引用 #10237（all-placeholder speculative output）与 #13863（stale accepted-token counts）作为 related，但非根因。
- 级联噪声：停滞数小时后的 `MQ RuntimeError("cancelled")` 与级联 EngineDeadError 是 worker-exit 阶段现象，不是根因；`temperature 0.0001 < 0.01` 的 sampling 警告与 NaN 理论相关但未证实。
- 判别特征：静默 hang 无任何 ERROR/traceback/HCCL timeout，只能靠 per-engine Prometheus 计数（running 冻结 + generation/completed 不增）识别——quickly_check 按指标形态设计而非 grep 错误签名。

## 后续回归

#13518 引入更保守的 admission 容量收缩，容量回归由 #14678 跟踪（不主张 revert #13518）。
