# 原文见：https://github.com/vllm-project/vllm-ascend/issues/10521（真实诊断 trace：traces/2026-08-30-10521-el0008.yaml）
# 沉淀：诊断面板触发 to-postmortem（2026-08-31）；预分诊 novelty=covered（VLLM-ASC-12989）

# 摘要
- 现象：310P（300I Duo）Qwen3-30B-A3B w8a8 (TP2) / Deepseek-R1-70b w8a8 (TP8) 启动报
  Insufficient_Event_Resources(EL0008)，Create capture event failed, error=117571609, runtime result=207007
- 根因：310P 硬件 event 资源有限 + 多尺寸 cudagraph 捕获超上限（同 VLLM-ASC-12989，更大模型再确认）
- fix：--enforce-eager 或缩小 cudagraph_capture_sizes；长期等驱动更新
- 价值：以 30B/70B 更大模型验证 12989 根因不随模型规模变化——310P 捕获预算硬约束
- 诊断轨迹：triage(inference_interrupt) → index(32 候选) → quickly_check 逐字命中 → load_full → hit(0.3)
