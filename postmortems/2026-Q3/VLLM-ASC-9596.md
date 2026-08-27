# VLLM-ASC-9596: Qwen3-4B TP=8 默认 PIECEWISE graph capture 失败（昇腾 NPU stream/SQ-CQ 资源预算限制）

> 源是结构化 GitHub issue 线程（4 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/9596
**fix 跟踪**：无已合入修复；大规模重构 #9691 进行中；workaround（FULL_DECODE_ONLY + 缩小 cudagraph_capture_sizes / enforce-eager）用户三组对照实验验证
**时间**：2026-05-26 ~ 2026-08-11（stale 关闭）
**框架**：vllm-ascend v0.19.1rc1 + vLLM 0.19.1，CANN 8.5.1
**平台**：昇腾 NPU（npu-smi 仅标 Ascend910，未区分 A2/A3）
**category**：interrupt
**investigation_quality**：high（维护者 yiz-liu 确认为 Ascend stream 资源预算限制，给出官方文档/博客出处；用户三组对照实验自证 workaround）
**批量导入**：批次 2 组 4（2026-08）

## 一句话根因

TP=8 下默认 PIECEWISE（mixed prefill-decode）图捕获所需的 capture stream/event/SQ-CQ 数量超过昇腾 NPU stream 资源预算（[SqCqManage]Alloc sq cq fail 0x7020023 → rtStreamWaitEvent resource alloc fail 207005 → capture_end 507903），捕获序列失效导致启动失败；TP=1 或 FULL_DECODE_ONLY 资源需求小，不触发。

## 弯路与级联

- **对照实验是关键证据**：同一 TP=8 下 `--enforce-eager` 正常、`FULL_DECODE_ONLY + cudagraph_capture_sizes=[1,8,16,32,60]` 正常、TP=1 正常——三组对照把根因钉死在 PIECEWISE 捕获的资源消耗上，排除算子/模型问题。
- **文档依据**：官方 ACL_Graph 文档 "stream-budget constrains capture breadth" 章节 + yiz-liu 博客（graphs-in-vllm-ascend-2）直接解释该限制；groom 可把文档链接挂进 case。
- **这是平台限制不是 bug 回归**：维护者原以为已修完所有 edge case（"I thought we had fixed all the edge cases"），说明同类 stream 预算问题有历史记录，检索时留意。
- **后续**：#9691 大规模重构进行中，合入后此 workaround 可能不再需要——groom 跟踪 #9691。
