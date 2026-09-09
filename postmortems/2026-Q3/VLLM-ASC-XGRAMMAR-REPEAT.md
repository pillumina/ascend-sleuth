# VLLM-ASC-XGRAMMAR-REPEAT: Qwen2.5 结构化输出持续换行不终止（xgrammar 约束与内容冲突）

> 源是结构化文档（msprobe 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprobe/blob/tag_MindStudio_26.2.0.B050_003/docs/zh/best_practices/inference_reply_replay_problem_of_Qwen2.5.md
**时间**：2026-09-09（沉淀）
**框架**：vllm-ascend（vLLM 推理框架 + 结构化输出）
**category**：precision
**investigation_quality**：high（eager/采样参数/结构化输出/硬件相关性逐一排除 + 三段定界）
**namespace 建议**：inference/vllm-ascend/

## 结构化 case

`knowledge/inference/vllm-ascend/precision/VLLM-ASC-XGRAMMAR-REPEAT.yaml`（已转正 Tier 2）

## 一句话根因

prompt 中待格式化内容的转义双引号（\"）因采样随机性被替换为裸双引号（"），xgrammar 据此认为字符串已闭合、掩盖后续输出；JSON 合法性与回复完整性冲突 → 持续输出换行、不终止。

## 弯路与级联

- **定界手法**：把推理分为「输入预处理 → 模型前向执行 → 数据后处理」三段，先定界到后处理（采样阶段），再深挖。
- **先排除**：eager 模式、采样参数、硬件相关性。
