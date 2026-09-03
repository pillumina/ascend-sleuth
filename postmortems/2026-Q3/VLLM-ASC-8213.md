# VLLM-ASC-8213: MiniMax-M2.7 在 vllm-ascend 0.17/0.18 镜像（A3）启动失败——tokenizer 加载报 ValueError: Tokenizer class TokenizersBackend does not exist，镜像 transformers 4.57.6 过旧，容器内升级 transformers ≥5.5.3 解决

> 源是结构化 GitHub issue 线程（4 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/8213
**fix 跟踪**：无 vllm-ascend/上游 PR；修复=容器内 `pip install transformers==5.5.3`（4.57.6 → 5.5.3，v0.18.0rc1-a3-openeuler 实测启动成功，报者关闭 completed 2026-04-22）；备选路线=Eco-Tech/MiniMax-M2.7-w8a8-QuaRot + quay vllm-ascend:main（A2 实测，非 A3 验证）
**时间**：2026-04-13 ~ 2026-04-22（completed）
**框架**：vllm-ascend v0.17.0rc1-a3-openeuler / v0.18.0rc1-a3-openeuler（镜像内 transformers 4.57.6）+ MiniMax-M2.7（bf16，vllm-ascend 检测到 fp8 checkpoint 自动反量化 bf16 加载）
**平台**：Ascend 910C（A3-910C，A3 单机）
**category**：interrupt（启动失败，ApiServer 进程崩）
**investigation_quality**：medium（启动失败单点 + 现场版本试验定位 transformers 依赖；无代码级根因，无官方确认）
**verification**：engineer-report（报者现场升级 transformers 4.57.6→5.5.3 后 v0.18.0rc1-a3 启动成功闭环，无上游 fix PR——沿用 KB VLLM-ASC-8798 的档位先例）
**pre-triage**：new_pattern（现库无 MiniMax-M2.7/transformers 依赖版本 case；邻近 VLLM-ASC-12685 是 M2.7 fp8 路由到 AscendFp8Config 的 o_groups AttributeError，根因不同）

## 现象摘要

- A3 单机，quay.io/ascend/vllm-ascend:v0.17.0rc1-a3-openeuler 与 v0.18.0rc1-a3-openeuler 拉起 MiniMax-M2.7 服务（TP8 DP2 EP，FULL_DECODE_ONLY）均失败。
- 报错：ApiServer 进程 traceback 终止于 tokenizer 加载（`renderer_from_config → cached_get_tokenizer → AutoTokenizer.from_pretrained`）抛 `ValueError: Tokenizer class TokenizersBackend does not exist or is not currently imported.`
- 日志先打印 `Resolved architecture: MiniMaxM2ForCausalLM` + `Detected fp8 MiniMax-M2 checkpoint on NPU. Disabling fp8 quantization and loading dequantized bf16 weights instead.`——权重加载本身不是崩溃点。
- 用户 yang0754（bf16 权重）：容器内 pip install transformers==5.5.3（4.57.6 → 5.5.3）后 v0.18.0rc1-a3-openeuler 正常启动。
- 另一路线（评论#1）：Eco-Tech/MiniMax-M2.7-w8a8-QuaRot + quay vllm-ascend:main，A2 实测可跑（fp8 权重直跑不支持，需 w8a8-QuaRot 版本——该结论未在 A3 复核）。

## 一句话根因

MiniMax-M2.7 的 tokenizer 配置依赖 transformers ≥5.5 新增的 TokenizersBackend 后端类；vllm-ascend 0.17/0.18 的 a3 镜像内 transformers 4.57.6 过旧，ApiServer 初始化 tokenizer（renderer 路径）时 AutoTokenizer 找不到 TokenizersBackend 类抛 ValueError，服务启动失败。容器内升级 transformers 到 5.5.3（≥5.5.x）即可。

## fix

- 容器内升级依赖：`pip install transformers==5.5.3`（≥5.5.x）后重启服务（v0.18.0rc1-a3-openeuler 实测通过）。
- 备选：MiniMax-M2.7 用 w8a8-QuaRot 量化权重（Eco-Tech）+ 更新版 vllm-ascend 镜像（main；A2 实测，A3 未复核）。

## 弯路与级联

- 弯路：评论#1 最初判断"是 fp8 的不支持，换 w8a8-QuaRot"——报者澄清其跑的是 bf16 权重（日志显示 fp8 checkpoint 会被自动反量化 bf16 加载），真正缺口在 transformers 版本，勿只按量化路线处理。
- 级联：ApiServer 多进程（ApiServer_0/1 同栈）相继崩，EngineCore 启动日志正常——判型以 tokenizer 加载的 ValueError 文本为准。
