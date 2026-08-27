# VLLM-ASC-14467: 原生 FP8 checkpoint 被路由进 AscendFp8Config（仅 DSV4 布局），Qwen3.5 启动 AttributeError

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/14467
**fix 跟踪**：https://github.com/vllm-project/vllm-ascend/pull/14852（作者 yiminghub2024 提交）
**时间**：2026-08-18 ~ 2026-08-26
**框架/平台**：vllm-ascend v0.23.0（quay.io/ascend/vllm-ascend:qwen3.8-a5 镜像）；A5 (Ascend 950PR) 单卡，模型 Qwen/Qwen3.8-27B-FP8 官方原生 FP8 checkpoint
**category**：interrupt
**investigation_quality**：high
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（Phase B，第 2 批）

## 结构化 case

草稿：`postmortems/inbox/VLLM-ASC-14467.case.yaml`（Tier 2 入库前待 groom 分诊）。

## 一句话根因

`detect_quantization_method`（utils.py:137-140）对任何 config.json 声明 `quant_method=="fp8"` 的 checkpoint 返回 FP8_METHOD 且其在 supported_quantization（platform.py:90-95）中，模型被路由进只实现 DeepSeek-V4 原生 FP8 布局的 `AscendFp8Config`——fp8_config.py:125 把每个 LinearBase 分派到 `ds_linear` scheme，构造器读 DS 专有 `o_groups`/`o_lora_rank`（methods/fp8.py:56-58）→ `Qwen3_5Config` 无此字段 → AttributeError；且 FP8 路径不 consult `ignored_layers`/`modules_to_not_convert`，BF16 保留层（visual.merger.linear_fc1）也被当量化层处理。

## 弯路与级联

- 同根因家族：#12685（MiniMax-M2.7 同踩 `o_groups`）——groom 可归 variant_of；本 case 是原生 FP8 checkpoint 场景。
- 第二问题面：崩溃层落在 BF16 merger 层——FP8 路径不 consult ignored_layers，与 #12685 的纯字段缺失不同，值得在 diagnosis 里单列。
- main 分支同一调用路径表现为裸 `raise NotImplementedError`（fp8_config.py:34-40），同样 opaque——不是独立问题。
