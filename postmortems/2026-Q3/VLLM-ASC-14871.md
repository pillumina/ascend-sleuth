# VLLM-ASC-14871: PD 分离 decode 开 recompute_scheduler + speculative decoding 首请求崩溃（Request 缺 async_tokens_to_discard）

> 源是结构化 GitHub issue 线程 + 已合并 fix PR——按 to-postmortem 优化②，只写指针，不重写。
> 批量导入草稿：sed-g3（2026-09），周审转正。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/14871
**修复 PR**：https://github.com/vllm-project/vllm-ascend/pull/14504（[Misc][Core][P/D] Add main2main 0.27.1 for Recompute scheduler，merged 2026-08-25，merge_commit 07482eb3）
**时间**：issue created 2026-08-25 / closed 2026-08-31（state_reason=completed，维护者 bowgneo 关闭，报者确认 #14504 修复）
**框架**：vllm-ascend（推理侧，PD 分离 decode 的 recompute scheduler）——issue 环境：vLLM v0.27.1 + vllm-ascend 0.1.dev4715+g6e506867c（main @ dade7da62，nightly-main-a3 镜像）
**平台**：Atlas 800I A3（Ascend 910_93，16 chips 单机 + 两节点 1P1D 验证）——纯代码级缺陷，跨平台适用
**category**：interrupt
**investigation_quality**：high
**verification**：upstream-fix-merged（detail：fix PR #14504）

## 现象（用户首帖摘要）

PD 分离部署：decode 节点同开 `recompute_scheduler_enable` 与 speculative decoding（`deepseek_mtp`/MTP，任意带 MTP head 模型可复现，合成随机权重模型亦可）。服务通过健康检查（`GET /v1/models` 200）后，第一个 `POST /v1/chat/completions` 即返回错误且所有 EngineCore 退出。V1、V2 model runner 崩溃完全相同（recompute scheduler 是 runner-agnostic core 代码）。

## 一句话根因

`vllm_ascend/core/recompute_scheduler.py:1088`（PR #12541 引入）在 `update_from_output` 里读 `request.async_tokens_to_discard`，但该属性在配对的上游 vLLM（v0.27.1 及当时 main）`Request` 类上不存在、仓库内无定义/setattr（全仓库唯一读取点）——main2main 同步缺口；spec-decode 请求每个 decode step 都填充 `scheduled_spec_token_ids`，and 链必然触达缺失属性 → 首请求 AttributeError。

## fix

升级 vllm-ascend 到含 PR #14504（main2main 0.27.1 for Recompute scheduler，merged 2026-08-25）的构建/后续版本。未升级前的规避：去掉 speculative decoding（issue 消融验证同一拓扑可正常服务）或关闭 recompute_scheduler_enable。

## 弯路与级联

- 无大弯路：报者直接给出完整根因（缺属性读取点 + 全仓库唯一引用核查 + V1/V2 双验证 + 去 spec decode 消融），维护者 close 后报者确认 #14504 修复。
- 级联提示：本崩溃是纯代码属性同步缺口，不是 MTP/算子/显存问题；与 VLLM-ASC-10784（Kimi-k2.5 decode 侧运行中 OOM：请求竞争触发 recompute，MoE shared-expert 展开内存异常，官方 known issue 无 PR/版本）是同一 recompute 功能下的**不同缺陷**——症状（首请求 AttributeError vs 运行中 OOM、`_moe_forward_shared` 61GB / batch 1024→508648）与 fix（#14504 vs 无）均不同，勿混判。

## 建议 quickly_check 信号

`async_tokens_to_discard` / `recompute_scheduler.py` / recompute_scheduler_enable + speculative/MTP 组合
