# VLLM-ASC-10944: GLM-5/5.1/5.2 w8a8 + expert parallel 拉起报 aclnnMoeDistributeDispatchV4 561000（HCCL QP 资源耗尽）

> 源是结构化 GitHub issue 线程（10 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/10944
**fix 跟踪**：无已合入 PR；官方在 issue #11394 跟踪 GLM 系列 EP 功能修复（未合入）；workaround（关闭 EP）多用户实测有效
**时间**：2026-06-25 ~ 2026-08-07（stale 关闭）
**框架**：vllm-ascend v0.21.0rc1（quay.io/ascend/vllm-ascend:v0.21.0rc1 镜像），CANN 9.0.0
**平台**：A2-910B（910B2C × 16 卡单机）
**category**：interrupt
**investigation_quality**：medium（维护者确认 workaround、错误码根因到 HCCL QP 资源层；修复未落地、无代码级根因）
**批量导入**：批次 2 组 4（2026-08）

## 一句话根因

GLM 系列 w8a8 开启 expert parallel 时，MoE dispatch（aclnnMoeDistributeDispatchV4）向 HCCL 申请通信 QP 资源超出 NPU 预算（EI0007 Resources are exhausted，sendCqDepth 32768），算子调用失败（561000），服务无法拉起；官方在 #11394 跟踪修复。

## 弯路与级联

- **workaround 先行**：Bu1bul 实测去掉 `--enable-expert-parallel` 即可，GLM5/5.1/5.2 通吃，linyu09-oss 确认——EP 是触发开关，不是模型/量化问题。
- **勿当配置笔误排查**：561000 + EI0007 + "Failed to allocate resource qp" 三连签名即指向 HCCL 通信资源分配，不必继续查 tiling/权重。
- **官方修复在跟踪中**：#11394 是 GLM 系列 EP 的修复跟踪，合入前 EP 场景只能靠 workaround；groom 后续应跟踪 #11394 合入版本回填 compat。
