# VLLM-ASC-7310: Qwen3.5-27B + MTP（qwen3_next_mtp 投机）在 v0.17.0rc1 A2 单机 8 卡拉起崩：aclnnCausalConv1d blockDim=0（EE1003/107000）——0.17.0rc1 适配期 bug，0.18.0rc1+ 修复

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest r2-sed-g1（2026-09）产出，进 inbox 待 groom 分诊；不改正式 knowledge/ 目录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/7310
**fix 跟踪**：无 issue 线程内钉死的 merged fix PR。证据：维护者 yiz-liu 把 #7310 列入 v0.17.1rc1 release checklist（#7467 "Bug need Solve"）；候选代码级修复 PR #7495 [Ops][Misc] Refactor and optimize CausalConv1d for Ascend（merged 2026-03-23，把 causal_conv1d_fn 路径重写为 npu_causal_conv1d_custom，时间与修复窗口吻合但 issue 未引用）；作者实测 v0.18.0rc1+ 镜像无此问题（2026-05-15 自行关闭 completed）
**时间**：2026-03-16（报）~ 2026-05-15（作者确认 0.18.0rc1+ 后关闭）
**框架/平台**：vllm-ascend v0.17.0rc1；A2 单机 8 卡（910B）；Qwen3.5-27B；--speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":3}' + cudagraph FULL_DECODE_ONLY
**category**：interrupt
**investigation_quality**：medium（多用户确认 + 版本对照定位到适配期 bug；代码级归因未在 issue 展开，fix PR 为时间吻合的候选）
**verification**：upstream-maintainer-confirmed（无直接关联 merged fix PR；维护者排期修复 + 作者跨版本实测确认 resolution）
**novelty**：new_pattern——库内 MTP/投机启动崩 case（12983 310P free-mask、13329 KeyError mtp head、14871 PD recompute、8336 balance scheduling）机制/签名均不同；无 qwen3.5×MTP×aclnnCausalConv1d 启动崩 case

## 现象摘要

A2 单机 8 卡 + v0.17.0rc1 起 Qwen3.5-27B，带 qwen3_next_mtp 投机（3 draft）与 FULL_DECODE_ONLY 图模式，TP8 拉起即崩（rank2）：

```
call aclnnCausalConv1d failed, detail: Invalid_Argument(EE1003): LaunchKernelV2 failed because
  value 0 for parameter blockDim is invalid.
rtsLaunchKernelWithHostArgs failed, runtime result = 107000.
```

多人同报（"same question" ×3，含 397B 等其他 Qwen3.5 部署经验）；DP2+TP4 配置可起但 TP8 必现。

## 一句话根因

Qwen3.5 + MTP 投机是新引入能力（0.17 适配期）：TP8 + FULL_DECODE_ONLY 图模式下 MTP 的 CausalConv1d 算子以 blockDim=0 发起 kernel launch（EE1003/107000）导致启动崩溃；官方在随后版本修复（0.18.0rc1+ 实测无此问题；候选代码级修复为 PR #7495 对 CausalConv1d 的算子路径重写）。

## fix

- 升级 vllm-ascend ≥ v0.18.0rc1（作者实测修复；0.17.0rc1 无此问题）。
- 0.17.0rc1 期规避（有限证据）：TP8 → 改 DP2+TP4 等较小 TP 组合可拉起（tutain2005）；或暂缓 Qwen3.5 MTP 投机。
- 判别：签名 aclnnCausalConv1d/EE1003 blockDim=0/107000 + qwen3.5 MTP + 图模式 → 版本适配问题，勿查模型权重/CANN。

## 弯路与级联

- TP 越大越易现（TP8 必现、DP2TP4 可跑）——与 MTP 图捕获/算子实例化范围随 TP 扩大有关。
- 作者 2026-05-14 问"解决了吗"当天 MaoJianwei 提示换最新镜像、作者 05-15 确认 0.18.0rc1+ 正常后自关。

## 建议 triage 路由症状

`aclnnCausalConv1d`/`blockDim is invalid`/`107000` 不在 inference_interrupt 现有正则（EngineCore 崩溃段无 python 层异常包装）；启动失败表述可被 `启动失败|failed to start` 兜底，精确签名可随 case 可选补 `aclnnCausalConv1d|blockDim is invalid|107000`（needs-review）。
