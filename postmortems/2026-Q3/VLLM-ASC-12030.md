# VLLM-ASC-12030: GLM5 流式 tool-call 响应单词最后 1 个字符重复（glm4_moe_tool_parser.py 解析缺陷，0.23.0 已修复）

> 源是结构化 GitHub issue 线程（9 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/12030
**fix 跟踪**：无独立 PR；修复随 v0.23.0 发布（`glm4_moe_tool_parser.py` 更新）；workaround 为评论#3 附件修复版脚本
**时间**：2026-07-14 ~ 2026-08-25
**框架**：vllm-ascend 0.20（复现）→ 0.23.0（修复）；GLM-5.1 w8a8
**平台**：910C（A3）PD 分离
**category**：other
**investigation_quality**：medium（必现 curl + 修复脚本 + 0.23.0 同 curl 复测闭环；未给代码级 diff 定位）
**批量导入**：批次 2 组 2（2026-08）

## 结构化 case

`postmortems/inbox/VLLM-ASC-12030.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

GLM5 流式 tool-call 响应经 vllm-ascend 特有的 `glm4_moe_tool_parser.py` 解析，parser 解析逻辑缺陷使特定请求（function-calling）流式响应中单词最后 1 个字符重复；非流式响应不经此 parser 故正常。0.23.0 已修复，评论#8 用同一 curl 复测通过。

## 弯路与级联

- **判别要点**：先确认"仅流式、仅特定请求（tool-call）、非流式正常"——这三点把问题收敛到 GLM5 流式输出/解析路径，而非权重/采样/量化。
- **复现**：带 `tools` + `tool_choice=auto` 的 curl（如"请把任务 1 的状态更新为已完成"）多试几次必现。
- **修复路径**：升级 0.23.0（官方路径）或临时替换评论#3 附件修复版 `glm4_moe_tool_parser.py`（workaround）。
