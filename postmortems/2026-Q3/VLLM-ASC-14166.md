# VLLM-ASC-14166: A5 950DT 启动 DSV4-Flash-0731 报 MoeInitRoutingV3 找不到二进制（torch-npu 需 >=2.10.0.post4）

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/14166
**fix 跟踪**：无 PR；用户实测安装 torch-npu 2.10.0.post4 后不再报错（官方确认修复版本）
**时间**：2026-08-13 ~ 2026-08-15
**框架**：vllm-ascend 0.25.1 + torch-npu 2.10.0.post2（失败）→ 2.10.0.post4（成功）
**平台**：A5-950（950DT，npu-smi 25.1.rc1），模型 DeepSeek-V4-Flash-0731
**category**：interrupt
**investigation_quality**：low
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（Phase B 批量 to-postmortem）

## 结构化 case

草稿：`postmortems/inbox/VLLM-ASC-14166.case.yaml`（Tier 2 入库前待 groom 分诊）。

## 一句话根因

torch-npu 2.10.0.post2（及更早）的 op-plugin 未内置 MoeInitRoutingV3 算子二进制，A5 上启动 DSV4-Flash-0731 走 MoE 路由时 kernel 找不到二进制（`Cannot find binary for op MoeInitRoutingV3, errno:561000`），profile_run 阶段崩溃；torch-npu 2.10.0.post4 起补齐该算子，升级即修复。

## 弯路与级联

- 官方先要求补启动命令与 PLOG，用户直接以"升级 post4 后不再报错"闭环，未走补材流程。
- 级联注意：报错尾部还出现 `npu_grouped_matmul ... error code is 161002` 的次级错误，属于 MoeInitRoutingV3 之后的连锁失败，不要当作独立根因排查。
