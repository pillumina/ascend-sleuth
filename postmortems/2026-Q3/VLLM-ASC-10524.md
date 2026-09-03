# VLLM-ASC-10524: GLM-5.1-w8a8 PD 分离偶现精度问题（Claude Code 场景）——graph capture(dummy run) 读未初始化 slot_mapping

> 源是结构化 GitHub issue 线程 + 修复 PR（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest sed-g1 批次 1 产出，进 inbox 待 groom 分诊。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/10524
**修复 PR**：https://github.com/vllm-project/vllm-ascend/pull/11774（[BugFix][Worker] Reset slot_mapping to pad id for dummy graph capture，merged 2026-07-11，merge commit b9acec8）
**框架/平台**：vllm-ascend v0.18.0/v0.20.2 复现（PR 测试 env v0.23.0）/ A3（910B 系 4 机 1P1D PD 分离 + Mooncake KV transfer）
**category**：precision
**investigation_quality**：high（并发消融定位触发条件 + 维护者代码级根因 + merged fix PR 闭环）
**verification**：upstream-fix-merged（fix PR #11774）
**novelty**：new_pattern——库内 PD 偶发精度族（11169/12030/12957）根因分别为外部 connector/流式 parser/流同步，本条为"graph capture 未初始化 slot_mapping"（dummy-run 正确性），无重叠

## 现象摘要

GLM-5.1-w8a8 4 机 1P1D PD 分离（P：TP16/DP2；D：TP4/DP8、FULL_DECODE_ONLY 图模式 + MTP），对接 Claude Code（Anthropic 协议被转成 completions 接口）压测时**偶现精度问题**：

- 两个 DP 同时存在一长一短两个请求时大概率出问题；再次发送同请求恢复；服务日志无报错、无 Mooncake transfer 失败。
- v0.18.0 与 v0.20.2 同样复现；精度数据集测试得分正常（仅偶现复读等输出劣化，无系统乱码）。

## 一句话根因

dummy/graph-capture run 不走 `_prepare_inputs()`，slot_mapping 未填充却被图捕获读取到**上一个 run 残留的未初始化值**（PD 分离 + 多 kv cache group 下多个 group 的 slot_mapping 都未清）→ 捕获进图的 KV 索引含垃圾值 → decode 阶段偶发错误输出。修复：dummy run 把所有 kv cache group 的 slot_mapping 重置为 pad id（PR #11774）。

## fix

- 升级到含 PR #11774 的版本：main 2026-07-11 合入（b9acec8）；经 tag ancestry 校验首个含修复 tag 为 **v0.24.0rc1**（v0.23.0 / v0.23.0rc1 分支未包含此 commit）。
- 触发版本 v0.18.0 / v0.20.2（用户实测）→ 受影响区间 `<0.24.0rc1`（软判：0.23.0 用户未复测，不硬排除）。
