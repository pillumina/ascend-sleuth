# VLLM-ASC-3308: Qwen3-Next-80B-A3B TP8 在 v0.11.0rc0 拉起即 NPU OOM——0.11.0rc0 适配期 bug，v0.11.0rc1+ 修复

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest r2-sed-g1（2026-09）产出，进 inbox 待 groom 分诊；不改正式 knowledge/ 目录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/3308
**fix 跟踪**：repo 自动化回复（2026-06-02，issue 关闭方）称修复已合入 v0.11.0rc1+，指向 PR #3305/#3557。API 核查：#3305 [Bugfix] Fix ascend config for qwen3-next（修 #3291）内容以 commit `408606c0c`（2025-09-30）直提交 main、PR 本体 closed-unmerged；#3557 为文档 PR（非修复）。即"修复代码在 main、含于 v0.11.0rc1（2025-11-10）"，但以直提交而非 PR merge 形态，自动回复的 PR 编号表述不精确
**时间**：2025-10-02（报）~ 2026-06-02（自动关闭 completed）
**框架/平台**：vllm-ascend v0.11.0rc0；Qwen3-Next-80B-A3B-Instruct（大 MoE）；TP8（910B 系 8 卡）
**category**：interrupt
**investigation_quality**：medium（修复版本与 commit 可核实；OOM→ascend_config 的代码级因果未在 issue 线程展开，凭自动化回复 + 成功配方推理）
**verification**：upstream-maintainer-confirmed（无可直接钉死的 merged fix PR；修复代码 commit 408606c0c 在 main/rc1+；自动回复确认 resolution）
**novelty**：new_pattern——库内无 qwen3-next 大 MoE 启动 OOM / 0.11.0rc0 ascend_config 适配期 case；现有 OOM case（10784 运行期 recompute 展开、12345 host 内存增长）机制/阶段均不同

## 现象摘要

v0.11.0rc0 起 Qwen3-Next-80B-A3B-Instruct（TP8，--max-model-len 98304，未 enforce-eager）服务，EngineCore 启动阶段 NPU OOM：

```
RuntimeError: NPU out of memory. Tried to allocate 628.00 MiB (NPU 0; 29.50 GiB total capacity;
  27.39 GiB already allocated; 27.39 GiB current active; 478.15 MiB free; 27.80 GiB reserved in total by PyTorch)
...
RuntimeError: Worker failed with error 'NPU out of memory. ...', please check the stack trace above for the root cause
```

内存充足（多卡 910B、--gpu-memory-utilization 0.7）仍 OOM。

## 一句话根因

v0.11.0rc0（Qwen3-Next 首支持期）适配 bug：qwen3-next 启动路径 ascend_config 初始化/配置异常（同族 #3291 报 "Ascend config is not initialized"），内存估算/预留失真 → TP8 拉 80B-A3B 时启动即 NPU OOM；修复（commit `408606c0c`，PR #3305 同内容直提交）含于 v0.11.0rc1+。

## fix

- 升级 vllm-ascend ≥ v0.11.0rc1（修复 commit 408606c0c 已含）。
- 缓解参数（wxsIcey 实测）：TP8 时 `--gpu-memory-utilization 0.5` + `export PYTORCH_NPU_ALLOC_CONF=max_split_size_mb:32`（或 `expandable_segments:True`）。
- 现场过渡配方（ej1-hw）：0.11.0rc0 基座 + 升级 torch≥2.8.0 / torch-npu≥2.8.0rc1 + 打 ascend_config 修复 wheel（对应 commit 408606c0c）。

## 弯路与级联

- 勿只当"显存不够"调参处理——同版本小 MoE/普通模型正常，80B-A3B TP8 必现，指向适配期内存配置缺陷；升级是主修，调参只是缓解。
- #3291（Ascend config is not initialized）/ #3551 / #3564 同族，均可按"qwen3-next + 0.11.0rc0 → 升级 rc1+"处理。

## 建议 triage 路由症状

`NPU out of memory` 已被 inference_interrupt 覆盖；无需追加路由。
