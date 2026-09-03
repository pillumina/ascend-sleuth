# VLLM-ASC-10097 —— model_runner_v1 preprocess_mamba 重复传参致 TypeError（v0.20.2 回归）

# 原文见：https://github.com/vllm-project/vllm-ascend/issues/10097

# fix 跟踪：https://github.com/vllm-project/vllm-ascend/pull/10188

> 源为结构化 GitHub issue（首帖即含调用代码，bug 本体可静态读出），不重写全文。
> 完整 case 草稿（symptoms/quickly_check/diagnosis/root_cause/fix）见同目录 `VLLM-ASC-10097.case.yaml`。

## 根因摘要

v0.20.2 回归（Mamba align 模式）：`model_runner_v1.py` 中 `mamba_cache_mode == "align"` 分支，
`vllm_version_is("0.20.2")` 下把 `preprocess_bufs` 直接置为 `self._get_mamba_copy_bufs()`
（该版本 copy_bufs 即 preprocess 用缓冲），但调用 `mamba_utils.preprocess_mamba` 时仍把
`self._get_mamba_copy_bufs(),` 作为独立位置实参再传一次，与 `preprocess_bufs` 重复 →
实参数超过函数签名 → `TypeError`（对齐预处理的 Mamba 推理路径崩溃）。issue 原文已指明：
"the last 2 args ... is duplicated, `self._get_mamba_copy_bufs(),` should be removed"。

修复 = PR #10188 移除该重复实参（merged；issue closed COMPLETED）。落地动作 = 升级到含
PR #10188 的版本（或在旧代码上手工删除该多余实参）。
