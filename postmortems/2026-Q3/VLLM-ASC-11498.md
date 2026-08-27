# VLLM-ASC-11498: dsv4-flash W4A8_MXFP4 allgatherEP 路径把 topk_weights 强转 float8 与 bool mask 相乘，启动即抛 Float8 promotion 不支持

> 源是结构化 GitHub issue 线程（7 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/11498
**fix 跟踪**：PR #11663（https://github.com/vllm-project/vllm-ascend/pull/11663，"[Ascend950][Bugfix]Fix allgatherEP MXFPW4A8 quantization"，merged 2026-07-10）；评论#2 Eric-dot 确认 "PR #11663 fixed"；issue 随后 wait-feedback → stale → bot 以 not_planned 自动关闭（不代表未修复）
**时间**：2026-07-06 ~ 2026-08-07（stale 关闭）
**框架**：vllm-ascend release/v0.23.0（0.19.1rc2.dev863+g79928c2ff）+ vLLM 0.23.0，DeepSeek-V4-Flash + dsv4-flash，--enable-expert-parallel，CANN 9.1.0
**平台**：A5-950（Ascend950PR ×8，TP4/EP）
**category**：interrupt
**investigation_quality**：high（精确栈定位到 token_dispatcher.py:393 `topk_weights = topk_weights * mask`，fix PR 直接合入）
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（batch 2，组 1）

## 结构化 case

`postmortems/inbox/VLLM-ASC-11498.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

Ascend950（A5）allgatherEP 的 W4A8_MXFP4 量化路径把 topk_weights 误强转为 float8，随后与 bool 类型 mask 相乘（`topk_weights = topk_weights * mask`），PyTorch 不支持 Float8×Bool 类型提升，`profile_run` 阶段即抛 `RuntimeError: Promotion for Float8 Types is not supported, attempted to promote Float8_e4m3fn and Bool`；MXFP 模式下应跳过 topk_weights 的 float8 cast。

## 弯路与级联

- **无弯路**：报错自解释、栈直接指向 token_dispatcher.py 的乘法行，评论者直接给出 fix PR。
- **关闭状态陷阱**：issue 以 `not_planned` 被 stale bot 自动关闭，但这是"14 天无反馈"的自动行为，并非"官方拒绝修复"——修复实际已通过 PR #11663 合入 0.23.0，判别时不要被 closed reason 误导。
- **作用域**：仅 A5（Ascend950）+ W4A8_MXFP4 量化 + allgatherEP（EP 通信）组合触发；启动即崩（profile_run 阶段），非运行期偶发。
