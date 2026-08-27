# VLLM-ASC-12983: 310P MTP 与图模式无法同时开启（镜像缺 free-mask 算子，依赖后续 CANN/torch-npu）

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/12983
**fix 跟踪**：无 PR；官方确认修复依赖后续发布的 CANN/torch-npu（当前镜像缺 free-mask 算子）
**时间**：2026-07-28 ~ 2026-08-03
**框架**：vllm-ascend v0.23.0rc1-310p-openeuler，模型 Qwen3.6-27B
**平台**：310P
**category**：other
**investigation_quality**：medium
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（Phase B 批量 to-postmortem）

## 结构化 case

草稿：`postmortems/inbox/VLLM-ASC-12983.case.yaml`（Tier 2 入库前待 groom 分诊）。

## 一句话根因

310P 的 v0.23.0rc1-310p-openeuler 镜像缺 free-mask 算子：MTP 所需的 pageattention-splitfuse 要传入变化 shape 的 mask，图模式不允许 → 图捕获阶段同步被禁流上（`aclrtMemcpy, error code is 107030` / "Not allow to synchronize captured-stream"）启动失败；MTP 与图模式同开需依赖后续发布的 CANN 和 torch-npu。

## 弯路与级联

- 用户先试"去 MTP 参数可启动但只有 ~20 token/s"，官方补一句建议用 W8A8 量化权重提速——属性能建议，与图模式/MTP 互斥是两件事。
- 级联注意：报错链 `107030 → 107027 → 107030` 都是"captured stream 上不允许同步"的同源连锁，抓第一行 `aclrtMemcpy, error code is 107030` 即可。
