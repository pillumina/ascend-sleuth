# VLLM-ASC-13934: v0.26 SFA spec 拆分 Mooncake transfer group，vllm 侧 block_ids 索引未跟上致越界崩溃

> 源是结构化 GitHub issue 线程（12 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/13934
**fix 跟踪**：PR #13968（releases/v0.26.0 backport）+ PR #13965（main）；评论#11 验证 "Verified fixed in the latest v0.26rc commit"
**时间**：2026-08-10 ~ 2026-08-25
**框架**：vllm-ascend 0.19.1rc2.dev1317（releases/v0.26.0rc）+ vllm 0.23.1rc1.dev1291 + CANN 9.0.1 + torch_npu 2.10.0.post2，GLM-5.2 w4a8
**平台**：A3-910C（2 pod × 8 NPU，DCP=8）
**category**：interrupt
**investigation_quality**：high（maintainer 确认根因 + 报告方 6 轮修复尝试穷举 + 20k-40k 压测稳定复现 306/1000 + plog 深层定位 103900 + 修复后验证）
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md

## 结构化 case

`postmortems/inbox/VLLM-ASC-13934.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

v0.26 新增 `AscendSFAIndexerCacheSpec`（`vllm_ascend/core/kv_cache_interface.py:98`），`_build_kv_group2layeridx` 把 1 个 KV cache group 按 spec 拆成 2 个 Mooncake transfer group（SFA indexer / MLA attention），而 vllm 侧 `remote_block_ids` 仍按 1 组索引，D 侧 `_get_kv_split_metadata` 访问 `remote_block_ids[1]` 越界 → decode worker 崩溃。残留问题：SFA(scale=8) 与 MLA(scale=1) 共用物理 metadata slot，MLA 误用 SFA scale 把 block id 扩 8 倍 → 未注册地址 → HcclBatchGet 103900 传输失败与乱码。

## 弯路与级联

- **弯路（6 轮失败修复，最有价值的反例集）**：跳过越界 group → TPOT 134ms（spec decode 失效）；所有 group 回退 `remote_block_ids[0]` → 乱码（0/1 交替）；`kv_cache_group_id` 映射 → AttributeError（group_spec 是 int 非 dict）；修解包 → 乱码（585858）；统一 idx 0 → 乱码；禁用 spec 拆分 → 乱码（0.0.0.0）。**核心矛盾：SFA 与 MLA block 布局不同，任何共用 block_ids 的修复都损坏精度**——正确方向是 vllm 侧按 spec 拆分 block_ids 或隔离各 spec 的 metadata。
- **级联误导**：#13968 修复 IndexError 后压测 21 分钟出现 HcclBatchGet ErrorNo:103900 + 乱码，一度被当成独立传输问题（plog 深层链路 BatchGet AICPU launch failed）；实际是 SFA/MLA 共用物理 metadata slot 的残留 bug（评论#9 确认），更新后的 #13968/#13965 一并隔离布局解决。
- **关联**：#13710 是同一 DCP=8+MTP 拓扑下 v0.23 的另一条崩溃路径（slot mapping shape mismatch），非本 case。
