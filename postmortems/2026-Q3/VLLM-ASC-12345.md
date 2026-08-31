# VLLM-ASC-12345: DeepSeek V4 Pro A3/A5 长跑 host 内存泄漏→OOM（CANN-nnopbase sas_metadata AICPU kernel TilingKey host buffer 不驱逐）

> 源是结构化 GitHub issue 线程（9 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/12345
**根因确认**：评论 @linfeng-yuan（2026-07-28）——CANN-nnopbase host mem buffer 按 TilingKey 分配不驱逐（仅 AICPU kernel），CANN-9.1.0 修复
**时间**：2026-07-18 ~ 2026-08-31
**框架/版本**：DeepSeek V4 Pro；CANN < 9.1.0（9.1.0 修复）；报告方未提供 vllm-ascend 具体版本
**平台**：Ascend A3 / A5
**category**：interrupt
**investigation_quality**：medium（maintainer 定位根因明确；报告方未回验升级修复，issue 以 wait-feedback→stale→completed 关闭）

## 结构化 case

`postmortems/inbox/VLLM-ASC-12345.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

CANN-nnopbase 为每个 TilingKey 为 `sas_metadata` kernel 分配 host 内存 buffer 且不驱逐（仅 AICPU kernel 路径触发）；q_lens × kv_lens 组合随请求增长 → host 内存持续消耗，PD 分离与合部两种部署模式均复现，长跑后 OOM/服务不稳定。CANN-9.1.0 修复。

## 弯路与级联

- **泄漏面一度不明**：报告方初始不确定是 device 还是 host 内存，被要求补显存/内存曲线；maintainer 直接定位为 host 泄漏（sas_metadata AICPU kernel）。
- **与 device OOM 类 case 的区分**：13688（recompute 展开 61GB）、12989/9596（event 资源不足）、11343（KV cache 不释放，端口错位）均为 device 侧根因——本 case 泄漏面在 host，fix 是 CANN 升级而非 vllm-ascend 侧调整。
