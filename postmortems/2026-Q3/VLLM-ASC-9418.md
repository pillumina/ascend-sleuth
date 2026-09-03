# VLLM-ASC-9418: A3 双机混部拉起 DeepSeek-V4-Pro 失败（aclnnHcPreInvRms failed）——未用灵衢背板、跨机需显式走 ROCE 配置

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest r2-sed-g4（2026-09）产出，进 inbox 待 groom 分诊；不改正式 knowledge/ 目录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/9418
**fix 跟踪**：无上游 fix PR——组网/部署配置层问题；维护者 Bowen-Leee（2026-06-04）关闭 issue 并给出原因+配方；用户未复验
**时间**：2026-05-21 ~ 2026-06-04
**框架/平台**：A3 双机（HDK 25.5.2/25.5.1，openEuler 22.03-sp4 / kylin-v10-sp3；issue body 中"A2 双机"为笔误——title/env 均为 A3）；vLLM 0.18.0 + vllm-ascend；DeepSeek-V4-Pro-w4a8，TP16 + DP2（跨机）+ EP + `--quantization ascend`
**category**：interrupt
**investigation_quality**：medium（维护者一句话根因 + 明确配方；机制细节在内网 wiki，未复验）
**verification**：upstream-maintainer-confirmed（无 fix PR）
**novelty**：new_pattern——库内无 A3 跨机/混部启动失败的组网配置 case；判别参照 VLLM-ASC-12461（ROCE 正常组网下 MC2 算子的兼容 bug，机制不同）

## 现象摘要

A3 双机混部（TP16 跨 2 节点 + DP2 + EP）用推荐配置拉起 DeepSeek-V4-Pro-w4a8 失败，报 `call aclnnHcPreInvRms failed`。启动脚本为机内/超节点优化配置（`export HCCL_OP_EXPANSION_MODE="AIV"`、`export HCCL_BUFFSIZE=2048`），主/从节点同一套，均拉不起。（详细报错为截图，见源文档。）

## 一句话根因

用户没接灵衢背板，却仍按**机内 AIV/HCCS 优化配置**跑跨机通信 → 拉起 MoE 模型时通信/算子层失败（aclnnHcPreInvRms failed）。跨机（无背板）场景必须**显式改走 ROCE**。

## fix（维护者配方，Bowen-Leee 2026-06-04）

```bash
export HCCL_BUFFSIZE=200
export HCCL_INTER_HCCS_DISABLE=TRUE    # 超节点内节点间走 ROCE 而非 HCCS
# 删除 HCCL_OP_EXPANSION_MODE="AIV"
```

- 另在 vllm_ascend 的 `ascend_forward_context.py` 配置 `moe_comm_type = MoECommType.ALLGATHER`（规避方法见内网 wiki [REDACTED]）。
- 若确有灵衢背板/HCCS 超节点组网，保持原 AIV 推荐配置即可——**配方面向无背板跨机场景**。

## 判别

- 与 VLLM-ASC-12461 区分：12461 = ROCE 正常组网下 FusedMoE MC2（MoeDistributeDispatchV2）aicore exception 507057（升级 0.20.2rc1+ 修复）；本条 = 没走 ROCE/背板导致的拉起失败（配置层）。先判组网，再看故障面。

## 建议 triage 路由症状

`拉起失败` 属中文"启动失败"类，inference_interrupt 现有中文正则只有 `启动失败`，建议补 `拉起失败`；`aclnnHcPreInvRms` 此类跨机 MoE 算子失败可随 `aclnn\w+` 补录（可选，needs-review）。
