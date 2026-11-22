# 原文见：https://github.com/vllm-project/vllm-ascend/issues/13976

## 结论摘要

- 现象：DSpark 投机解码（`method=dspark`，num_spec=7）首个 chat 请求即崩，`AttributeError: 'DSparkDeepseekV4ForCausalLM' object has no attribute 'get_draft_attn_causal'`。
- 根因：`vllm_ascend/spec_decode/dspark_proposer.py:437` 无条件调用可选模型 API `get_draft_attn_causal()`，legacy 非因果模型未实现。
- 修复：升级 vllm-ascend ≥ v0.26.0rc1（#13935 / #13831），缺失时回落 `cad.causal = False`。

诊断过程与证据见 `traces/2026-11-04-13976-dspark-causal-api.yaml` 与同名 `.report.md`。
