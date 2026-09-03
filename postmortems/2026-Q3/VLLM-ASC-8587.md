# VLLM-ASC-8587: DS-V3.2-w4a8 双机 DP2×TP8 EP + FULL_DECODE_ONLY + deepseek_mtp + layer_sharding 压测并发=4 崩——graph replay 内 aclnnKvRmsNormRopeCache 同步 rtMemcpy（107030），升级 ≥0.18 并去掉 layer_sharding

> 源是结构化 GitHub issue 线程（5 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/8587
**fix 跟踪**：无独立 fix PR；维护者 Nagisa125 判定混合配置（FULL_DECODE_ONLY + layer_sharding）问题（旧版未做断言），建议 v0.18.0 + 关闭 layer_sharding；报者 lingxling 升级 v0.18.0 并去掉 layer_sharding 后不再复现（completed 2026-06-05）。后续关联 #10630 / #15509（cross-referenced，后续版本治理）
**时间**：2026-04-22 ~ 2026-06-05（completed）
**框架**：vllm-ascend 0.13.0 + vLLM 0.13.0（DeepSeek-V3.2 w4a8 QuaRot，--quantization ascend）
**平台**：Ascend 910B ×16（A2-910B，2 节点 ×8 卡，ROCE 组网）
**category**：interrupt（运行期压测崩溃，node1 全 8 worker 同时崩）
**investigation_quality**：medium（完整崩溃栈 + 可复现矩阵 cc1/2 过 cc4 崩 + 去 FULL_DECODE_ONLY 消除 + 维护者判定 layer_sharding 混用；未做代码级定位）
**verification**：upstream-maintainer-confirmed（维护者 Nagisa125 建议 + 报者 v0.18.0 关 layer_sharding 实测解决）
**pre-triage**：new_pattern（现库无 layer_sharding×FULL_DECODE_ONLY×MTP 图模式崩溃 case；邻近 VLLM-ASC-12983 为 310P 图模式 107030，触发面/根因不同；与 8646 同为 'rtMemcpy 107030 in capture' 家族但配置组合与规避不同）

## 现象摘要

- 双机 16 卡（910B）DS-V3.2-w4a8（QuaRot，--quantization ascend），DP2×TP8 + EP + FULL_DECODE_ONLY + deepseek_mtp（num_speculative_tokens=3）+ `--additional-config '{"layer_sharding": ["q_b_proj", "o_proj"]}'`。
- vllm bench：cc=4（Input=1024 Output=128, 20 prompts）时 node1 全部 8 个 worker 同时崩，API server 对后续请求全 500；cc=1/2 正常，完全可复现。
- 根错：`EE9999: rtMemcpy execution failed, reason=the current capture mode does not support this operation / synchronized memcpy failed, kind=1, runtime result=107030 / The DDR address of the MTE instruction is out of range`。
- 崩溃栈：sample_tokens → propose_draft_token_ids（MTP）→ drafter._propose → deepseek_mtp forward → acl_graph.__call__（replay）→ aclnnKvRmsNormRopeCache → rtMemcpy（107030）。runtime 日志时间戳显示错误记录于 warmup capture 期、推断期才浮出（延迟上报）。
- 去 `--compilation-config FULL_DECODE_ONLY` 即不崩。
- 解决：切 v0.18.0 + 去掉 layer_sharding（报者实测 bug 消失）。

## 一句话根因

FULL_DECODE_ONLY（ACL graph）图模式 + MTP 投机解码 + layer_sharding 的混合配置在 vllm-ascend 0.13 未被支持/未做断言：graph replay 内 aclnnKvRmsNormRopeCache 发起同步 rtMemcpy，ACL graph capture/replay 模式不允许 → runtime 107030/107027 崩溃（cc≥4 触发，node1 整组 worker 同崩）。维护者判定 layer_sharding 混用是问题源；升级 v0.18.0（含断言/限制）+ 去掉 layer_sharding 后解决。

## fix

- 升级到 vllm-ascend ≥0.18.0（0.18.0 实测）。
- 去掉 `--additional-config '{"layer_sharding": [...]}'`（该配置与 FULL_DECODE_ONLY/MTP 混用不被支持）。
- 若仍崩，再排查显存（维护者提示可降 gpu-memory-utilization 排除容量因素）。

## 弯路与级联

- 弯路：报者初判"rtMemcpy/copy 是根因"——维护者 yiz-liu 指出 graph 是静态的、runtime 不会凭空加 copy，更像前方另有错误；最终定位为 layer_sharding 混用配置。
- 级联：node1 全 8 worker 同时崩（collective 同步点级联）；HTTP 500 为进程崩溃后的对外表现。
