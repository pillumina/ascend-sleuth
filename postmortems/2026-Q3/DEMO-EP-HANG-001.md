# DEMO-EP-HANG-001: 大规模 EP all_to_all hang（演示用）

> **DEMO 演示用记录——本 PR 仅演示 intake→groom→门控流程，不合入 main，此文件不会进入正式知识库。**
> 症状场景为构造，镜像自 `examples/sample-case.yaml`（canonical 构造样例），不含任何真实客户数据。

**来源**：构造的调查笔记（演示"任意来源的知识经 to-postmortem 汇入"）
**框架**：mindspeed-llm 2.5.0 ｜ **平台**：A5-950 ｜ **category**：interrupt
**investigation_quality**：medium（构造演示，按理论 §4.1 应配中等强度 Beta 先验）

## 一句话根因

HCCL 内部通信缓冲区在大规模专家并行（world_size ≥ 64）下不足，all_to_all 算子等待超时，训练在 step 1000 后 hang。

## 结构化 case

已由 groom 升格（演示）至 `knowledge/training/mindspeed-llm/DEMO-EP-HANG-001.yaml`。
