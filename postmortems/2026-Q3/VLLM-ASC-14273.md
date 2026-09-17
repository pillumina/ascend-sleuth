# VLLM-ASC-14273: CANN 9.1.0 下 DeepSeek-V4 PD 分离输出损坏（NaN → 507035 → EngineDead）——cann_ops_transformer 激活 MegaMoe 路径暴露 prefill buffer sizing 违约

> 源是结构化 GitHub issue（**维护者给出根因 + 四格 A/B 矩阵**，含强制 legacy 路径与提容量两组对照），
> 按 to-postmortem 的「只写指针 + 不重写」口径记录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/14273
**修复**：https://github.com/vllm-project/vllm-ascend/pull/14358 、 https://github.com/vllm-project/vllm-ascend/pull/14439
**框架/平台**：vllm-ascend `releases/v0.25.1rc`(60ec261) + CANN **9.1.0** + torch-npu 2.10.0.post4 + triton-ascend 3.2.2；DeepSeek-V4-Flash-W8A8，PD 分离 + MooncakeConnector（mooncake_protocol=ascend）+ DSpark 投机解码 5 tokens
**category**：precision
**investigation_quality**：high（维护者根因 + A/B 矩阵）
**verification**：upstream-maintainer-confirmed
**novelty**：variant_of VLLM-ASC-14265 —— **同一个 buffer sizing 违约**，两种表现：14265 是「超容 → 溢出产错 → 投机接受率劣化」（静默，看指标）；本条是「同因在 CANN 9.1 下被激活 → NaN → 全 -1 → 507035 → EngineDead」（显式崩溃，看签名）。

## 现象

CANN 9.1.0 镜像：`content: null`、`reasoning_content` 多语言乱码、`finish_reason: length`；
**同模型同代码同参数换 CANN 9.0.1 即正确**；两次都 HTTP 200、无 traceback、无 Mooncake 传输错误。
显式失效序列：`P 返回 token 0` → `D target logits 含 904960 NaN` → token 全 `-1` → `NPU error 507035` → `EngineDeadError`。

## 根因（维护者）

CANN 9.1 是**触发**：它安装 `cann_ops_transformer`，使 `_MEGA_MOE_SUPPORTED` 由 false 变 true →
同一份代码在原先走 legacy `dispatch_ffn_combine` 的场景改选 **CANN MegaMoe** →
暴露 buffer sizing 违约：`enable_prefill_mc2=false` 时容量仍按 decode graph 尺寸分配
（复现态 **32 tokens/rank**、MC2 容量 128），却把 477-token 的 eager prefill batch 送给 MegaMoe，
违反算子文档的 `bs <= num_max_tokens_per_rank`。CANN 9.0.1 缺该组件 → 走 legacy 路径 → 隐藏该 bug。

## A/B 矩阵（维护者复现）

| 环境/路径 | 结果 |
|---|---|
| CANN 9.1 + 自动 MegaMoe + 32 tokens/rank buffer | 复现损坏与 EngineDead |
| CANN 9.1 + 强制 legacy `dispatch_ffn_combine` | 3×并发 16，48/48 HTTP 200 |
| CANN 9.1 + 原生 MegaMoe、容量提到 2048 tokens/rank | 48/48 通过 |
| CANN 9.1 + 32 tokens/rank 但超容 prefill 路由到 ALLTOALL | 48/48 通过 |

## fix

升级到含 PR #14358 / #14439 的版本（buffer sizing + fail-fast 校验）；应急规避任选其一：
强制 legacy 路径 / 提高 MegaMoe 容量至 ≥ prefill batch / P 节点开 `enable_prefill_mc2=true`。
上线前把「容量 ≥ prefill batch」列为检查项（容量口径见词条 `mc2-megamoe-token-capacity`）。

## 残余风险

- 算子侧**不会**在容量违约时给出清晰错误（表现为无效输出 + 迟到的 `507035`），所以"输出垃圾"类现场必须主动核对容量，不能等报错；
- 与 DP token 不均匀（#14304/#14305）是同栈上的另一条修复线，不要混判。
