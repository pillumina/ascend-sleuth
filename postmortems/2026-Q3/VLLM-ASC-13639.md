# VLLM-ASC-13639 —— MRV2 FullGraph × speculative decoding hang（update_stream 未统一 → fullgraph 死锁）

## 原文见

- https://github.com/vllm-project/vllm-ascend/issues/13639（[Bug]: Speculative decoding hangs in FullGraph mode (MRV2)，state=COMPLETED）
- 修复：https://github.com/vllm-project/vllm-ascend/pull/13600（[BugFix][MRV2] Unify update_stream across main and draft to fix fullgraph deadlock，merged）
- S2 replay 素材（本地留存，不随 repo 提交）：`.s2-replay/13639.md`（issue 现象）、`.s2-replay/13639.result.yaml`（subagent 盲测）
- 校准 ground truth：`eval/s2/vllm-ascend.yaml` issue 13639 `expected.resolution`

## 根因摘要

MRV2（vllm_ascend/worker/v2 Model Runner V2）FullGraph 图模式下开启 speculative decoding 时，
main 与 draft 模型图的**参数更新流（update_stream）未统一** → FULL 全图捕获/回放下 main/draft 的
流/事件同步关系不被满足 → **fullgraph 死锁**：decode worker 采样步永不返回，EngineCore 经
multiprocess executor 报 `TimeoutError: RPC call to sample_tokens timed out`，随后 executor shutdown
等待 worker exit（count=8）。

修复 = PR #13600 统一 main/draft 的 update_stream（code-patch，升级含该 PR 的版本）。

## 为什么补这条 case（S2 覆盖缺口）

库中该 namespace **无任何 MRV2 / FullGraph / update_stream / sample_tokens-RPC-timeout 签名 case**
（盲测 `tier2_hit=false`，与库大小无关）。盲测 agent 只判到"FULL×spec 非覆盖组合"家族并误判为
**不支持组合**（`root_cause_ok=false` 诚实标注）——实际组合受支持、死锁根因在 update_stream 分歧。
盲测会误判的组合，知识库必须有明确 case 指向真根因，并在 diagnosis 中加入判别步防后人重蹈。

## novelty（pre-triage，groom 复核）

**new_pattern**（见 `VLLM-ASC-13639.case.yaml` 头注证据）：
- knowledge 全库无 update_stream/fullgraph 签名，机制（main/draft 图参数更新流同步）与修复面无任何重叠 case
- 近邻判别：14871 = spec×recompute_scheduler 的 AttributeError 崩溃（PD 分离 recompute 场景，main2main 属性同步缺口）；13710 = DCP+MTP slot_mapping 256/260 shape 崩溃（pcp_utils 空段）——均崩溃非 hang、机制/签名不同

## triage 路由（needs-review：建议随 case PR 补 inference 侧 hang 正则）

**现状缺口**：inference_interrupt 分支现有正则不含独立词 `hang`/`stuck`（`\bhang\b` 只在
training_interrupt 分支），且本签名的日志 token 是 `TimeoutError`/`timed out`——都不是带词界的独立
词 `timeout`，`\btimeout\b` 匹配不到。实测：用户在 issue 里描述"Speculative decoding **hangs** in
FullGraph mode"时，能词法命中的只有 training 分支的 `\bhang\b`（会误导到 training 侧）；原始日志
签名本身整段不命中任何分支正则 → 依赖 diagnose 的**语义路由兜底**（盲测 agent 即如此路由到
inference/vllm-ascend interrupt，`routing_ok: true`），但没有正则可复现。

**建议（随本 case PR 一并提交 structure 部分，人审确认）**：给 inference_interrupt 分支补
推理侧 hang/死锁/挂起签名，如 `\bhang\b|\bstuck\b|挂起|死锁` 或 `RPC call to .* timed out`——
避免推理侧 hang 被 training 分支的 `\bhang\b` 误吸。拿不准归属 → 标 `needs-review`，groom 定夺。
