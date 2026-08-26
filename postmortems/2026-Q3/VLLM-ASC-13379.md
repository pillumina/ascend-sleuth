# VLLM-ASC-13379: 0.22.rc1 部署 DSV4-Flash-0731 报 KeyError 'mtp.0.head.weight'（DSpark 模型无 MTP，dspark 需 >=0.25.1rc）

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/13379
**fix 跟踪**：无 PR；官方回复指向 DSpark 部署文档（releases/v0.25.1rc 分支 DeepSeek-V4-Flash-DSpark.md）
**时间**：2026-08-03 ~ 2026-08-15
**框架**：vllm-ascend 0.22.rc1（失败）
**平台**：未注明（模型 DeepSeek-V4-Flash-0731-w8a8）
**category**：other
**investigation_quality**：low
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（Phase B 批量 to-postmortem）

## 结构化 case

草稿：`postmortems/inbox/VLLM-ASC-13379.case.yaml`（Tier 2 入库前待 groom 分诊）。

## 一句话根因

与 #13329 同根因：DeepSeek-V4-Flash-0731 是 DSpark 模型、不含 MTP head，0.22.rc1 用 mtp speculative method 启动即 `KeyError: 'mtp.0.head.weight'`；且 dspark 支持仅自 vllm-ascend 0.25.1rc 起，0.22.rc1 无 dspark 可用——比 #13329 多一层版本下限约束。

## 弯路与级联

- 前期评论先问"权重是否从 modelscope 指定链接下载"、要求补环境信息与完整报错，随后官方直接给出 DSpark 结论，未走补材流程。
- 与 #13329 措辞差异（中文"使用mtp模式启动报错" vs 英文 "Is there an issue with the downloaded model weights?"）是后续交叉回放的考题，两条 symptoms 各自忠实本线程。
