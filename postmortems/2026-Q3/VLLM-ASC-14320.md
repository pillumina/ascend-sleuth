# VLLM-ASC-14320: DCP block_table 越界 k_cache 容量 → LightningIndexerQuant MTE invalid GM address

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/14320
**fix 跟踪**：最新 v0.26rc commit（作者验证 "Verified fixed in the latest v0.26rc commit"）；回归引入自 PR #12592（v0.26 PCP 移除）
**时间**：2026-08-15 ~ 2026-08-25
**框架/平台**：vllm-ascend releases/v0.26.0rc + torch 2.5.1(torch_npu) + CANN 9.1.0；A3 (910A3/HPU910a3)，GLM-5.2-w4a8 + DCP=8 + MTP + PD 分离
**category**：interrupt
**investigation_quality**：high
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（Phase B，第 2 批）

## 结构化 case

草稿：`postmortems/inbox/VLLM-ASC-14320.case.yaml`（Tier 2 入库前待 groom 分诊）。

## 一句话根因

v0.26 PCP-removal 重构（#12592）把 `_build_block_table_replicated_view` 的 `total_cp_size` 从 `pcp*dcp` 改为 `dcp`，DCP replicated block_table 的 block id 域超出单 rank k_cache 容量；LightningIndexerQuant 用越界 id 索引 k_cache（instrumented 打印确认 `bt_max_idx >= k_cache_cap`，OVERFLOW=True）→ MTE invalid GM address（EZ9999 / 507015）→ decode EngineCore 崩溃。

## 弯路与级联

- 先排查 seq_lens 负值（`aseq_q`/`aseq_k` has_neg=False 排除）；叠加 PR #14114（MTP slot_mapping）与 #14177（SFA clamp_min seq_lens-offset）后仍复现，证明是独立的 block_table index overflow 根因。
- v0.23 同配置不复现 → 回归指纹锁定 v0.26。
- 级联噪声：D0 head 侧 `corrupted size vs. prev_size`（glibc heap corruption）与 EngineDeadError 是崩溃后级联；`npuSynchronizeDevice ... 507015` 报错是同步浮出点，fault kernel=LightningIndexerQuant 才是定位锚。
- 复现窗口：num=4/300 不崩、num=1000 cc=64 rr=1.8 在 ~400-532 请求崩溃（load-duration 依赖）。
