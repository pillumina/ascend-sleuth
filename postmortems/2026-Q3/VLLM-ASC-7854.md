# VLLM-ASC-7854: Qwen3.5-397B-w8a8 TP4DP4EP 混部+MTP+FULL_DECODE_ONLY 高并发多模态压测乱码/精度掉点（OCRbench 87.9 vs 95.6）

> 源是结构化 GitHub issue 线程（7 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/7854
**fix 跟踪**：PR #8560（merged 2026-04-28，"[Feature] Add xmask feature for dispatch_ffn_combine operator (only for w8a8 branch)"）——维护者 shaopeng-666 / leo-pony 确认该 PR 解决本 issue
**时间**：2026-03-31 ~ 2026-05-28（completed）
**框架**：vllm-ascend 0.17.0rc2.dev143+g f83cb0e6d（vllm-ascend commit f83cb0e6d）+ vLLM 0.18.0（commit bcf2be9）；修复在 main（PR #8560 测试基于 vLLM 0.19.0）
**平台**：Ascend 910B（A2-910B，64GB×N，混部 2 节点/8 卡×2）
**category**：precision（静默乱码/精度掉点，无异常栈）
**investigation_quality**：medium（对照 TP16DP1 正常 + 精度量化 + 维护者指认 fix PR；根因由 PR #8560 自述 xmask 机制）
**verification**：upstream-fix-merged（fix PR #8560）
**pre-triage**：variant_of VLLM-ASC-9186（同算子 dispatch_ffn_combine 的 w8a8 fused-MoE/EP 路径缺陷；增量=运行期 xmask 精度乱码 vs 9186 启动期 pybind bias1 类型崩溃，修复 PR 不同：8560 vs 11701）

## 现象摘要

- 启动：Qwen3.5-397B-A17B-w8a8-mtp，TP4×DP4 + `--enable-expert-parallel` + `--speculative-config qwen3_5_mtp` + `--compilation-config FULL_DECODE_ONLY` + `--quantization ascend` + async-scheduling + `VLLM_ASCEND_ENABLE_FUSED_MC2=1`。
- 高并发（1024 并发）跑多模态 OCRbench 精度测试出现乱码回复：精度 87.9 / 95.6（掉约 8 点）。
- 对照组：只改部署策略为 TP16DP1（无 EP/MTP 混部），精度正常、无乱回复。
- 0410 nightly-releases-v0.18.0-a3 镜像仍复现；报者曾怀疑与 KV 空间不足有关（未证实），最终归因 PR #8560。

## 一句话根因

w8a8 fused-MoE 的昇腾自定义算子 `dispatch_ffn_combine` 未实现 xmask（xactivemask）处理：EP 混部 + MTP/FULL_DECODE_ONLY 高并发下，被 xactivemask=0 屏蔽的 token（不参与路由的 padding token）没有像正常路径那样被置为 padding expert 并跳过分发，仍按真实 expert 分发/计算，部分 rank 拿到错误结果 → 推理输出乱码、精度掉点。PR #8560 给 dispatch_ffn_combine（仅 w8a8 分支）加 xactivemask 控制逻辑修复。

## fix

升级到含 PR #8560 的 vllm-ascend（merged 2026-04-28；main）。机制：xactivemask=0 时该 token 的 expertIdx 置为 expertNum（= tokenPerExpert × EP），token 放序列尾，各设备只处理前 tokenPerExpert×EP 个 expert、不处理 padding expert。无配置 workaround——静默精度问题只能升级验证（对照组 TP16DP1 仅用于确认是混部路径问题，不是可交付规避）。

## 弯路与级联

- issue 线程无弯路；乱码为静默输出错误（无引擎异常栈），判型靠"混部+EP+MTP 高并发 + 精度测试掉点"而非报错文本。
- 级联：无（服务不崩，仅输出内容错）。
