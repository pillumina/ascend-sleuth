# VLLM-ASC-9507: minimax2.7 + PCP 开启时 curl 报错——FULL 图模式不支持 PCP（官方确认限制，workaround 型）

> 源是结构化 GitHub issue 线程（7 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/9507
**fix 跟踪**：无代码修复——官方确认功能限制（FULL 图模式不支持 PCP，仅 FULL_DECODE_ONLY 支持）；workaround 用户验证有效；乱码问题（--no-async-scheduling）未确认即 stale 关闭
**时间**：2026-05-25 ~ 2026-08-11（stale 关闭）
**框架**：vllm-ascend v0.19.1rc1 + vLLM 0.19.1，minimax2.7-w8a8，TP4 + PCP2
**平台**：A2-910B（910B3，npu-smi 25.5.2）
**category**：interrupt
**investigation_quality**：medium（维护者一句话确认限制 + 用户切换后 curl 成功；后续乱码问题未闭环）
**批量导入**：批次 2 组 4（2026-08）

## 一句话根因

vllm-ascend 的 PCP（prefill context parallel）只支持 FULL_DECODE_ONLY 图模式；默认 FULL 图模式下 decode 更新图参数时 `attn_metadata.decode_meta` 为 None，`attention_cp.py:324` 访问 `.num_computed_tokens_of_pcp_dcp` 抛 AttributeError（'NoneType' object has no attribute ...）。

## 弯路与级联

- **workaround 型 case**：这是"官方确认限制 + 用户切换配置成功"的闭环，不是代码修复——fix 是 `--compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY"}'`（lilinsiman 确认，nie-linfeng 实测 curl 成功），不要把"支持 PCP"当预期写进 fix。
- **级联的第二个问题**：切 FULL_DECODE_ONLY 后 PCP 崩溃消失，但出现输出乱码（重复思考 token），官方建议 `--no-async-scheduling` 但未获用户确认——这是独立现象，诊断时不要混为 PCP 限制的一部分。
- **报错签名**：`AttributeError: 'NoneType' object has no attribute 'num_computed_tokens_of_pcp_dcp'`（attention_cp.py update_graph_params）是 PCP+FULL 图模式的专属签名。
