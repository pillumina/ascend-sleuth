# VLLM-ASC-7023: Qwen3.5 多模态高并发打流 Worker 崩溃 —— patch_multimodal_merge placeholder/embedding 计数不匹配（ValueError）

> 源是结构化 GitHub issue 线程 + 未合入 fix PR，按 to-postmortem 优化②——只写指针，不重写。
> 批量导入：sed-g3（2026-09）——case 草稿见同目录 VLLM-ASC-7023.case.yaml。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/7023
**fix PR**：https://github.com/vllm-project/vllm-ascend/pull/7055（closed，**merged=false 未合入**）
**时间**：2026-03-05 报告；2026-03-12 维护者最后回复；2026-07-23 issue 以 completed 关闭（线程无验收确认）
**框架版本**：vllm main commit `15d76f74e2fdb12a95ea00f0ca283acf6219a2b7`；vllm-ascend main commit `3cc8bf15da7c182f05fdadb3d2cb071812d7ac67` + PR #7021（2026-03，无 release 版本号）；vLLM V1 executor
**平台**：未指明 NPU 型号（collect_env 输出为空占位；启动为 tp4 + dp4 + expert-parallel 多卡 + EP）
**category**：interrupt
**investigation_quality**：medium（复现完整 + 栈到 patch 代码点 + PR 作者机制分析；但 PR 未合入、无维护者验收）
**verification**：investigation（fix PR #7055 未合入；维护者 shaopeng-666 仅指向 PR #7055 待验证，无已合修复 PR、无明确 resolution 确认——宁低勿高）

## 现象（用户首帖）

Qwen3.5-397B-A17B-w8a8-mtp + V1 + 多模态图片数据集高并发（1024 并发）打流，Worker 崩溃：

```
ValueError: Attempted to assign 65 = 65 multimodal tokens to 3905 placeholders
```

栈：`vllm/v1/executor/multiproc_executor.py worker_busy_loop` → `execute_model` →
`vllm/model_executor/models/qwen3_5.py:690 embed_input_ids` →
`vllm_ascend/patch/worker/patch_multimodal_merge.py:48 _merge_multimodal_embeddings`（raise ValueError）。
同段日志该 Worker 先报 `ERR01001 OPS invalid parameter`（级联/伴随，判型以 ValueError 文本为准）。

## 一句话根因

vllm-ascend 以 `patch/worker/patch_multimodal_merge.py` 覆写 vLLM 的 `_merge_multimodal_embeddings`
合并 Qwen3.5/Qwen3-VL 多模态 embedding 到 prompt 视觉 placeholder 位置；多模态请求下出现 placeholder 计数
（3905）≫ 实际 embedding token 数（65）的错位，patch 在 `patch_multimodal_merge.py:48` 计数校验不通过直接
raise ValueError，worker execute_model 崩溃（PR #7055 作者：mm embedding token 数可少于 placeholder 数 →
计数不匹配 / index 越界）。

## fix

上游**无已合修复**。PR #7055（closed, merged=false）给出的方向：
① `patch_multimodal_merge.py` 加 pre-check——embedding token 数与 placeholder 数不匹配时告警而非崩溃；
② 新增 `patch_qwen3_vl.py` tokenizer 级修正 Qwen3-VL `_get_merged_lt_splits()` / `_find_mm_placeholders()`
placeholder 检测；③ 注册 patch + 单测。线程无 workaround；当前只能手动应用 PR #7055 diff 或等上游重新合入后升级。

## 弯路与级联

- 同 Worker 先报 `ERR01001 OPS invalid parameter` 再报本 ValueError——若同请求，ERR01001 是 merge 错位路径
  上的伴随算子报错，勿单独按 CANN 算子 bug 排查；仅出现 ERR01001 而无本 ValueError 文本时属另一类问题。
- issue 以 completed 关闭但线程无用户/维护者验收确认（labels 含 wait-feedback）；PR 未合入 → 不视为已解决。

## 建议 quickly_check 信号

`Attempted to assign [0-9]+ = [0-9]+ multimodal tokens to [0-9]+ placeholders` /
`patch_multimodal_merge` / `_merge_multimodal_embeddings`
