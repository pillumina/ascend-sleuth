# VLLM-ASC-9129: 310P 上 LLM-Compressor 的 compressed-tensors W8A8 模型拉起失败（KeyError PlatformEnum.OOT）——310P W8A8 需 modelslim + --quantization ascend

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest r2-sed-g4（2026-09）产出，进 inbox 待 groom 分诊；不改正式 knowledge/ 目录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/9129
**fix 跟踪**：无上游 fix PR——310P 平台设计约束；维护者 Tflowers-0129 给出用法约束（310P W8A8 → modelslim + `--quantization ascend`），zyz111222 补充模型支持提示（qwen3-asr 310P 未支持）；issue closed 2026-05-14（resolved）
**时间**：2026-05-13 ~ 2026-05-14
**框架/平台**：vllm-ascend v0.18.0rc1-310p 镜像（300iDuo / 310P）；LLM-Compressor w8a8 量化的 Qwen3-ASR-1.7B；对照 910B 同镜像可跑
**category**：interrupt
**investigation_quality**：medium（维护者源码级机制解释 + 910B/310P 平台对照；修复用法未被 reporter 复验、无 before/after 闭环）
**verification**：upstream-maintainer-confirmed（无 fix PR，机制与用法由维护者确认）
**novelty**：new_pattern——库内无 310P × compressed-tensors 量化格式选择 case；邻近 10610/12901（modelslim 描述缺 indexer key）、10122（310P QuantBatchMatMulV3 CANN bug 507015）、10834（w4a8 group 256）机制/签名均不同

## 现象摘要

310P（Atlas 300I Duo，v0.18.0rc1-310p 镜像）部署 LLM-Compressor 量化（`scheme="W8A8"`，config `quant_method: compressed-tensors`）的模型，模型加载阶段 EngineCore 启动失败，报错尾部：

```
File ".../vllm/model_executor/layers/quantization/compressed_tensors/schemes/compressed_tensors_w8a8_int8.py", line 50, in create_weights
    self.kernel = init_int8_linear_kernel(...)
File ".../vllm/model_executor/kernels/linear/__init__.py", line 223, in choose_scaled_mm_linear_kernel
    for kernel in possible_kernels[current_platform._enum]:
KeyError: <PlatformEnum.OOT: 6>
```

（栈经 vllm_ascend/ops/linear.py → QKVParallelLinear 权重创建；启动命令带 `--dtype=float16 --enforce-eager`，与报错无关。）

## 一句话根因

LLM-Compressor 导出的 compressed-tensors W8A8 路径在 310P 上没有 vllm-ascend 适配：310P 分支只注册 `AscendModelSlimConfig310`（910B 等非 310P 路径注册了 `AscendCompressedTensorsConfig` 可 override），模型加载落入 vLLM 原生 `CompressedTensorsW8A8Int8`，其 int8 linear kernel 选择器只支持 CPU/CUDA/ROCm，310P 属 `PlatformEnum.OOT` → `possible_kernels[current_platform._enum]` 查表 KeyError。**310P 的 W8A8 是平台约束：只支持 modelslim 量化格式。**

## fix

- 310P 部署 w8a8：改用 **modelslim 量化** + `--quantization ascend` 加载（进入 310P 已适配的 Ascend 量化路径）；LLM-Compressor 的 compressed-tensors 权重需重新量化或换官方 310P 权重。
- 若 modelslim 后仍失败 → 核对模型在 310P 的支持矩阵（zyz111222：qwen3-asr 模型 310P 未支持）。
- 910B 可用同一 compressed-tensors 权重（非 310P 注册了 compressed-tensors override）——平台不对称是判别证据。

## 弯路与级联

- 先怀疑 `--dtype=float16`/`--enforce-eager`（310P 不支持 bf16），均无关——报错在量化 kernel 选择，与 dtype 启动参数无关。
- issue 标题现象（910B 正常 vs 310P 失败）本身就是关键线索：格式适配按平台注册，310P 覆盖不全。

## 建议 triage 路由症状

`KeyError`/启动失败已被 inference_interrupt 现有正则覆盖（`启动失败`、`KeyError`）；新形态为 **`PlatformEnum.OOT` 签名 + 310P**，可考虑在 inference_interrupt 分支补 `PlatformEnum\.OOT|platform enum`（可选，needs-review）。
