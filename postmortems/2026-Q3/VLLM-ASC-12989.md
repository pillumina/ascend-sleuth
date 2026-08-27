# VLLM-ASC-12989: 310P event 资源上限，FULL_DECODE_ONLY 多尺寸 cudagraph 捕获失败

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/12989
**fix 跟踪**：无 PR；官方确认 "这个问题需要依赖未来驱动版本的发布"；workaround = `--enforce-eager` 或减少捕获数量
**时间**：2026-07-28 ~ 2026-08-03
**框架/平台**：vllm-ascend v0.23.0rc1-310p 镜像 + torch-npu 2.10.0.post2 + CANN 9.1.0-beta.1；310P（Atlas 300I DUO，310P3），Qwen3-14B-W8A8SC TP2
**category**：interrupt
**investigation_quality**：medium
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（Phase B，第 2 批）

## 结构化 case

草稿：`postmortems/inbox/VLLM-ASC-12989.case.yaml`（Tier 2 入库前待 groom 分诊）。

## 一句话根因

310P 硬件/驱动的 event 资源有限，`FULL_DECODE_ONLY` 下按 `cudagraph_capture_sizes [1,2,4,8,16]` 多尺寸捕获 CUDA graph 时 event 资源耗尽：`Create capture event failed`（error=117571609 / runtime result 207007）→ `Insufficient_Event_Resources(EL0008)` → `capture_end` 507903 → EngineCore 崩溃；TP1 或 `--enforce-eager` 正常。

## 弯路与级联

- 弯路：用户先用 `--enforce-eager` 规避后追问 "是什么问题"——maintainer 指出硬件资源限制导致图捕获数量有限，非配置/模型问题。
- 误导性栈：报错栈浮现在 `all_reduce`（patch_distributed.py）与 `NPUModelRunner failed` 包装处——异步算子报错的浮出点，不是根因位置。
- 关联：#13007（同 310P `Insufficient_Event_Resources(EL0008)`，maintainer 建议少捕获图）——同根因变体，groom 可归 variant_of。
