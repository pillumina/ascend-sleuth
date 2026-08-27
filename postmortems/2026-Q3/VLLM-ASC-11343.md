# VLLM-ASC-11343: PD 分离 + 多节点 PP，D 侧 ZMQ 端口映射用 P0 base port 计算所有 PP rank，P1 上端口整体偏移 -1 连到无人监听的 31128

> 源是结构化 GitHub issue 线程（4 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/11343
**fix 跟踪**：PR #11342（https://github.com/vllm-project/vllm-ascend/pull/11342，多节点 PP 端口映射修复；评论#0 作者给出、维护者 yiz-liu 评审；快照未捕获合并记录，issue 由 MarinaMiao 以 completed 关闭 2026-08-07）；另官方建议多节点用 Ray 统一配置
**时间**：2026-07-02 ~ 2026-08-07
**框架**：vllm-ascend（PD 分离 + 多节点 PP，mooncake_connector KV 传输层）；线程未提供版本号
**平台**：A3-910C（两节点，PP=4/DP=1/TP=8，world_size 32）
**category**：interrupt
**investigation_quality**：high（用户端口级实证：21 次超时全指向 31128 → 登 P1 查监听 31129-31144 → 代码走读确认偏移 -1；维护者评审）
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（batch 2，组 1）

## 结构化 case

`postmortems/inbox/VLLM-ASC-11343.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

D 侧 `mooncake_connector._get_remote_ranks_for_req`（line ~1744）计算远程 PP rank 的 ZMQ handshake 端口时，所有 stage 都用 P0 的 base kv_port（31112）依次偏移（`[tp + pp*prefill_tp_size] + remote_port`），未考虑 P1 的 base port 是 31113——PP2/PP3 实际端口 31129/31137，计算得到 31128/31136，整体偏移 -1，连到无人监听的端口 → KV 传输 Receive timeout → P 节点 KV cache 无法被 D 取走、显存堆积到 100%，bench 卡死。

## 弯路与级联

- **误导性正常基线**：单 P 模式性能正常 + 单 curl 请求 OK，曾把怀疑引向 proxy 部分；bench 跑到 100+ 请求才卡死（失败样本少、占比低，约 21/758）。
- **实证定位链**：D 侧 21 次 `Receive request timeout ... port 31128` 全部指向 `33.182.142.85`（P1）→ 登 P1 查 ZMQ 监听 31129-31144，31128 无 worker → 对照 mooncake_connector.py:239 的 P 侧 `handshake_port = side_channel_port + device_index` 与 D 侧 line 1387/1744 的端口计算，确认 base port 取错。
- **正确解法之外**：官方同时推荐多节点统一走 Ray——`vllm serve` 只在 head 节点启动一次，所有 worker 共享同一 kv_port 配置，从根上消除 per-node 端口差异。
