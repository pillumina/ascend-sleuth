# VLLM-ASC-10876: DeepSeek-V4-Flash chunked prefill 偶发长尾（forward_ms 4s+，TTFT P90 7.3s）——triton rms kernel TOTAL_BATCH constexpr 致频繁重编译

> 源是结构化 GitHub issue 线程（用户深度打点/版本对比/commit 定位），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest sed-g1 批次 1 产出，进 inbox 待 groom 分诊。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/10876
**修复 PR**：https://github.com/vllm-project/vllm-ascend/pull/11211（[Performance] Delete the tl.constexpr of total_batch param in triton_rms_kernel，merged 2026-07-03，commit 76d338a72）
**框架/平台**：vllm-ascend v0.20.2rc1/v0.21.0rc1 复现（thread 顶部 env 0.19.1-dev 打点）、v0.23.0rc1 起修复 / Ascend 910B2 ×8（TP8 单机，enable-dsa-cp/flashcomm1 开启）
**category**：performance
**investigation_quality**：high（用户逐 chunk 打点定位 + 对齐实验 + v0.21 vs v0.23 版本对比定位到 commit 76d338a72）
**verification**：upstream-fix-merged（fix PR #11211，含于 v0.23.0rc1）
**novelty**：variant_of VLLM-ASC-13973——同族 dsa_cp/prefill 性能回归（13973=v0.26 dsa-cp 解耦引入额外 fc1 通信+SFA DCP block table 宽度；本条=v0.21 dsa_cp_forward_prefill 里 triton rms kernel constexpr 重编译尖峰），同一功能路径、不同机制与版本

## 现象摘要

serve DeepSeek-V4-Flash（w8a8，TP8，chunked prefill + prefix cache + enable-dsa-cp），多轮长对话（首轮 ~5 万 token）压测：

- **prefill 长**：并发 1、max-tokens=1 极限 prefill 场景平均 5.6s、TTFT P90/P99 ~7.3s。
- **prefill 不稳**：偶发 forward_ms=4000+ms（正常 chunk ~450ms，10x）；打点发现只要单批 token 数 ≠ chunked_prefill_size 边界就有概率触发（实样：`total_scheduled_tokens=3122 forward_ms=4381.53`）。
- 用户用"padding 到 chunk 大小"的 workaround 后 TTFT 从 6.4s 降到 ~1.5s（后来理解 = 只是约束了 total_batch 取值、规避重编译）。
- **版本对比（用户收尾）**：v0.21 偶发 4s+ spike；v0.23 各 token 数 forward 稳定 ~400ms。定位到 `dsa_cp_forward_prefill`（AscendDSACPImpl._forward，vllm_ascend/attention/context_parallel/dsa_cp.py）→ fix commit 76d338a72。同 fix 还关联 #11209（triton_q_rms 长跑偶现 ~3s 卡顿）——同根因不同表象。

## 一句话根因

dsa_cp_forward_prefill 路径里的 triton rms kernel（vllm_ascend/ops/triton/rms_norm.py）把 TOTAL_BATCH 标成 tl.constexpr：chunked prefill 每批 token 数变化 → 每次新 shape 都触发 kernel 重编译（每次 ~4s 级），表现为偶发超长 prefill/TTFT 长尾。修复：去掉该 constexpr（PR #11211），变长 batch 复用同一 kernel，perf 几乎无损。

## fix

- 升级到含 PR #11211 的版本：main 2026-07-03 合入（76d338a72），**v0.23.0rc1（2026-07-19）起包含**（tag ancestry 已校验）；用户 v0.23.0rc1 实测不可复现。
- 触发区间：<0.23.0rc1（0.20.2rc1 / 0.21.0rc1 实测复现；0.19.1-dev 打点数据同现）。
- 旧版 workaround（padding 到 chunk，用户 hack）随修复不再需要。
