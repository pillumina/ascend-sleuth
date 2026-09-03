# VLLM-ASC-13446 —— 按 24.0rc 官方 Qwen3-Reranker deploy guide 启动 Qwen3-VL-Reranker-2B 启动报错（guide 架构覆盖与模型 config 类错配）

# 原文见：https://github.com/vllm-project/vllm-ascend/issues/13446

# fix 跟踪：https://github.com/vllm-project/vllm-ascend/pull/13510 （[Doc][BugFix] Fix Qwen3-Reranker deploy guide，merged；issue closed COMPLETED）

> 源为结构化 GitHub issue（首帖含完整启动配方 + 报错栈 + 用户实测可行的 0.18 配方），不重写全文。
> 完整 case 草稿（category/tags/compat/symptoms/quickly_check/diagnosis/root_cause/fix）见同目录 `VLLM-ASC-13446.case.yaml`。

## 根因摘要

doc bug——v0.24.0rc 官方 Qwen3-Reranker deploy guide 的启动配方写错（PR #13510 修 guide，未改引擎代码）：

`vllm serve Qwen3-VL-Reranker-2B --runner pooling --hf_overrides '{"architectures":
["Qwen3VLForSequenceClassification"], ...}'` —— 该架构覆盖与模型实际 config 类不匹配
（serve 目标模型 config.json：model_type=qwen3_vl，architectures=[Qwen3VLForConditionalGeneration]，
无该 ForSequenceClassification 类），vllm 走 qwen3_vl 多模态数据解析路径却拿到文本 Qwen3Config，
`qwen3_vl.py get_hf_config` 严格类型断言失败：

```
TypeError: Invalid type of HuggingFace config. Expected type: <...Qwen3VLConfig>, but found type: <...Qwen3Config>
```

→ serve 启动失败（日志尾 ERR99999 为级联兜底）。issue 内用户按 0.18 配方把架构覆盖改为
`Qwen3ForSequenceClassification` 后启动正常，印证 guide 架构名错配是触发点。

## fix

**改启动配方（config-change，无需升级镜像）**：`--hf_overrides` 的 architectures 覆盖改
`Qwen3ForSequenceClassification`（0.18 配方，用户实测可行；保留其余覆盖字段），重启 serve；
或按 PR #13510 修正后的官方 guide 配置。日志尾 ERR99999 UNKNOWN application exception 是启动
异常级联兜底（同 VLLM-ASC-7823 归类），非独立错误。

## novelty（S2 replay 覆盖缺口补 case）

new_pattern——全库无 reranker / hf_overrides / Qwen3VLForSequenceClassification / 本 TypeError
签名 case；最近邻（9593+1991 310P pooling 平台缺口 NotImplementedError→升级、5725 pooling 精度、
7023 多模态 placeholder 计数）平台/签名/根因层/fix_type 全异。
