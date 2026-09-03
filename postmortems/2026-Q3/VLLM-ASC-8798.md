# VLLM-ASC-8798: Qwen3.5 系列（27B/35B-A3B/397B）enable_thinking 下概率性无限重复输出——模型能力问题（非框架 bug）

> 源是结构化 GitHub issue 线程（多用户复现 + A/B 消融定量），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest sed-g1 批次 1 产出，进 inbox 待 groom 分诊。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/8798
**框架/平台**：vllm-ascend v0.18.0rc1 镜像 / 8×910B4；Qwen3.5-27B（另确认 Qwen3.6-27B、Qwen3.5-35B-A3B、Qwen3.5-397B-A17B-W4A8 同现）
**category**：precision
**investigation_quality**：medium（多用户同现 + 用户 A/B 替换实验定量（80%→3%）；结论为负向推断"模型能力"，无代码级根因）
**verification**：engineer-report（无上游 fix；用户现场 A/B 实验验证规避路径：Qwen3.5→Qwen3.6 重复率大幅下降）
**novelty**：new_pattern——库内无 Qwen3.5 thinking 重复输出 case；与 10892（310P MoE 算子精度→过度思考）表象相近但根因不同，互为判别

## 现象摘要

Qwen3.5-27B（v0.18.0rc1 镜像，MTP speculative + async-scheduling，`chat_template_kwargs.enable_thinking=true`）请求要求"只输出 json{...} 不要其他内容"，概率性出现 **thinking 段无限自我重复**（实样：`Wait, I'll output json{"Answer": B}` 类句子重复数百行直到 `max_completion_tokens`=8192 耗尽，`reasoning_tokens: 0`、finish 靠 budget 截断）。

- 多用户确认：Qwen3.6-27B / Qwen3.5-35B-A3B / Qwen3.5-397B-A17B-W4A8 同样"thinking 思维链挂死/重复"——均在 enable_thinking 开启时概率出现。
- 维护者建议 PR#8764（async-scheduling 下 num_accepted_tokens 非阻塞拷贝竞态）或关 `--async-scheduling`——用户两种都试仍复现，排除该框架竞态。
- **用户收尾 A/B**：同评测集 Qwen3.5-27B 语言/代码补全重复率 45%/37%；Qwen3.6-27B 未出现。用户反馈 case 请求 ×30：Qwen3.5 重复概率 80%/12.5%，Qwen3.6 为 3%/0% → **结论：大概率模型能力问题**，非昇腾/框架 bug。
- 补充：`thinking_token_budget` 在开源框架不可调（阿里云 Model Studio API 专属），别当 workaround 建议。

## 一句话根因

Qwen3.5 系模型在 enable_thinking 模式下的概率性重复输出/思维链死循环是**模型自身能力/生成行为**问题（换同代 Qwen3.6 后重复率从 80% 降到 3% 以下），非 vllm-ascend 框架缺陷；框架侧候选（async-scheduling 竞态 PR#8764、关 async-scheduling）消融后仍复现，予以排除。

## fix（规避）

- 换用 **Qwen3.6 系**模型（同任务重复率大幅下降，用户实测）；
- 或关闭 enable_thinking（thinking 段不产生即不触发）；
- 不要建议 thinking_token_budget（开源框架不可调）；PR#8764 / 关 async-scheduling 无效（已消融排除）。
