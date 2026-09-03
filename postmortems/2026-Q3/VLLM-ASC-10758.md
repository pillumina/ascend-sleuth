# VLLM-ASC-10758: minimax-m2.5 工具调用末尾拼接 `</parameter>`——流式 tool-call parser 在参数未闭合时输出 delta

> 源是结构化 GitHub issue 线程 + 两个关联 PR（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest sed-g1 批次 1 产出，进 inbox 待 groom 分诊。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/10758
**关联 fix PR**：
- vllm-ascend #10817（[BugFix][v0.20.2rc] Avoid streaming partial MiniMax parameter tags）——**open 未合入**（v0.20.2rc 窄 backport）
- vllm-ascend #10377（DeltaMessage 补 tool_calls list）——closed **未合入**，维护者判定 fix 有误（引入 `write_file() missing ... args` 回归），勿采用
- vLLM 上游 #45701（[Frontend] Add Streaming Parser Engine and new MinimaxM2 Parser）——merged 2026-06-16，主线修复
**框架/平台**：vllm-ascend v0.20.2rc1（+ minimax-m2.5-w8a8-QuaRot，eagle3 speculative，MiniMax-M2 tool parser）→ A2（Atlas 800I A2，HDK 25.5.1）
**category**：interrupt（sed-g1 定；与存量工具调用类 case 10954 同归 interrupt）
**investigation_quality**：medium（vllm-ascend 开发者 PR 描述定位机制 + 用户 on-site 验证；但最终修复路径 open/有波折，无干净合入闭环）
**verification**：investigation（关联 fix PR #10817 open 未合入；主线修复在 vLLM 上游 #45701）
**novelty**：variant_of VLLM-ASC-10954——工具调用 parser 输出损坏族（10954=GLM 工具幻视→json 参数类型，机制=vllm parse 逻辑；本条=流式 parser 未闭合参数尾片，机制=增量序列化粒度），模型与机制均不同但同"工具调用输出/传参错误"族

## 现象摘要

v0.20.2rc1 + MiniMax-M2.5 工具调用（`--tool-call-parser minimax_m2 --enable-auto-tool-choice`），流式响应中工具调用**末尾拼接残缺的 `</parameter>`**（如参数值后接 `a.txt</parameter`）导致调用方路径/参数解析失败。同一流中 *最终解析出的* tool call 本身正确——问题在**流式增量序列化**：MiniMax-M2.5 tokenizer 会把 `</parameter>` 切成多片（`</`、`parameter`、`>`），增量 parser 在参数值仍打开时就序列化输出。

- 用户 on-site 应用 PR#10817 后原问题解决；再叠 PR#10377 修 DeltaMessage 缺 `tool_calls` 后出现新回归：复杂代码脚本请求报 `write_file() missing 2 required positional arguments: "file_path" and "content"`。
- 维护者 QwertyJack 判定 #10377 fix 有误（streaming DeltaMessage 补 tool_calls 的方式不对）。

## 一句话根因

MiniMax-M2 增量流式 tool-call parser（v0.20.2rc 的 vllm-ascend patch）在完整 `</parameter>` 闭合前就输出参数 delta，tokenizer 又把闭合标签切成多片，于是流式客户端收到的工具调用内容尾部带残缺 `</parameter>` 尾片 → 路径/参数识别失败。

## fix

- 主线：升级 vllm 到含 **vllm#45701**（Streaming Parser Engine + MinimaxM2 Parser，2026-06-16 合入）的版本——MiniMax-M2 移到 parser engine，按完成参数粒度输出。
- v0.20.2rc 不能升级时的窄修复：应用 vllm-ascend PR#10817（参数闭合后才发 delta）——**open 未合入**，需自行 cherry-pick/合入；**勿叠加 PR#10377**（维护者判定有误，会引入 tool_calls/参数缺失回归）。
