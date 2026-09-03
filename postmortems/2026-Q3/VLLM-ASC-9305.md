# VLLM-ASC-9305: v0.20.2 启动报 ModuleNotFoundError: No module named 'vllm.v1.attention.backends.mla.prefill'——vllm 与 vllm-ascend 版本错配（按 vllm-main-verified.commit 对齐解决）

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest sed-g2 批次 2 产出（人工筛出的高质量 closed issues），进 inbox 待 groom 分诊。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/9305
**fix 跟踪**：无独立 fix PR——非代码 bug，维护者（zhaomingyu13）结论 = vllm 与 vllm-ascend 版本错配，按 vllm-ascend/.github/vllm-main-verified.commit（或 vllm-release-tag.commit）对齐重建
**框架/平台**：vllm-ascend 0.19.1rc2.dev75（git 5385230a8）/ vLLM 0.20.2；镜像 quay.io/ascend/vllm-ascend:v0.20.2rc1 同现（Qwen3.5-9B）
**category**：interrupt
**investigation_quality**：medium（维护者定论版本错配 + 用户 commit 对齐实测解决；错配根因=随手挑 commit 组合所致）
**verification**：upstream-maintainer-confirmed（zhaomingyu13 维护者 2026-07-29 明确 resolution：版本对齐；无 fix PR）
**novelty**：variant_of VLLM-ASC-11208——同"ModuleNotFoundError at 启动= vllm×vllm-ascend 版本错配/适配差"族；增量=11208 缺 expert_map_manager（模型适配缺失），本条缺 vllm.v1.attention.backends.mla.prefill（vllm-ascend 与 vllm 版本错配），同属版本对齐修复、不同缺失模块

## 现象摘要

vllm-ascend 0.19.1rc2.dev75（git 5385230a8，2026-05-18 构建）配 vLLM 0.20.2 启动即报：

```
ModuleNotFoundError: No module named 'vllm.v1.attention.backends.mla.prefill'
```

- 用户当时"随手挑了一个 commit"，发现 vllm-ascend@8f5962ba(05-19) 与 vllm@0d4d334(05-15) **双侧版本错配**；换 commit 组合（vllm-ascend@a45cd 05-16 + vllm@bc150f 05-05）后解决。
- 官方镜像 quay.io/ascend/vllm-ascend:v0.20.2rc1 + Qwen3.5-9B 也报同错（镜像内 vllm/vllm-ascend 组合不对齐的同类案例）。
- 结论：非业务 bug，属环境版本错配。

## 一句话根因

vllm 与 vllm-ascend 版本未按官方校验组合对齐：vllm-ascend 构建/安装针对的 vLLM commit 与运行时 vllm 不一致，vllm.v1.attention.backends.mla.prefill 等模块在错配版本中不存在 → import 阶段 ModuleNotFoundError、服务启动失败。官方校验组合记录在 vllm-ascend 仓库 `.github/vllm-main-verified.commit`（main 线）与 `.github/vllm-release-tag.commit`（release 线）。

## fix

按 **vllm-ascend/.github/vllm-main-verified.commit**（或 vllm-release-tag.commit）对齐 vllm 与 vllm-ascend 版本重建/换镜像；不随意组合 commit。issue 2026-08-06 关闭。

## 建议 triage 路由症状

现有 inference_interrupt 的 `ModuleNotFoundError` + 启动失败类已覆盖，无需新增（缺失模块名可作 fallback 特征但不要求 triage 路由）。
