# VLLM-ASC-10892: 310P 上 Qwen3.6-35B-A3B-w8a8 过度思考/输出劣化——MoEGatingTopkSoftmax 单次 >1024 token 返回无效路由

> 源是结构化 GitHub issue 线程 + 修复 PR（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest sed-g1 批次 1 产出，进 inbox 待 groom 分诊。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/10892
**修复 PR**：https://github.com/vllm-project/vllm-ascend/pull/11391（[BugFix][Ops][310p]: fix the accuracy issue caused by MoEGatingTopkSoftmax，merged 2026-07-04，0dc58f8）
**框架/平台**：vllm-ascend v0.21.0rc1（镜像 v0.21.0rc1-310p-openeuler）/ 310P（Atlas 300I Duo，310P3）
**category**：precision
**investigation_quality**：high（维护者定位到算子级根因 + merged fix PR + 回归测试）
**verification**：upstream-fix-merged（fix PR #11391，含于 v0.23.0rc1）
**novelty**：new_pattern——库内无 310P MoE gating/路由精度 case（310P 存量均为 interrupt 算子/CANN 崩溃族）；与同表象的 8798（Qwen3.5 thinking 重复=模型能力）根因不同，两条互为判别

## 现象摘要

310P（300i duo，310P3 ×4）+ Qwen3.6-35B-A3B-w8a8（vllm-ascend v0.21.0rc1）serve，审核类长请求（~2700 token + 多图）出现"过度思考"：模型不按要求直接输出 JSON 结果，而输出大段中英混杂的逐步分析、thinking 不受控。用户对比 27B 模型认为"输出劣化"。请求参数 max_tokens=1024/2048/4096 多次测试均有。

- 用户@维护者追问是否为模型能力问题；维护者回复"大概率不是模型能力"，定位到 MoE 的 **MoEGatingTopkSoftmax 算子隐含精度问题**，上 PR 关联本 issue。
- PR #11391 改动 `vllm_ascend/_310p/fused_moe/experts_selector.py`：310P 该算子单次接收 >1024 token 时返回**无效路由结果**（注释：310P returns invalid routing results when this op receives more than 1024 tokens），修复 = 按 1024 切块多次调用再拼接（router_logits.split(1024)），新增 2050 token 回归 UT（切块 [1024,1024,2]）。

## 一句话根因

310P 上 `npu_moe_gating_top_k_softmax` 算子单次输入 >1024 token 时返回无效 topk 路由（疑似内部溢出/边界 bug），路由错乱使 MoE 输出劣化 → thinking 段失控/过度思考/不遵循输出指令；修复 = 在 `_310p/fused_moe/experts_selector.py` 按 1024 切块调用后拼接（PR #11391）。

## fix

- 升级到含 PR #11391 的版本：main 2026-07-04 合入（0dc58f8），**v0.23.0rc1（2026-07-19）起包含**（tag ancestry 已校验）。
- 触发区间：<0.23.0rc1（实测 env v0.21.0rc1）；仅 310P 路径受影响（_310p/fused_moe）。
