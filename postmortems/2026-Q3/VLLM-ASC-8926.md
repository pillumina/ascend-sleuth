# VLLM-ASC-8926: DeepSeek-V3.1-w4a8-mtp-QuaRot + PCP2 投机解码 worker 崩溃——seq_lens_cpu=None 无守卫赋值

> 源是结构化 GitHub issue 线程（3 条评论），按 to-postmortem 优化——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/8926
**fix 跟踪**：PR #8749（https://github.com/vllm-project/vllm-ascend/pull/8749，[Performance] adapter dcp pcp full graph and async schedule spec，merged 2026-05-08 main；`vllm_ascend/spec_decode/eagle_proposer.py` 双字段 None 守卫）
**时间**：2026-05-07（报）～ 2026-05-08（closed completed）
**框架**：vllm-ascend 0.19.0rc1（标题）/ 0.19.1rc1 镜像（env）；DeepSeek-V3.1-w4a8-mtp-QuaRot，TP8 + PCP2 + EP + deepseek_mtp
**平台**：A2-910B（A2 × 2）
**category**：interrupt
**investigation_quality**：high（栈到行 + fix patch 明确机制 + 合入当日双人验证）
**批量导入**：sed-g3（2026-09）
**pre-triage**：variant_of VLLM-ASC-13710（父 case 已入库；同族=CP(PCP/DCP)×MTP×async spec worker 崩溃，机制/修复不同）

## 结构化 case

`postmortems/inbox/VLLM-ASC-8926.case.yaml`（Tier 2 候选，待 groom 审）

## 现象摘要

A2×2 部署 DSV3.1-w4a8-mtp-QuaRot（TP8、PCP2、EP、async scheduling、MTP num_spec=3），`Worker_PCP0_TP4_EP4` 在请求进入投机采样时崩溃：`model_runner_v1.py sample_tokens → propose_draft_token_ids → eagle_proposer._propose → set_inputs_first_pass` 内 `cad.seq_lens_cpu[-num_prefill_reqs:] = seq_lens_p` → `TypeError: 'NoneType' object does not support item assignment`。

## 一句话根因

async spec 模式下 model runner 只填充上游 canonical 字段 `_seq_lens_cpu`（来自 `optimistic_seq_lens_cpu`），Ascend 子类字段 `seq_lens_cpu` 保持 None；`eagle_proposer.set_inputs_first_pass`（PCP prefill worker 有 prefill 请求时）无守卫对 None 切片赋值 → TypeError，worker 崩溃。PR #8749 加双字段 None 守卫并同步、优先读上游 canonical 字段。

## fix

升级到含 PR #8749 的构建（merged 2026-05-08 main）；issue 内双人验证通过，closed completed。

## verification

**upstream-fix-merged**（fix PR #8749；`Verified, it resolves my issue`）
