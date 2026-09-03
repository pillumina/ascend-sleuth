# VLLM-ASC-7635: Qwen3.5-397B-A17B-w8a8 开启 EP（DP2×TP8 A2 双机 16 卡）拉起崩：aclnnMoeDistributeDispatchV4 561002 "moeExpertNum is 32 ... must no more than 24"——单卡专家数超 MC2 上限仍选 MC2，PR #7364 后超限自动切 AllGather

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest r2-sed-g1（2026-09）产出，进 inbox 待 groom 分诊；不改正式 knowledge/ 目录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/7635
**fix 跟踪**：PR #7364 [BugFix] A2 MOE method && layerwise MTP bugfix && Mamba gdn_metadata bugfix（merged 2026-03-17 MengqingCao）：修复 A2 MoE 通信方式选择错误——单卡专家数超 MC2 上限（安全上限，版本相关 16/24）时仍选 MC2，改为自动切 AllGather（可能性能损失）；作者合入 PR 后拉起+压测正常，2026-04-02 关闭 completed
**时间**：2026-03-25（报）~ 2026-04-02（关）
**框架/平台**：vllm-ascend v0.17.0rc1；A2 双机 16 卡（DP2×TP8×EP）；Qwen3.5-397B-A17B-w8a8（512 专家）
**category**：interrupt
**investigation_quality**：medium（用户对照 + 维护者 PR 代码级定位；issue 线程有"关闭 EP 可起"的 workaround 验证，无逐层日志排查）
**verification**：upstream-fix-merged（fix PR #7364）
**novelty**：variant_of VLLM-ASC-10944——同"MoE/EP + aclnnMoeDistributeDispatchV4 启动失败族"（10944=910B GLM w8a8 EP → 561000 HCCL QP 资源耗尽、官方 #11394 未合入；本条=A2 Qwen3.5-397B → 561002 单卡专家数超 MC2 上限、PR #7364 已合入切 AllGather）；报错码/平台/根因/修复均不同，属同族不同形态

## 现象摘要

A2 双机 16 卡（DP2×TP8）、v0.17.0rc1 拉 Qwen3.5-397B-A17B-w8a8 并开 `--enable-expert-parallel`，profile_run（内存测算 dummy run）阶段 worker 崩：

```
RuntimeError: npu_moe_distribute_dispatch_v2: ... call aclnnMoeDistributeDispatchV4 failed, error code is 561002
... moeExpertNum is 32, in case of unlayered, it must no more than 24.
[MoeDistributeDispatchA2CheckAttrAndSetTiling][moe_distribute_dispatch_v2_tiling.cpp:1152]
```

去掉 `--enable-expert-parallel` 可正常拉起。

## 一句话根因

Qwen3.5-397B-A17B 共 512 个专家，A2 16 卡 EP 切分后单卡 32 个，超过 MC2（MoeDistributeDispatchV2）为内存安全设的单卡专家上限（该版本上限 24，不同版本 16/24）；0.17.0rc1 的 A2 MoE 通信方式选择在模型专家数 >256 时仍错误地选 MC2 → dispatch tiling 校验失败 561002 → 启动崩。PR #7364 修复选择逻辑：超限自动切 AllGather（有性能损失）。

## fix

- 升级 vllm-ascend 到含 PR #7364 的版本（main 2026-03-17；≥0.18.0rc1 起预计含，groom 回填首版）；超限场景自动切 AllGather，可正常拉起（作者压测通过，注意可能有性能损失）。
- 旧版本 workaround：去掉 `--enable-expert-parallel`（barcklist：235B 同问题、关 EP 即可）。
- 判别：`aclnnMoeDistributeDispatchV4 ... 561002` + `moeExpertNum is N ... must no more than 24` + EP + A2 → 通信方式选择/上限问题，勿查量化/权重。

## 弯路与级联

- 日志中 E29999 InitOpInfoLib（TransposeKvCacheByBlock 等）是级联噪声，别追；真签名是 tiling 校验 `moeExpertNum is 32 ... no more than 24`。
- yiz-liu 曾建议 #7235（C++ 侧），作者核对与问题无关；真正修复在 #7364。

## 建议 triage 路由症状

报错块含 python `RuntimeError`，inference_interrupt 的 RuntimeError 正则已能兜底路由；精确签名可随 case 可选补 `aclnnMoeDistributeDispatchV4 failed, error code is 561002|moeExpertNum is .* must no more than`（needs-review）。
