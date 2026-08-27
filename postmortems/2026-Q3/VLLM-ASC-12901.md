# VLLM-ASC-12901: A3 启动 GLM5.2 w4a8c8 报 KeyError（v0.22.1rc1-a3 镜像 modelslim 量化描述缺 indexer.wq_b.weight）

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/12901
**fix 跟踪**：无独立 PR；官方结论为版本差异，用户实测升级镜像 v0.23.0rc1-a3 后启动成功
**时间**：2026-07-27 ~ 2026-08-18（stale 关闭）
**框架**：vllm-ascend v0.22.1rc1-a3（失败）→ v0.23.0rc1-a3（成功）
**平台**：A3 (910C)，模型 GLM5.2 w4a8c8
**category**：interrupt
**investigation_quality**：medium
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（Phase B 批量 to-postmortem）

## 结构化 case

草稿：`postmortems/inbox/VLLM-ASC-12901.case.yaml`（Tier 2 入库前待 groom 分诊）。

## 一句话根因

v0.22.1rc1-a3 镜像中 `vllm_ascend/quantization/modelslim_config.py` 的量化权重描述表缺少 GLM5.2 w4a8c8 的 `indexer.wq_b.weight` 条目，模型加载时 `get_linear_quant_type` 按 prefix 查表抛 `KeyError: 'model.layers.3.self_attn.indexer.wq_b.weight'`，服务启动失败；升级 v0.23.0rc1-a3 镜像后该条目已补齐、启动成功。

## 弯路与级联

- 官方自动化响应要求补环境信息（版本/commit、首错栈），用户未回复，线程 stale 关闭——但结论其实在主帖末尾已自证（切镜像成功）。
- 级联注意：错误栈长且逐层（multiproc_executor → deepseek_v2 → modelslim_config），真正可 grep 的只有最后一层 `KeyError`，排障时直接抓 KeyError 行即可。
