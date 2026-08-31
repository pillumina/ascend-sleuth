# 原文见：https://github.com/vllm-project/vllm-ascend/issues/15086（真实诊断 trace：traces/2026-08-30-15086-kimik3.yaml）
# 沉淀：诊断面板触发 to-postmortem（2026-08-31）；预分诊 novelty=new_pattern

# 摘要
- 现象：vllm-ascend 23.0 正式版 A3 560T 部署 KIMI-K3 W4A8 报
  Model architectures ['KimiK3ForConditionalGeneration'] are not supported for now；
  社区文档写 23.0 支持 kimi k3
- 根因：版本错位——K3 架构支持在 0.23.0 之后才合入 vllm registry（v0.23.0 只有 KimiK25，
  main 已加 vllm.models.kimi_k3）
- fix：升级 vllm-ascend 到含 K3 支持的版本
- 价值：新诊断模式——"模型架构 not supported"先查上游 registry 版本差异（源码分析路径），
  勿当架构缺失；社区文档表述与发布版本存在时差
- 诊断轨迹：triage(inference_interrupt) → index(无命中) → source_analysis(registry diff v0.23.0 vs main)
  → hit(新形态，0 置信)
