# VLLM-ASC-13508: Gluon 兼容 stub 缺父模块，x86_64 导入 ModuleNotFoundError

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/13508
**fix 跟踪**：maintainer 确认跟进并关闭为 completed（修复落地 main，无独立 PR 号）
**时间**：2026-08-04 ~ 2026-08-25
**框架/平台**：vllm-ascend main2main（vLLM 0.26.0+empty）+ triton-ascend 3.2.1 + triton 3.2.0（x86_64）/ 3.5.0（arm）+ torch-npu 2.10.0.post2；A2 (910B)，x86_64 CPU
**category**：interrupt
**investigation_quality**：high
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（Phase B，第 2 批）

## 结构化 case

草稿：`postmortems/inbox/VLLM-ASC-13508.case.yaml`（Tier 2 入库前待 groom 分诊）。

## 一句话根因

vLLM main 在 HAS_TRITON 时无条件 `from triton.experimental import gluon`；vllm_ascend/__init__.py 的 Gluon 兼容 stub 只把 `triton.experimental.gluon(.language)` 叶子模块塞进 sys.modules，未创建父模块 `triton.experimental`——Python 先解析父模块故仍抛 `ModuleNotFoundError`。架构相关：triton-ascend 3.2.1 在 x86_64 依赖 triton==3.2.0（无 experimental 包），arm 依赖 triton==3.5.0（含真实包）掩盖了 stub 不完整。

## 弯路与级联

- 判别要点：`import vllm_ascend` 后 `'triton.experimental' in sys.modules == False` 而 `'triton.experimental.gluon' == True`——问题不是插件未执行，是模块层级不完整。
- 易混项：#7359/#6737（标准 triton 安装覆盖/禁用 Ascend 后端）是不同问题；评论#2 给出不含 vllm-ascend 的最小复现。
- CI 盲区：只有 aarch64 NPU runner + amd64 CPU-only runner，arm 依赖集自带 experimental 包，x86_64 失败未被捕获。
