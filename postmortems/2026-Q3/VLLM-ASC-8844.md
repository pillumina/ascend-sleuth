# VLLM-ASC-8844: GLM 5/5.1 四节点 PD 分离（TP16 DP2）GPQA 精度不达标——显存跑满后的重计算路径精度退化

> 源是结构化 GitHub issue 线程（4 条评论），按 to-postmortem 优化——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/8844
**fix 跟踪**：无 fix PR；官方回复定位（Nagisa125，2026-05-29）："显存用满后的重计算路径导致精度下降，关闭重计算可恢复"；issue closed completed 2026-05-29
**时间**：2026-04-30（报）～ 2026-05-29（closed completed）
**框架**：vllm 0.18.0 + vllm-ascend 0.18.0；GLM 5/5.1（GLM-new-w8a8）`--quantization ascend`，P/D 侧 DP2 TP16 + EP + deepseek_mtp
**平台**：未声明机型（四节点 PD 分离）
**category**：precision
**investigation_quality**：medium（作者自定位 + 官方确认；无代码级根因、无 PR、无数值复测）
**批量导入**：sed-g3（2026-09）
**pre-triage**：new_pattern（重计算族现有 10784/OOM、14871/AttributeError 两条 interrupt，无 precision 形态）

## 结构化 case

`postmortems/inbox/VLLM-ASC-8844.case.yaml`（Tier 2 候选，待 groom 审）

## 现象摘要

GLM 5/5.1 w8a8 四节点 PD 分离（P/D 各 TP16、DP2、EP + MTP），vllm-ascend 0.18.0：GPQA-diamond 精度实测 67.8%，低于论文/标准水平。TP≤4 时无精度问题；作者归纳触发条件 = 长输出 + 高并发 + D 节点显存持续饱和（`gpu-memory-utilization 0.92` + `recompute_scheduler_enable: true`）。D 节点显存不跑满则不出现。

## 一句话根因

D 节点显存长期打满后 vllm-ascend 进入 recompute（重计算）路径，该路径（具体机制未定位到代码/算子）输出精度劣于正常路径 → 大 TP PD 分离长稳场景 benchmark 精度不达标。官方确认方向：显存用满后的重计算路径导致精度下降，关闭重计算可恢复。

## fix / 规避

无合入 PR。将 `--additional-config` 的 `recompute_scheduler_enable` 置 false（或调低 D 节点显存占用/并发避免饱和）后重启。诚实标注：关闭后 GPQA 数值未回填线程、无代码级根因；勿当长期修复推广。

## verification

**upstream-maintainer-confirmed**（无 fix PR；官方回复确认 resolution，issue closed completed）
