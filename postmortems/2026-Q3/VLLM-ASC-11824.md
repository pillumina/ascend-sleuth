# VLLM-ASC-11824: batch invariance 测试在 Ascend NPU 输出随 batch 波动（算子非确定性执行）——PR #11824 开启 use_deterministic_algorithms

> 源是 GitHub PR（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/pull/11824（[Ops][BugFix]，已合并 2026-07-13）
**fix 跟踪**：PR #11824 本体（vllm_ascend/batch_invariant.py 的 `override_envs_for_invariance()` 中调用 `torch.use_deterministic_algorithms(True, warn_only=True)`）
**时间**：2026-07-10 ~ 2026-07-13
**框架**：vllm-ascend（PR 标注 vLLM v0.23.0），batch invariance 测试用 Qwen3-30B
**平台**：A5-950（PR 实测；A3 未在线程验证）
**category**：precision
**investigation_quality**：medium（维护者修复 PR + 测试验证，但线程无逐项排查记录、无复现日志）
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（batch 2）

## 结构化 case

`postmortems/inbox/VLLM-ASC-11824.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

Ascend NPU 上算子默认非确定性执行，batch invariance 测试断言"同输入、不同 batch 输出一致"时结果随 batch 波动、测试失败；需在 `override_envs_for_invariance()` 中调用 `torch.use_deterministic_algorithms(True, warn_only=True)` 强制确定性执行才能通过。

## 弯路与级联

- 本线程是修复 PR 而非排查 issue，无弯路记录；signature 弱（无错误签名，只有行为词 determinism/batch invariance），fallback 用行为词检索。
- `warn_only=True` 意味着遇不可确定性算子只告警不抛错——修复只覆盖"能确定化的算子"，不会因不确定算子中断测试。
- 级联注意：batch invariance 是 CI 门禁，失败会阻塞合入/发布，但**不影响线上服务**——severity 判 benign，勿按服务故障处理。
