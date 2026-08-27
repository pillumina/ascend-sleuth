# VLLM-ASC-13710: DCP+MTP slot_mapping shape mismatch（256 vs 260）——切分空段漏加 draft

> 源是结构化 GitHub issue 线程（5 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/13710
**fix 跟踪**：PR #14025（https://github.com/vllm-project/vllm-ascend/pull/14025，pcp_utils→dcp_utils 重构 + 空段保护）；评论#4 验证 "Verified fixed in the latest v0.26rc commit"
**时间**：2026-08-06 ~ 2026-08-25
**框架**：vllm-ascend 0.1.dev100+g1c87c58a1（v0.23 分支）+ vllm 0.23.1.dev30 + CANN 9.0.1 + torch_npu 2.10.0.post2，GLM-5.2 w4a8
**平台**：A3-910C（2 pod × 8 NPU，DCP=8）
**category**：interrupt
**investigation_quality**：high（长/短 prompt 边界对照 + 崩溃状态 dump 排除 OOM + 根因级分析 + 官方修复与验证）
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md

## 结构化 case

`postmortems/inbox/VLLM-ASC-13710.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

`pcp_utils.py:generate_pcp_mtp_input` 用 `np.array_split` 按 `cu_num_tokens` 切分请求时出现空段：空段请求的 `req_indices_split[i]` 没执行 MTP draft 追加（4 个元素）而 `positions_split[i]` 追加了 → `req_indices_mtp`(256) 与 `positions_mtp`(260) 长度不一致（差 4 = 一个请求的 draft 追加量）→ `block_table.py:272` 的 `slot_mapping.cpu[:256]` 被赋形状 260 的结果 → RuntimeError。PR #14025 修复。

## 弯路与级联

- **弯路（边界对照）**：长 prompt（~26k tokens, 200-220 blocks）+ 高并发（cc=102）触发、短 prompt（~20k, 195 blocks, cc=96）不触发 → 先怀疑并发/显存上限，崩溃 dump 显示 KV usage 6.7%、running=26（未超 max_num_seqs=32）→ 排除 OOM；差 4 的 shape 差值正好等于一个请求的 draft 追加量 → 定位到切分空段漏加 draft。
- **误导性报错**：崩溃后的 `corrupted size vs. prev_size`（glibc 堆损坏）是 worker 异常退出的**症状而非根因**；同拓扑的 #13934（v0.26 Mooncake IndexError）是另一条代码路径，勿混淆。
