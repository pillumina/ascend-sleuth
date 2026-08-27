# VLLM-ASC-10784: Kimi-k2.5 PD 分离 2P1D decode 侧 OOM（请求竞争触发 recompute，MoE shared expert 展开内存爆炸）

> 源是结构化 GitHub issue 线程（7 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/10784
**fix 跟踪**：无 PR；官方（Dawn952）确认 "known issue — recompute may cause memory anomalies, use the latest version to resolve"（未指明版本/PR）；issue stale 关闭
**时间**：2026-06-22 ~ 2026-08-08
**框架**：vllm-ascend v0.18.0（g747cfcb07）+ vLLM v0.18.0，Kimi-k2.5，2P1D PD 分离
**平台**：未在 thread 内明确（昇腾 NPU）
**category**：interrupt
**investigation_quality**：high（用户用 OOM 快照 + recompute 分支打印 + npu_grouped_matmul 输入 shape 打印完成机制确认；官方确认 known issue）
**批量导入**：批次 2 组 4（2026-08）

## 一句话根因

Kimi-k2.5 PD 分离 decode 侧高并发下请求竞争触发 preemption→recompute；recompute 分支中昇腾 MoE shared expert 展开（_moe_forward_shared）与 torch_npu.npu_grouped_matmul 的 batch 维度异常放大（1024→508648），中间激活膨胀至 61GB 级导致显存不足 OOM。

## 弯路与级联

- **快照定位法**：用户用 `OOM_SNAPSHOT_ENABLE=1` dump 快照，直接看到 _moe_forward_shared 在最后一次 segment_map 前膨胀到 61GB、随后 npu_grouped_matmul_gmm2 请求 3.4GB+112MB（workspace）失败——这是把 OOM 归因到具体算子的标准路径。
- **recompute 确认**：给 npu_grouped_matmul_gmm2 加输入 shape 打印 + 在 recompute 分支加打印，实证"竞争→preemption→recompute→输入爆炸"链条——没有这一步就只会看到笼统的 OOM。
- **官方答复是 known issue 不是根因**："use the latest version" 无版本号/PR，groom 需后续确认新版修复落点再回填 compat；当前按 pending-investigation 处理。
- **规避方向**：降低 max-num-seqs/并发，减少 preemption 触发 recompute；这是运维侧缓解，不是修复。
