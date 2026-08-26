# VLLM-ASC-12685: 非量化模型被自动路由进 AscendFp8Config，ds_linear scheme 硬编码致启动 AttributeError

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/12685
**fix 跟踪**：https://github.com/vllm-project/vllm-ascend/pull/12826（用户确认 "修改过后已成功拉起服务"）
**时间**：2026-07-23 ~ 2026-08-10
**框架/平台**：vllm-ascend 0.23.0rc1 + torch-npu 2.10.0.post2 + CANN 9.0.1；平台未写明芯片型号（aarch64 Kunpeng 920），模型 MiniMax-M2.7（BF16 非量化权重）
**category**：interrupt
**investigation_quality**：high
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（Phase B，第 2 批）

## 结构化 case

草稿：`postmortems/inbox/VLLM-ASC-12685.case.yaml`（Tier 2 入库前待 groom 分诊）。

## 一句话根因

模型目录 config.json 只要声明 `quantization_config.quant_method=="fp8"`（即使权重是 BF16）就会被自动路由进 `AscendFp8Config`，其 `get_quant_method`（fp8_config.py L115-120）对所有 LinearBase 无条件 `create_scheme_for_layer(...,"ds_linear",...)`；`AscendW8A8MXFP8DSDynamicLinearMethod.__init__`（methods/fp8.py L39-47）读取 DSV4 专有字段 `o_groups`/`o_lora_rank`，MiniMax-M2.7 的 `MiniMaxM2Config` 无此字段 → AttributeError，服务启动失败。

## 弯路与级联

- 弯路：用户先怀疑模型 config.json 误标 fp8 / 尝试 `--quantization None` 规避——这只是 workaround，根因是 ds_linear scheme 对非 DS 模型的误用（PR #12826 修复）。
- 级联：多 worker 同时 `WorkerProc failed to start` + `EngineCore waiting for worker exit` 是同一根因的并发表象；可 grep 锚点是最后一层 `AttributeError: 'MiniMaxM2Config' object has no attribute 'o_groups'`。
- 同根因家族：#14467（Qwen3.5 原生 FP8 同踩 `o_groups`），groom 可归 variant_of。
