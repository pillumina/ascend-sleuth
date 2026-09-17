# VLLM-ASC-HCCL-BIND-IP-PORT: 多 P 节点独立启动 + MoE 分发长稳后 P 节点崩溃——plog 报 Communication_Error_Bind_IP_Port（HCCL 建链 bind IP:Port 失败，src_port 越界）

> 源是**二手现场记录 + 上游同签名 issue**（非本仓 diagnose session）：机制来自一份外部现场定位记录
> （原文未公开引用），签名证据来自上游 issue。按 to-postmortem 的「只写指针 + 不重写」口径记录，进 inbox 待 groom 分诊。

**源文档**：
- 上游同签名证据：https://github.com/vllm-project/vllm-ascend/issues/9447（GLM-5.1 + vllm-ascend 0.18.0rc1，A3 双机 RoCE；plog `src_port: 344832056`）
- 现场记录（外部，原文未公开引用）：4×A3 3×1P+1×1D，v0.22.1rc1，运行两天半后 P 节点崩溃
- 同类现象：https://github.com/vllm-project/vllm-ascend/issues/13527（v4 flash PD 分离运行一段时间后 p0 因 HCCL 失败挂死）

**框架/平台**：vllm-ascend v0.22.1rc1（rc）/ A3-910C 多机 PD 分离（3×1P + 1×1D，独立启动、不使用 Ray）
**category**：interrupt
**investigation_quality**：medium（有同签名 plog 证据 + 机制推演；无维护者根因结论、无 fix PR、复现不稳定）
**verification**：investigation（issue 无 upstream fix；机制为那份外部现场记录的「最可能根因」）
**novelty**：new_pattern —— 全库无 `Communication_Error_Bind_IP_Port` / `hccl_ret` 命中。
与两条近邻的分层（本 case 的判别价值就在这里）：
- **VLLM-ASC-8938**（ZMQ `Address already in use`）：那是 **Mooncake KV 传输端口**（用户配置 `kv_port`，ZMQ 层）；
  本条是 **HCCL 集合通信自行分配**的建链端口 → 用户配置面完全不同；
- **VLLM-ASC-12461**（多节点 EP + FusedMoE MC2 的 aicore exception）：同为"多节点 MoE 分发通信失败"，
  但报错层不同——那条是算子 aicore exception，本条是 HCCL socket 建链失败。

## 现象摘要

多 P 节点独立启动（无 Ray 统一编排）的 PD 分离部署，服务长稳运行（数小时至两天半）后某 P 节点崩溃退出：

- 崩溃点常在 MoE 分发路径之后：python 栈尾在 `token_dispatcher` 的 `torch.repeat_interleave` → `npu_moe_distribute_dispatch`（MC2 跨节点分发）；
- HCCL/plog：`hccl_socket_manager` 建链失败，报 `Communication_Error_Bind_IP_Port`；**dest/src_port 出现越界数值**（#9447 实测 `src_port=344832056`，正常端口范围 0~65535）；
- `hccl_test` 链自测正常；`kv_port` 无异常。

## 一句话根因（未闭环）

最可能：多 P 节点独立启动下，MoE 专家并行的跨节点 HCCL 通路在长稳后通信资源（socket/通信组）释放-重建时**端口分配异常**——HCCL socket 端口计算出越界值 → bind IP:Port 失败 → P 节点崩溃。与 `kv_port`/Mooncake 无关。

## 排查与处置（按优先级）

1. 取崩溃 P 节点 plog，定位失败点是哪个**通信组**（EP / TP / DP）；
2. 比对 `src_port`/`dest_port` 是否为越界值（确认是端口计算问题，不是端口冲突）；
3. 三个 P 节点的 `HCCL_SOCKET_IFNAME` / `HCCL_IF_IP` / `HCCL_OP_EXPANSION_MODE` 是否一致（独立启动最易漂移；`HCCL_OP_EXPANSION_MODE=AIV` 在多通信域有抢核问题）；
4. rc 版本升级到正式版后长稳复现（rc backport 不全）；
5. `HCCL_DEBUG=INFO` 抓崩溃前最后一次建链的 IP:Port 与组名，交维护者（上游 issue 仍 OPEN）。

## 未闭环与残余风险（如实标注）

- 根因是**推演结论**，不是代码级定位；复现不稳定（同类 #13527）；
- 上游无 fix PR；本 case 的 `fix_type` 因此记为 `pending-investigation`（给排查与止损动作，不给"确定性修复"）；
- 若现场出现的是 `Address already in use`（端口正常、只是被占用）→ 不是本条，转 VLLM-ASC-8938 族。
