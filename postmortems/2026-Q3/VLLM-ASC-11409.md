# VLLM-ASC-11409: RFork 二次实例启动失败——pre-transfer post-process 在接收端权重仍空时跑 shared-expert 一致性校验 → NaN mismatch abort

> 源是结构化 GitHub issue 线程 + 修复 PR（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest sed-g2 批次 2 产出（人工筛出的高质量 closed issues），进 inbox 待 groom 分诊。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/11409（issue 正文为空——截图上传失败，签名取自标题 + 关联 PR）
**fix 跟踪**：PR #11497（[BugFix][RFork] Fix RFork GLM fallback crashes，Fixes #11409，未合入，被 **#12995** 取代合并 2026-08-06）；同源基础能力 PR #10128（RFork 量化/post-load 传输，merged 2026-06-22）
**框架/平台**：vllm-ascend RFork loader（量化 DeepSeekV2 族，如 GLM-5 W4A8 + MTP）；fix 上下文 A2-910B
**category**：interrupt
**investigation_quality**：medium（issue 正文无日志；根因/修复取关联 PR #11497 描述 + 用户"已解决"确认；修复最终以 #12995 合入并带单测）
**verification**：upstream-fix-merged（issue 用户按 #11497 实测解决；#11497 未合入、其合并形态 #12995 merged 2026-08-06——见 yaml detail）
**novelty**：new_pattern——库内无 RFork loader 族（_index 全量比对）；启动/加载 crash 存量（11208 ModuleNotFound、12345 host OOM 等）机制均不同

## 现象摘要

RFork（模型 fork 加载）第二次实例启动报：

```
FusedMoE shared experts split computation does not match the integrated computation.
max absolute difference:nan  integrated output-sum:nan,norm:nan  split output-sum:nan,norm:nan
```

（同线程前置日志："SharedFusedMoE shared experts split computation matches the integrated computation." 为正常对照行。）

## 一句话根因

RFork pre-transfer post-process 阶段（quantized + processed-layout 传输，PR #10128 引入后）`process_weights_after_loading` 会对 `AscendFusedMoE` 跑 shared-expert 一致性 forward 校验，而此时**接收端权重仍为空** → 输出 NaN → 一致性断言 NaN mismatch → RFork 传输中止、worker 启动失败。（#11497 修复点 1；同 PR 另修 RFork fallback 时 failed-model 的 process-global 注册残留导致 `Duplicate layer name`。）

## fix

PR #11497（→ 合并形态 #12995，merged 2026-08-06）：把 workaround 限定在 RFork loader——pre-transfer 的 layout-processing 调用临时用 `functools.wraps` 保存的原始 `process_weights_after_loading`（跳过 shared-expert 一致性 forward），调用后立即恢复 wrapper；fallback 路径只清 failed-model 自己的注册项再重初始化。非 RFork 路径的 FusedMoE wrapper 不受影响。

- issue 线程：#11497 提交后用户（TZP20020330tzjly）2026-07-08 确认"已经成功解决"；issue 2026-07-14 closed。
- 版本：合入形态 #12995 于 2026-08-06 进 main（合并 #12173 + #11497）。

## 建议 triage 路由症状

现有 inference_interrupt 的 `RuntimeError|AssertionError` + 启动失败类可兜底；若需精确签名可加 `shared experts split computation does not match`（随 case PR 提交，needs-review 由 groom 定夺）。
