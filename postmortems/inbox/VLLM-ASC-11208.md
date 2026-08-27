# VLLM-ASC-11208: 双机 A2 按官方教程部署 GLM5.2 启动报 ModuleNotFoundError（v0.22.1rc 未适配 GLM5.2）

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/11208
**fix 跟踪**：无独立修复 PR——官方结论为版本适配差异：需 vLLM v0.23.0 + 含 PR #10441 的 vllm-ascend main（另参考 PR #11065、issue #10610）
**时间**：2026-06-30 ~ 2026-08-07（stale 关闭）
**框架**：vllm-ascend v0.22.1rc（失败）→ vLLM v0.23.0 + vllm-ascend main（成功）
**平台**：A2 (910B) 双机
**category**：interrupt
**investigation_quality**：medium（官方确认版本组合方案；用户未回测成功闭环，stale 关闭）
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（batch 2）

## 结构化 case

`postmortems/inbox/VLLM-ASC-11208.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

v0.22.1rc（及更早）的 vllm-ascend 未适配 GLM5.2，缺少 `vllm.model_executor.layers.fused_moe.expert_map_manager` 模块，模型加载 import 阶段抛 `ModuleNotFoundError`、服务启动失败；GLM5.2 支持需 vLLM v0.23.0 + 至少含 PR #10441 的 vllm-ascend main。

## 弯路与级联

- **弯路（换版本引入次级错误）**：用户先切到 v0.22.1rc 镜像，ModuleNotFoundError 消失，但出现**模型键值错误**——这是版本错配下的次级现象，不是独立根因；正确组合是 vLLM v0.23.0 + vllm-ascend main（含 PR #10441），不要停留在 0.22.x 上排查键值错误。
- **镜像陷阱**：quay.io/ascend/vllm-ascend:glm5.2 标签镜像并不保证含 PR #10441，需确认构建镜像所用的 commit；main 分支源码构建最稳。
- 线程最终无人回测成功闭环，stale 关闭——但结论（评论#1 xw1216 + 自动回复#8）社区确认一致。
