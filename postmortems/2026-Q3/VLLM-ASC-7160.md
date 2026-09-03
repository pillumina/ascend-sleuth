# VLLM-ASC-7160: Qwen3.5-35B-A3B（MoE）vllm serve 拉起即崩——aclnnMoeGatingTopK 只支持 renorm=0，Qwen3.5 路由需 renorm=1 → EZ9999

> 源是结构化 GitHub issue 线程 + 修复 PR（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest sed-g2 批次 1 产出（人工筛出的高质量 closed issues），进 inbox 待 groom 分诊。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/7160
**fix 跟踪**：PR #7573（[A5][bugfix] Fix fused MoE A5 MXFP8 scale normalization, load-balance routing and gating_topk ops，merged 2026-03-25）；issue 2026-07-09 closed
**框架/平台**：vllm-ascend 0.17.0.0rc1 / 0.18.0rc1（及 qwen3_5-v0-a2 0day 镜像）；线程含 A2-910B（verl Dockerfile a2）复现，fix 在 A5/950 adaptor 分支合入
**category**：interrupt
**investigation_quality**：medium（多环境/多版本复现一致 + 用户按 fix PR 源码验证闭环；无维护者在 issue 线程内逐字定论，机制取自 op 报错文本 + PR diff）
**verification**：upstream-fix-merged（fix PR #7573 已合入；用户 snowsea-zero 按该 PR 改源码验证解决）
**novelty**：new_pattern——库内（_index 全量比对）无 gating_topk/renorm/EZ9999 tiling 拒绝签名；最近似 10122（QuantBatchMatMulV3 507015）/ 10610（modelslim KeyError）均不同算子/机制

## 现象摘要

`vllm serve /root/models/Qwen3.5-35B-A3B`（TP2 + `enable_cpu_binding`/`multistream_overlap_shared_expert`）在 EngineCore 启动 profile_run 阶段 worker 抛：

```
RuntimeError: call aclnnMoeGatingTopK failed, detail:EZ9999: Inner Error!
EZ9999[...]: renorm is: 1, but currently only support 0.[FUNC:CheckAttr][FILE:moe_gating_top_k_tiling.cpp][LINE:210]
MoeGatingTopK do tiling failed, ret is -1.
EngineCore failed to start ... Worker failed with error ...
```

- 调用链：`AscendFusedMoE.apply → select_experts → _select_experts_with_fusion_ops（experts_selector.py:220）→ torch.ops._C_ascend.moe_gating_top_k`（vllm-ascend 封装 aclnnMoeGatingTopK）。
- 0.17.0.0rc1 / 0.18.0rc1（torch-npu 2.9.0 / CANN 8.5.0）均复现；verl 训练内嵌 vllm 推理（qwen3-30B-A3B，A2）同报。
- 用户把 experts_selector.py 的 `renorm = int(renormalize)` 强改 `int(0)` 后能绕过启动；但 renorm=0 跳过了 renorm 语义所要求的权重归一化——线程内观察不一：原版模型可跑通、snowsea-zero 与 SFT 模型则出现重复回显 prompt/`<think>` 循环劣化。**renorm=0 静默改变路由语义，不是可交付 fix**（见下）。

## 一句话根因

Qwen3.5-A3B 系 MoE 路由要求对 top-k 权重 renormalize（renorm=1），vllm-ascend fused-MoE 的 `_select_experts_with_fusion_ops` 把该标志原样传给自定义 op `_C_ascend.moe_gating_top_k`（wrap CANN `aclnnMoeGatingTopK`），而该 CANN op 的 tiling CheckAttr（moe_gating_top_k_tiling.cpp:210）**只支持 renorm=0** → `EZ9999: Inner Error`，EngineCore profile_run 启动即崩。

## fix

PR #7573（merged 2026-03-25）：`experts_selector.py` 改经 `DeviceOperator.moe_gating_top_k` 分派；**Ascend950/A5 adaptor 改走 `torch_npu.npu_moe_gating_top_k`**（CANN op 支持 renorm 语义），`renorm=0` 传入 + `norm_type==0 && renorm==1` 时手动 `topk_weights = topk_weights / topk_weights.sum(dim=-1, keepdim=True)` 补回归一化（device_op.py）。issue 线程 snowsea-zero 按该 PR 修改 0.18.0rc1 源码验证解决。

- 修复版本：含 #7573 的 main（2026-03-25 后）；非 A5 芯片如仍走 `_C_ascend` 路径，需确认 CANN 版本是否放开 renorm=1，或按 #7573 思路本地改走 torch_npu op。
- 不可取 workaround：硬编码 renorm=0 绕过 tiling 检查会破坏路由权重归一化 → 重复输出（误导性修复，勿作为 case fix 记录）。

## 建议 triage 路由症状

现有 inference_interrupt 含 `RuntimeError`/`启动失败` 类可兜底命中，但签名正则 `aclnn\w+|AclNN_|EZ\d+` 目前只在 training 分支——若 triage 未命中，建议 inference_interrupt 增补 `aclnnMoeGatingTopK|renorm is: 1|MoeGatingTopK do tiling failed`（随 case PR 提交，needs-review 由 groom 定夺）。
