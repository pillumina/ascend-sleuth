# VLLM-ASC-9503 —— A3 双机 GLM-5.1-w8a8 MoeDistributeDispatchV2 算子错误（RoCE 组网兼容性）

- **来源**：[vllm-ascend issue #9503](https://github.com/vllm-project/vllm-ascend/issues/9503)（triaged，stale 后关闭）
- **导入管道**：issue-ingest skill 第二轮评估（triaged 池）
- **状态**：draft（postmortems/inbox/ 待审）

## 现象

A3 双机部署 GLM-5.1-w8a8（0.19.1rc1），报 **MoeDistributeDispatchV2 算子错误**。

## 根因

维护者确认：**MoeDistributeDispatchV2 在 RoCE 组网下存在已知兼容性问题**（旧版本触发）。

## 处理

升级 vllm-ascend 到 **0.20.2rc1 或更新版本**（ZYang6263 确认新版本可解决）。

## 评估

- 可沉淀：根因定论（维护者确认 RoCE 兼容性）+ fix 明确（升级 0.20.2rc1+）
- **与已有 case 同域**：VLLM-ASC-12461（507057 MTE 越界，MoE 通信算子 ROCE 触发）——同域（MoE 通信）不同根因（兼容性 vs 越界），groom 预分诊确认 new 还是 variant_of

## 同批评估（第二轮，4 条）

| issue | 判定 | 理由 |
|---|---|---|
| #9503 | ✅ 沉淀 | 根因定论（RoCE 兼容性）+ fix 明确（升级 0.20.2rc1+）|
| #6572 | ⏭ 跳过 | A2 TP8 OOM，用户未回执、无根因定论 |
| #10521 | ⏭ 跳过 | 310p 图捕获硬件限制等待新驱动（等待型）|
| #10082 | ⏭ 跳过 | 图模式性能咨询已解答（咨询类非故障）|
