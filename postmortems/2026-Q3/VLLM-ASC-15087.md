# VLLM-ASC-15087: PD 分离 prefill 节点静默冻结 —— v0.23.0 `_disable_preemption_on_prefill_node()` 禁用抢占致调度活锁

> 源：现场诊断 trace `traces/2026-09-08-ascendstore-pd-prefill-hang.yaml`（证据 `traces/evidence/2026-09-08-ascendstore-pd-prefill-hang/evidence.txt`）+ vllm-ascend 开发确认（PR #14233）。
> 本 case YAML 草稿：`postmortems/inbox/VLLM-ASC-15087.case.yaml`；按 to-postmortem 流程产出，进 inbox 待 grom 分诊。

**框架/平台**：vllm-ascend v0.23.0 / A3-910C 与 A2-910B。PD 分离部署（4机A3 P 节点 / 8机A2 D 节点，1P1D），P 节点内存池化（AscendStoreConnector，load_async=true）+ MooncakeConnectorV1（kv_transfer）+ 多轮对话对比压测。
**category**：interrupt（静默 hang）。
**investigation_quality**：high（源码级定位 + 维护者确认 + fix 复测验证）。
**verification**：upstream-maintainer-confirmed（vllm-ascend 开发确认根因；PR #14233 为引入回归的临时方案）。
**novelty**：new_pattern（全库无 `_disable_preemption_on_prefill_node` / PD prefill 无抢占楔 case；邻近 8808/11343/10998/13356/13964/7871 机制全异）。

## 现象摘要

PD 分离多轮对话压测，压到约 8 分钟后全量请求 **prefill hang 不恢复**，P/D 节点全部卡死（直到手动 kill）。

- **P 侧日志（时间晚墙钟 8h，已校准）**：空闲段后，EngineCore 每 ~1s 重复同一 reqid 两行——
  ```
  [pool_scheduler.py:559] Reqid: chatcmpl-…-a6d79777, Total tokens 46338, kvpool hit tokens: 23168, need to load: 23168
  [pool_scheduler.py:580] KV pool load spec created req=chatcmpl-…-a6d79777 vllm_cached=0 kvpool_cached=23168 need_to_allocate=23168 load_async=True use_layerwise=False
  ```
  从 08:34:22 持续到 09:23:57（约 50 min）不推进。此前有 `[mooncake_connector.py:1910] Delaying free of 181/182 blocks` + `GPU KV cache usage: 84.6%→96.4%`。
- **D 侧**：请求自然 drain 至 0（Engine 006: 9→4→1→0 reqs），随后只剩 /health、/metrics 行。
- **无 ERROR / Traceback / HCCL timeout / abort**——静默冻结。
- **py-spy**：P EngineCore 主线程稳定卡 `collective_rpc → _wait_for_response → get_response → dequeue（shm_broadcast.wait）`；D 侧 worker 在 dummy_run `acl_graph.call` 后进入 `dequeue` 空转。

## 一句话根因

v0.23.0 新引入的 `_disable_preemption_on_prefill_node()`（`patch_balance_schedule.py:79`，guard=`vllm_version_is('0.23.0') && kv_role=='kv_producer'`）在 **PD 分离 prefill 节点禁用自动抢占**。KV cache 打满、需求从池加载大上下文时，`allocate_slots` 给不出槽位——正常会抢占最低优先级 running 请求腾资源——但 `_disable_preemption=True` 直接 `break`、不抢占 → 请求永远拿不到槽位 → 调度活锁 → 引擎 quiesce。

关键源码分水岭（`patch_balance_schedule.py`「allocate_slots」循环）：
```python
while True:
    new_blocks = self.kv_cache_manager.allocate_slots(request, num_new_tokens, ...)
    if new_blocks is not None:
        break                       # 有槽位 → 调度成功
    if self._disable_preemption:
        break                       # 抢占被禁 → 直接放弃，不腾资源
    # 否则：抢占最低优先级 running 请求，腾槽位再重试
    preempted_req = max(self.running, key=lambda r: (r.priority, r.arrival_time))
    self._preempt_request(preempted_req, ...)
```

## 因果链

```
DP 多轮载荷 + KV cache pool(load_async) + PD(kv_producer) + v0.23.0
  → KV 打满、需从池重载大上下文(23168 token)
  → allocate_slots 给不出槽位
  → 本应抢占腾资源，但 _disable_preemption=True → 直接 break
  → 请求永远拿不到槽位 → 加载从不真正执行
  → 调度活锁（每 ~1s 重打 load spec，计数冻结）
  → P EngineCore 卡 collective_rpc 等 worker 响应 → 引擎 quiesce → P/D 全部冻结
```

## 为什么只影响 v0.23.0 / 某些组合

- 双守卫：`vllm_version_is('0.23.0') && kv_role=='kv_producer'` → 其他镜像版本、或非 prefill(producer) 节点不触发。
- 充分条件：**P 节点 KV 打满 + 需从池重载大上下文** 同时出现（多轮长上下文 + 池化 + load_async 才凑齐）→ 所以"其他模型通常不踩"。

## fix

一行（`vllm_ascend/patch/platform/patch_balance_schedule.py:79`）：
```python
# self._disable_preemption = _disable_preemption_on_prefill_node(vllm_config)   # 旧
self._disable_preemption = False                                               # 新
```
或回退 PR #14233（等价且更干净）。**已验证**：相同部署/测试方式复测 4 次不复现。修复后务必复测 PR #14233 原本守护的 Qwen3.5 系场景是否回归。

## 诊断/根治的关键判别（沉淀教训）

- **同实体每 ~1s 重复打同一条日志 + 计数冻结 = 控制循环活锁，不是组件故障**——别把"发日志的组件"（pool_scheduler / mooncake / AscendStore 异步 load）当故障组件；真实支点在**调度/控制循环层**（preemption/admission）。
- 静默停滞类问题先查**调度/接纳/抢占**维度，再补数据流/传输细节。
- 主题诊断时直接 grep `Automatic scheduler preemption is disabled`（patch_balance_schedule.py:80，仅 `_disable_preemption=True` 打印）可快速二分。

## 建议 triage 路由症状（已同步，不新增）

`symptoms` 关键词已可由 `inference_interrupt` 路由（本轮新增 `\bpreempt\b|抢占|无法.*调度|调度.*(卡|死锁|楔)|admission.*fail|排队.*堆积|waiting.*递增` 分支 + 既有 `\bhang\b` 覆盖）→ `inference/vllm-ascend/interrupt/`。无需再补。
