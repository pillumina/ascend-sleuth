# VLLM-ASC-ZMQ-HANDSHAKE-PORT-OVERFLOW: PD 分离 + Mooncake KV 传输握手端口越界（kv_port 基址 + rank 偏移 ≥65536）

> 源是**上游同族 issue + 源码级核验**（非本仓 diagnose session）：现象侧来自上游报错家族，
> 机制侧在 v0.23.0rc1 源码里逐行核实（含"无端口范围校验"这一点）。按 to-postmortem 的
> 「只写指针 + 不重写」口径记录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/8938 （同族：多 P 节点 ZMQ 端口问题）
**框架/平台**：vllm-ascend（现场报告 v0.22.1rc1；本仓源码核验 v0.23.0rc1）/ A2、A3 多机 PD 分离 + Mooncake KV 传输
**category**：interrupt
**investigation_quality**：high（公式与"无范围校验"两点均在源码里逐行确认；无上游 fix PR）
**verification**：investigation（代码级已核，非维护者结论）
**novelty**：new_pattern —— 与 VLLM-ASC-8938（端口被占，值合法）机制不同：本条是**算出来的端口号越界**；
与 VLLM-ASC-11343（选错基址）也不同：本条是**偏移累加溢出**；与 VLLM-ASC-HCCL-BIND-IP-PORT 分层：
那条失败在 HCCL 集合通信端口，本条失败在 Mooncake KV 传输的 ZMQ 握手端口。

## 机制（源码级）

`vllm_ascend/distributed/kv_transfer/kv_p2p/mooncake_connector.py`（v0.23.0rc1）：

```
# Handshake base port                                        # L1592、L1971 两处
self.side_channel_port = (
    vllm_config.kv_transfer_config.kv_port
    + vllm_config.parallel_config.data_parallel_rank
    * tensor_parallel_size * pipeline_parallel_size * pcp_size
)
device_index = (pp_rank * pcp_size + pcp_rank) * tp_size + tp_rank
handshake_port = self.side_channel_port + device_index        # L1978-1979（另见 L299）
path = make_zmq_path("tcp", self.side_channel_host, handshake_port)
```

全文件**无端口范围校验**（`grep -n '65535|65536|port range'` 零命中）——越界值直接进 ZMQ bind。

## 现象与触发面

- 报错形如 `port 65536 have already been bound`；65536 = 2^16 是越界值，不是"被占用"；
- 多节点（如 3×1P + 1×1D）各节点配了相同/相邻 kv_port 基址 → 各 rank 偏移累加后跨节点重叠或越界；
- 长稳场景下可能出现"运行一段时间后"才失败（线程/进程重建时重新算端口）。

## fix

按公式复算，给**每个节点组**分配独立 kv_port 基址，保证 `基址 + dp_size × tp × pp × pcp ≤ 65535`
并留出 `tp × pp × pcp` 余量；把"每节点组不同端口段"写进编排模板（硬要求）。
验证：拉起后 `grep -aoE 'port [0-9]{4,6}'` 确认实际握手端口全部 ≤65535。

## 未闭环与残余风险

- 上游无 fix PR：**代码层仍无范围校验**，属"配置侧规避"而非"根因修复"——升级不解决，必须改端口段分配；
- 与 8938（Address already in use）容易混：判别第一步就是看端口值是否 >65535。
