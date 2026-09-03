# VLLM-ASC-9593: 310P 启动 pooling 模型报 NotImplementedError（runner_type='pooling'）——310P 功能缺口，PR #8846 补支持

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest r2-sed-g4（2026-09）产出，进 inbox 待 groom 分诊；不改正式 knowledge/ 目录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/9593
**fix 跟踪**：PR #8846 "[Feature] Support pooling models on 310P platform"（base main，merged 2026-05-27，merge e029f683da；作者标 vLLM v0.20.2；实现 310P 非因果 attention mask + flash attention forward + classification/embedding/scoring E2E）；维护者 Tflowers-0129 2026-06-04 确认"目前主线已支持pooling模型"
**时间**：2026-05-26 ~ 2026-06-04
**框架/平台**：vllm-ascend 0.18.0rc0+htrunk1.gts.gtsllm.310p.r4（310P3 / 300I Duo）；`vllm serve bge-m3 --runner pooling --dtype float16 --enforce-eager`
**category**：interrupt
**investigation_quality**：high（清晰 NotImplementedError 签名 + 明确 fix PR + 维护者确认 + E2E 测试；reporter 未复验升级）
**verification**：upstream-fix-merged（PR #8846）
**novelty**：new_pattern——库内无 310P pooling/embedding runner case

## 现象摘要

310P（310P3）上 `vllm serve bge-m3 --runner pooling --dtype float16 --enforce-eager`，模型加载阶段直接报：

```
File ".../vllm_ascend/_310p/attention/attention_mask.py", line 135, in get_attention_mask
    raise NotImplementedError("310P does not support runner_type='pooling'")
```

服务无法启动。

## 一句话根因

310P 分支（`_310p/`）早期只实现因果（generate/decode）attention 路径，`get_attention_mask` 对 pooling（embedding/classification/scoring，非因果）直接抛 NotImplementedError——**310P 版本线功能缺口，不是用法错误**。PR #8846（merged 2026-05-27）为 310P 补 pooling 支持（非因果 attention mask + flash attention forward + E2E）。

## fix

- **升级 vllm-ascend 到含 PR #8846 的版本**（作者标 vLLM v0.20.2 代；310P 镜像版本线与 main 不完全同步，确认镜像含该 commit）。
- 升级后 310P 可正常跑 `--runner pooling`（bge-m3 等 embedding / classification / scoring 模型）。
- 对照：910B 等非 310P 平台同命令本就正常——平台差异是判别证据。

## 建议 triage 路由症状

`NotImplementedError` 未在 inference_interrupt 异常类正则中（当前列 KeyError/AttributeError/RuntimeError/AssertionError/ValueError 等）；建议补 `NotImplementedError`（可选，needs-review）。
