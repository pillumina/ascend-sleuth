# VLLM-ASC-9056: vLLM v0.20.1 + 旧 vllm-ascend main 拉起即崩——BalanceScheduler 未适配 hash_block_size

> 源是结构化 GitHub issue 线程（3 条评论），按 to-postmortem 优化——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/9056
**fix 跟踪**：PR #9155（https://github.com/vllm-project/vllm-ascend/pull/9155，[CI] Main2main 0514，merged 2026-05-14 main；同步上游 vLLM v0.20.1 接口，含 `patch_balance_schedule.py` 适配）
**时间**：2026-05-11（报）～ 2026-05-21（closed completed）
**框架**：vllm v0.20.1 + vllm-ascend main@4d51588（旧于 main2main 0514）；GLM-5-w4a8，DP2 TP8 EP + MTP
**平台**：issue 未声明机型
**category**：interrupt
**investigation_quality**：medium（栈到行 + 维护者确认 main2main 引入 + fix PR merged 后关闭；无消融复现）
**批量导入**：sed-g3（2026-09）
**pre-triage**：variant_of VLLM-ASC-8336（父 case 已入库；同族=balance scheduling patch × 配套 vLLM 版本 API 漂移 → EngineCore 启动崩溃）

## 结构化 case

`postmortems/inbox/VLLM-ASC-9056.case.yaml`（Tier 2 候选，待 groom 审）

## 现象摘要

vllm v0.20.1 + vllm-ascend main@4d51588 拉起 GLM-5-w4a8（DP2 TP8 + MTP）：EngineCore DP1 启动阶段即崩，栈尾 `patch_balance_schedule.py:696`（`super().__init__(*args, **kwargs)`）→ `TypeError: BalanceScheduler.__init__() got an unexpected keyword argument 'hash_block_size'`。维护者 MengqingCao：main2main 引入；Potabk 指向 PR #9155。

## 一句话根因

上游 vLLM v0.20.1 给 `Scheduler.__init__` 新增 `hash_block_size` 参数，旧 vllm-ascend main 的 balance scheduling patch（`BalanceScheduler.__init__` 签名）未跟上 → 调度器初始化透传新参数报 TypeError，启动即挂。PR #9155（Main2main 0514）同步适配修复——纯版本配套缺口，与模型/量化无关。

## fix

vllm-ascend 升级/同步到含 PR #9155 的构建，与配套 vLLM v0.20.1 对齐。同族排查提示：patch×配套 vLLM 版本漂移还有 VLLM-ASC-8336（WAITING_FOR_FSM 枚举成员缺）——不同漂移点勿套用。

## verification

**upstream-fix-merged**（fix PR #9155，merged 2026-05-14；报者确认合并即修复并关闭）
