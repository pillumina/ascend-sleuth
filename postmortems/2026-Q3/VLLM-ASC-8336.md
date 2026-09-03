# VLLM-ASC-8336: qwen3.5 35B w8a8 910B main 镜像压测崩溃 — AttributeError: WAITING_FOR_FSM（balance scheduling patch × 配套 vLLM 版本错位）

> 源是结构化 GitHub issue 线程 + 修复 PR，按 to-postmortem 优化——只写指针+结论，不重写全文。
> 批量导入：sed-g3（2026-09）；脱敏：源日志含内网 IP（mq_connect_ip 7.242.*）未写入本草稿，无替换。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/8336（created 2026-04-16，closed completed 2026-07-03，comments=4）
**修复 PR**：https://github.com/vllm-project/vllm-ascend/pull/8448（[Misc]update vllm to v0.19.1，merged 2026-04-28；经上游 https://github.com/vllm-project/vllm/pull/38048 修复 WAITING_FOR_FSM）
**框架**：vllm-ascend（推理侧，910B3 / A2-910B）
**category**：interrupt
**investigation_quality**：medium（官方确认 fix PR + 用户实测 workaround + 关闭 completed，闭环完整；根因从栈+PR 描述推导，无 issue 内维护者显式定论）
**verification**：upstream-fix-merged（'fix PR #8448'）

## 现象摘要

- Qwen3.5-35B-A3B-w8a8-mtp（--quantization ascend、auto tool choice/reasoning parser、async scheduling）vllm-ascend main/dev（0.17.0rc2.dev312+g1eb0cc0e4）+ 配套 vLLM v0.19.0，导出 `VLLM_ASCEND_BALANCE_SCHEDULING=1`，910B3 单卡压测一压就崩。
- EngineCore fatal：`vllm_ascend/patch/platform/patch_balance_schedule.py:297` scheduler.schedule() 内 `if request.status == RequestStatus.WAITING_FOR_FSM:` 触发 enum `__getattr__` → `AttributeError: WAITING_FOR_FSM`（空闲启动正常，请求进入后即崩）。
- 级联噪声：APIServer AsyncLLM output_handler failed → `EngineDeadError` → 大量 completion stream generator / serving.py 报错 → WorkerProc shutting down、服务退出。
- workaround 实测：注释掉 `export VLLM_ASCEND_BALANCE_SCHEDULING=1` 不再崩溃，但用户报告性能下降。

## 一句话根因

vllm-ascend 的 balance scheduling 是自定义调度 patch（patch_balance_schedule.py），其 :297 的 WAITING_FOR_FSM 分支按配套 vLLM v0.19.1（vllm#38048 才引入 `RequestStatus.WAITING_FOR_FSM` 成员）编写；issue 环境配套 vLLM v0.19.0 的 RequestStatus 尚无该枚举成员，首请求调度即 AttributeError → EngineCore fatal。

## fix

升级到含 PR #8448 的 vllm-ascend（配套 vLLM 升至 v0.19.1）。受影响区间：配套 vLLM v0.19.0（及更早缺失该枚举的配对）的 vllm-ascend main/dev 组合；#8448 merged 2026-04-28，官方 2026-06-11 确认最新 release/rc 已解决。
临时 workaround：去掉 `export VLLM_ASCEND_BALANCE_SCHEDULING=1`（关闭 balance scheduling 规避崩溃），代价是性能下降。
