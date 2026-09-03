# 原文见：https://github.com/vllm-project/vllm-ascend/issues/10998（closed COMPLETED，state_reason=COMPLETED；fix PR #11131 merged）
# 沉淀：S2 replay 校准缺口（.s2-replay/10998 + 10998.result.yaml，2026-09-03：tier2_hit=false、root_cause_ok=true）→ inbox 草稿
# 框架：vllm-ascend（推理侧，Ascend NPU）｜category：interrupt｜pre-triage：new_pattern

# 根因摘要

- 现象：Qwen3.6-27B hybrid KV（多 cache group）+ layerwise PD disagg + mooncake store 长稳压测偶发报错。
  worker 日志（mooncake_backend.py）：
  `Failed to get 3 keys out of 6. error_codes=[-704]. Check key existence and memory state.`；
  key 明细同批跨 group 0/1/2/3（key 形如 `...@group:N@cache_role:kv@cache_family:default@<hash>`），
  `result=[26738688, 26738688, -704, -704, -704, 26738688]`——失败恰为 group 1/2/3 的 key（-704=key not found），group 0 全命中。
- 根因：layerwise connector（MooncakeLayerwiseConnector）+ mooncake store（AscendStoreConnector/backend=mooncake）
  路径未按 cache group 分别构造命中集合取块，组 key 请求集合与 store 实际存在状态错配 → 组级 get 部分失败。
- fix：PR #11131（merged，校准 resolution：「按组命中集合取块」）——升级含该 PR 的 vllm-ascend 构建后长稳复测。
- 价值：知识库覆盖缺口填补（S2 replay tier2_hit=false）——新形态「按组 get 部分失败 -704」，
  区别于 mooncake 族既有成员：put -800（9398/7792）、从不 Put（8808）、lazy-init AssertionError（11459）、
  传输 segfault（10532）、SFA spec 拆组 OOB 崩溃（13934）。
- 产出：`postmortems/inbox/VLLM-ASC-10998.case.yaml`（完整 case 草稿，待 groom 周审分诊后转正）
