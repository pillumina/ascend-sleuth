# 原文见：https://github.com/vllm-project/vllm-ascend/issues/13688（真实诊断 trace：traces/2026-08-30-13688-aiv-ric.yaml）
# 沉淀：诊断面板触发 to-postmortem（2026-08-31）；预分诊 novelty=new_pattern

# 摘要
- 现象：AIV 模式 graph capture 失败（rtEventRecord task not supported 507009 → capture_end 507903），
  vllm serve GLM-4.6V TP8+EP8 首请求挂死在 Replaying aclgraph（AIVector 8-16% / AICore 0%），
  5min 后 EngineCore shm_broadcast timeout
- 根因：AIV + RIC graph_task_group 组合冲突——最小复现矩阵唯一失败组合是 task_group 包
  allreduce + AIV（baseline✅/tg_no_hccl✅/tg_allreduce❌/allreduce_tg✅）
- fix：禁用 AIV 或回退 RIC（二者互斥使用）
- 价值：新形态（知识库无）；证明 507903 签名 ≠ 资源不足（reference 只解释签名，根因需独立判断）——
  诊断时勿把 12989/9596 资源不足 fix 套用到组合冲突
- 诊断轨迹：triage(inference_interrupt) → index(507903→12989/9596 形态不符) → reference_lookup(507903 甄别)
  → miss(新形态) → 建议沉淀
