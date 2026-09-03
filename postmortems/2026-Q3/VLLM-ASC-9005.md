# VLLM-ASC-9005: 4×A2 拉起 DeepSeek-V4-Pro 显存余 20+G 却报 Memory resources are exhausted——HDK 过低误报

> 源是结构化 GitHub issue 线程（5 条评论），按 to-postmortem 优化——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/9005
**fix 跟踪**：无代码 PR；环境级修复 = 升级 HDK firmware + npu driver 至 25.5.0（CANN 8.5.1 不动）；weiguihua2 官方建议升级 driver 验证；报者实测通过，issue closed completed 2026-05-14
**时间**：2026-05-09（报）～ 2026-05-14（closed completed）
**框架**：vllm-ascend 0.18.0（按 DeepSeek-V4-Pro 部署文档）；CANN 8.5.1、firmware 7.0.1.3.220、npu driver 23.0.7
**平台**：A2-910B（A2 × 4，多节点）
**category**：interrupt
**investigation_quality**：medium（复现矩阵完整；remedy 两次现场验证；机制为用户层解释，无代码级定位）
**批量导入**：sed-g3（2026-09）
**pre-triage**：new_pattern（全库无 HDK 过低→OOM/显存误报 case；10944 的 QP 资源（EI0007/561000）机制/报错/修复全异）

## 结构化 case

`postmortems/inbox/VLLM-ASC-9005.case.yaml`（Tier 2 候选，待 groom 审）

## 现象摘要

4×A2 按 v0.18.0 文档拉起 DeepSeek-V4-Pro：每卡显存约 40G 时即报 `Memory resources are exhausted`，实际每卡还余 20+ G。调低 `--max-model-len`/`--max-num-seqs` 无效、加大共享内存无效。对照：单台 A2 跑 DSV4-Flash 正常、4 台跑 qwen3.5 正常——只有 4 台多节点大通信量模型的 DSV4-Pro 失败。升级 firmware + npu driver 至 25.5.0（CANN 8.5.1 不变）后正常启动。

## 一句话根因

HDK（firmware 7.0.1.3.220 / driver 23.0.7）版本过低时，多节点通信所需的 qp 等底层资源申请失败，上层以显存耗尽语义误报 `Memory resources are exhausted`；单机/低通信模型不触发。升级 HDK 至 25.5.0 解决（机制为用户层解释，未代码级定位）。

## fix

升级 HDK：firmware + npu driver → 25.5.0（需重启节点；CANN 8.5.1 不动），重新拉起验证。诊断要点：报显存耗尽但实际显存余量大、且多节点+大通信模型场景——先查 HDK 版本，勿按 OOM 方向调参。

## verification

**engineer-report**（两位工程师现场各自验证升级 25.5.0 解决；官方建议升级验证；无 fix PR）
