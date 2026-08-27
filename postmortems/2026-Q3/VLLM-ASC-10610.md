# VLLM-ASC-10610: GLM-5.2-w8a8 拉起报 KeyError（modelslim 量化描述缺 indexer 层权重 key，需 vLLM 0.23.0 + PR #10441）

> 源是结构化 GitHub issue 线程（14 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/10610
**fix 跟踪**：PR #10441（vllm_ascend/quantization/modelslim_config.py 相关，合入 main）；vLLM v0.23.0 + 含 #10441 的 vllm-ascend main 源码编译后解决（xw1216 确认，Dbgsaoge 同证）；issue 本身 stale 关闭
**时间**：2026-06-17 ~ 2026-08-09
**框架**：vllm-ascend v0.21.0rc2 / releases/v0.22.1rc（失败）→ vLLM v0.23.0 + vllm-ascend main（成功）
**平台**：A2-910B（910b2，TP16/TP12 + EP）
**category**：interrupt
**investigation_quality**：high（多用户复现 + 报错栈完整 + 社区给出可复现修复组合；官方未在 thread 内给出代码级答复，靠社区闭环）
**批量导入**：批次 2 组 4（2026-08）

## 一句话根因

GLM-5.2 新增 indexer 注意力结构，而 vllm_ascend/quantization/modelslim_config.py 的 `get_linear_quant_type` 直接索引 `quant_description[prefix + ".weight"]`，modelslim 量化描述未覆盖 `model.layers.N.self_attn.indexer.wq_b.weight` 这一新 key，w8a8 加载即抛 KeyError。

## 弯路与级联

- **版本弯路**：用户先在 v0.21.0rc2 复现，换 releases/v0.22.1rc 依然同样 KeyError（Dbgsaoge）——问题不在 0.21/0.22 之间的演进，而在 vllm-ascend 侧对 GLM-5.2 indexer 结构的适配（PR #10441 只进 main）。
- **官方镜像陷阱**：quay.io 官方镜像的 glm5.2 标签不保证含 PR #10441，需源码编译 main；xw1216 建议直接 vLLM v0.23.0 + vllm-ascend main 编译（若依赖冲突只升 FastAPI）。
- **姊妹 issue**：#11208（v0.22.1rc ModuleNotFoundError）指向同一修复组合——GLM-5.2 适配一律先核对是否含 PR #10441。
- **不要改模型/量化参数**：KeyError 是加载侧 schema 缺失，不是模型文件或 --quantization 用法问题。
