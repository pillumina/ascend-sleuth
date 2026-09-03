# VLLM-ASC-7856: GLM-4.7-w8a8（float-mtp）流式工具调用 tool_calls 解析异常（json 不闭合/格式错乱），非流式正常——上游 vLLM 问题（PR #29947），升级 vLLM ≥0.18.0 修复

> 源是结构化 GitHub issue 线程（7 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/7856
**fix 跟踪**：上游 vLLM PR #29947（"[Frontend] OpenAI Responses API supports Tool/Function calling with streaming"，merged 2026-03-12，随 vLLM 0.18.0 发布）；vllm-ascend 侧无独立 fix——v0.18.0rc1 镜像（含 vLLM 0.18.0）复测通过
**时间**：2026-03-31 ~ 2026-04-07（completed，报者自关）
**框架**：vllm-ascend v0.17.0rc1 镜像（GLM-4.7-W8A8-floatmtp，Eco-Tech）+ 双机 910B 16 卡
**平台**：Ascend 910B（A2-910B，双机 16 卡）
**category**：precision（流式 tool-call 输出格式错误）
**investigation_quality**：medium（多轮复现 + 抓包 + 流式/非流式对照 + 0.18.0 复测闭环；根因由报者定位到上游 vllm 并给 PR，无代码级确认）
**verification**：upstream-fix-merged（上游 vllm-project/vllm#29947，merged 2026-03-12；报者 v0.18.0 复测闭环）
**pre-triage**：variant_of VLLM-ASC-12030（同族=GLM 系流式 tool-call 响应解析/输出异常，precision；增量=模型 GLM-4.7、根因在上游 vLLM tool parser（#29947，≥0.18）而非 vllm-ascend glm4_moe_tool_parser（0.23.0 修复的 GLM5.1 场景））

## 现象摘要

- 双机 910B 16 卡 + GLM-4.7-W8A8-floatmtp（Eco-Tech，modelscope）+ vllm-ascend v0.17.0rc1 官方镜像 + 官方 GLM4.x 部署文档。
- opencode/webfetch 场景问"洛杉矶天气怎么样"等触发工具调用：模型输出 tool_calls 格式不正确、arguments json 不闭合/拼接错误，工具调用 100% 失败（报者实测）。
- 流式（stream=true）必现异常（甚至 json 括号不闭合）；非流式（stream=false）同请求正常。
- 简单示例 curl（纯文本/无 tools 上下文）正常，不触发函数调用——仅在带 tools + tool_choice 的真实场景暴露。
- v0.18.0（vllm-ascend v0.18.0rc1 镜像，含 vLLM 0.18.0）复测通过 → 报者关闭。

## 一句话根因

GLM-4.7 流式 tool-call（tools + tool_choice=auto + webfetch 类请求）在 vLLM <0.18 的流式 parser 路径输出残缺/不闭合的 arguments json（工具调用失败）；非昇腾特有（GPU 同版本同样，报者与维护者均无法用 GPU 对照排除的"模型 vs vllm"疑问最终落到上游）。上游 vllm PR #29947 修复流式 tool/function calling，随 vLLM 0.18.0 发布；vllm-ascend 0.17.0rc1 镜像内 vLLM 过旧即缺陷面。

## fix

升级到 vLLM ≥0.18.0（vllm-ascend 0.18.0rc1 及以上镜像内含），无需 vllm-ascend 侧改动。无配置 workaround。

## 弯路与级联

- 弯路：维护者 aipaes 引导 3 条排查线（简单 curl 复现 / 核对 modelscope 权重一致性 / 换官方 bf16 权重对照量化权重）——均未能定位；报者 gbdjxgp 以"流式必现 vs 非流式正常 + 抓包"收敛到流式 parser 路径，最终确认上游 vllm 修复。
- 忽略项：模型权重本身无问题（非量化的 bf16 版本同样会触发），勿按"量化权重缺陷"方向排查。
