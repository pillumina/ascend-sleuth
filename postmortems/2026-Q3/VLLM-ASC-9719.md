# VLLM-ASC-9719: Minimax W8A8 启动 OOM、权重显存翻倍——modelslim 权重 config.json 误带 quantization_config 跳过 per-layer 加载（官方解=重下正确权重）

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest r2-sed-g4（2026-09）产出，进 inbox 待 groom 分诊；不改正式 knowledge/ 目录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/9719
**同族官方结论**：#9894（kunpengW-code 提交）："If this problem occurs, the downloaded weight version may be incorrect. Check whether the config.json contains quantization_config. If yes, update the file again."（正确权重：modelscope Eco-Tech/MiniMax-M2.5-w8a8-QuaRot）
**fix 跟踪**：无 merged fix PR——PR #9734（改卫语句）被维护者 kunpengW-code 拒绝未合入（"modelslim 导出的权重不应含 quantization_config，纳入会掩盖错误权重定位"）；issue 9719/9894 closed completed
**时间**：2026-05-29 ~ 2026-06-02
**框架**：vLLM 0.20.2 + vllm-ascend main（commit 2e94f541）；Minimax m2.5-w8a8-quarot
**category**：interrupt
**investigation_quality**：high（源码级定位卫语句 + 显存实测对照 + 维护者确认权重格式结论）
**verification**：upstream-maintainer-confirmed（无 merged fix PR）
**novelty**：variant_of VLLM-ASC-10610——同 modelslim_config.py 的 quant_description 加载族；10610 = quant_description 缺 per-layer key → KeyError；本条 = 顶层键占位致卫语句误判 → 全层 bf16 退化 2× 显存（权重文件错误型，官方解=修正权重）

## 现象摘要

Minimax m2.5-w8a8-quarot 启动失败，加载权重显存为预期约 2 倍（~27GB → ~54GB/shard），触发 OOM（历史版本正常）。

代码层机制（pokomenMaster 定位）：

- 模型 `config.json` 含 `quantization_config`（quant_method/bits/group_size 等**顶层键**，无 `.weight` 结尾的 per-layer 键）；
- `AscendModelSlimConfig.from_config` 把这些顶层键填入 `self.quant_description`（非空）；
- `maybe_update_config` 卫语句 `if self.quant_description: return` 判真 → **跳过加载 `quant_model_description.json`**（真正含 per-layer 量化类型）；
- `get_quant_method` 无法判定层 scheme → 全部 Linear 回退 **bf16** 加载 → 显存 ×2 → OOM。

## 一句话根因

下载的 modelslim 权重**版本错误**：正确导出的 config.json **不应含 quantization_config**。错误变体带顶层 `quantization_config` → vllm-ascend 的 `if self.quant_description: return` 卫语句误判"已有量化描述"→ 跳过 per-layer json → 全层按 bf16 加载（~27GB→~54GB/shard）→ OOM。

## fix（官方解，无代码补丁）

1. 检查 `<model_dir>/config.json` 是否含 `quantization_config`；
2. 含 → **重新下载正确权重**（modelscope Eco-Tech/MiniMax-M2.5-w8a8-QuaRot 等官方 modelslim 导出）；
3. 重启服务：正确权重显存回到 int8 预期（~27GB/shard），服务拉起。

PR #9734 的代码侧修复（卫语句改 `any(k.endswith(".weight") ...)` 等）被维护者拒绝——modelslim 导出权重本就不该带 quantization_config，纳入会掩盖错误权重定位，不采用。

## 建议 triage 路由症状

启动 OOM 已被 inference_interrupt 现有正则覆盖（`out of memory`/`\bOOM\b`）；判别要点在 config.json 检查（本 case 已含于诊断），无需新增路由。
