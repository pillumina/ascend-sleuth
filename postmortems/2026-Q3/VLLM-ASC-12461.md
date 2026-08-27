# VLLM-ASC-12461: 多节点 EP + FusedMoE MC2 算子在 ROCE 网络 aicore exception → SUSPECT REMOTE ERROR

> 源是结构化 GitHub issue 线程（11 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/12461
**fix 跟踪**：无代码修复——用户自证：常规 ROCE 网络对 MC2 算子支持异常，HCCS 网络可跑通（评论#9）；官方未出修复
**时间**：2026-07-21 ~ 2026-08-03
**框架**：vllm-ascend 0.21.0（glm5.2-a3 镜像）+ GLM-5.2-w8a8，TP16/DP2/EP 多节点 + MTP(num_speculative_tokens=4) + MLAPO
**平台**：A3-910C（2 × A3）
**category**：interrupt
**investigation_quality**：high（消融排除 speculative 路径 + plog aicore 定位 MTE DDR 越界 + fault kernel 名 + 单/多节点对照 + 环境自解闭环）
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md

## 结构化 case

`postmortems/inbox/VLLM-ASC-12461.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

多节点（跨服务器）EP 下，vllm_ascend FusedMoE 的 MC2 通信算子（`MoeDistributeDispatchV2`，Ascend 特有 MoECommType.MC2）在常规 ROCE 网络触发 aicore exception（MTE 指令 DDR 地址越界，errCode 0x800000）→ NPU 侧上抛 `SUSPECT REMOTE ERROR, error code is 507057`，多节点 EP 启动/编译失败。属网络环境对 MC2 算子的支持问题，非 vllm-ascend 代码 bug：HCCS 网络可正常跑通。

## 弯路与级联

- **弯路（先排除后确认）**：先怀疑 MTP/dummy_run 路径（栈指向 `llm_base_proposer.py:dummy_run`）——关闭 speculative decode 后同栈报错，排除；再怀疑图编译（graph compile is ok, enforce-eager 也报错）——排除；单节点 TP16+PP2 可跑、多节点 EP 在 MLAPO 与 GEMM 路径均失败 → 收敛到跨节点 FusedMoE MC2 通信；最终定位网络环境（ROCE vs HCCS）。
- **误导性报错**：plog 中的 `QuantBatchMatmulV3 launch failed (361001)`、`aclrtLaunchKernelWithHostArgs failed 507015`、`Kernel task happen error retCode=0x26` 都是 MC2 通信失败后的**次级报错**，diagnosis 中已列为忽略项，勿追其调用链。
