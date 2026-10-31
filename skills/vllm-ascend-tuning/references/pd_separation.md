 # PD Separation Architecture Guide

Prefill-Decode (PD) Separation splits the inference pipeline into dedicated Prefill and Decode nodes for optimal resource utilization.

## Architecture Overview

```
+----------------+     KV Transfer     +----------------+
|  Prefill Node  | ==================> |  Decode Node   |
|  (P)           |    Mooncake/NIXL    |  (D)           |
+----------------+                     +----------------+
| High TP        |                     | High DP        |
| Low DP         |                     | Low TP         |
| Compute-bound  |                     | Memory-bound   |
+----------------+                     +----------------+
```

## When to Use PD Separation

```
[+] Ultra-long context (> 64K)
[+] High concurrency with varying input lengths
[+] Need to optimize TTFT independently
[+] Multi-tenant serving with different SLOs
[+] Large MoE models (GLM-5.1, DeepSeek)

[-] Short context (< 4K)
[-] Low concurrency
[-] Simple deployment requirements
```

## Configuration

### Prefill Node Configuration

```bash
# P Node: High TP, Low DP
nic_name="enp48s3u1u2"
local_ip="141.61.81.181"

export VLLM_ASCEND_ENABLE_FUSED_MC2=1
export HCCL_OP_EXPANSION_MODE="AIV"
export VLLM_ASCEND_ENABLE_FLASHCOMM1=1
export HCCL_IF_IP=$local_ip
export GLOO_SOCKET_IFNAME=$nic_name
export TP_SOCKET_IFNAME=$nic_name
export HCCL_SOCKET_IFNAME=$nic_name
export OMP_PROC_BIND=false
export OMP_NUM_THREADS=1
export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True
export HCCL_BUFFSIZE=256
export ASCEND_AGGREGATE_ENABLE=1
export ASCEND_TRANSPORT_PRINT=1
export ACL_OP_INIT_MODE=1
export ASCEND_A3_ENABLE=1
export VLLM_NIXL_ABORT_REQUEST_TIMEOUT=300000

vllm serve /path/to/model \
  --host 0.0.0.0 \
  --port 8000 \
  --data-parallel-size 4 \
  --data-parallel-rank 0 \
  --data-parallel-address $DECODE_IP \
  --data-parallel-rpc-port 29500 \
  --tensor-parallel-size 8 \
  --enable-expert-parallel \
  --speculative-config '{"num_speculative_tokens": 3, "method":"mtp"}' \
  --max-model-len 202752 \
  --max-num-batched-tokens 4096 \
  --max-num-seqs 64 \
  --gpu-memory-utilization 0.95 \
  --enforce-eager \
  --quantization ascend \
  --kv-transfer-config '{
    "kv_connector": "MooncakeConnectorV1",
    "kv_role": "kv_producer",
    "kv_port": "30000",
    "engine_id": "0",
    "kv_connector_extra_config": {
      "use_ascend_direct": true,
      "prefill": {"dp_size": 4, "tp_size": 8},
      "decode": {"dp_size": 32, "tp_size": 1}
    }
  }'
```

### Decode Node Configuration

```bash
# D Node: High DP, Low TP
nic_name="enp48s3u1u2"
local_ip="141.61.81.34"

export VLLM_ASCEND_ENABLE_FUSED_MC2=1
export HCCL_OP_EXPANSION_MODE="AIV"
export HCCL_IF_IP=$local_ip
export GLOO_SOCKET_IFNAME=$nic_name
export TP_SOCKET_IFNAME=$nic_name
export HCCL_SOCKET_IFNAME=$nic_name
export OMP_PROC_BIND=false
export OMP_NUM_THREADS=1
export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True
export HCCL_BUFFSIZE=900
export ASCEND_AGGREGATE_ENABLE=1
export ASCEND_TRANSPORT_PRINT=1
export ACL_OP_INIT_MODE=1
export ASCEND_A3_ENABLE=1
export VLLM_NIXL_ABORT_REQUEST_TIMEOUT=300000
export TASK_QUEUE_ENABLE=1
export VLLM_ASCEND_ENABLE_MLAPO=1

vllm serve /path/to/model \
  --host 0.0.0.0 \
  --port 8000 \
  --data-parallel-size 32 \
  --data-parallel-rank 1 \
  --data-parallel-address $PREFILL_IP \
  --data-parallel-rpc-port 29500 \
  --tensor-parallel-size 1 \
  --enable-expert-parallel \
  --speculative-config '{"num_speculative_tokens": 3, "method":"mtp"}' \
  --max-model-len 202752 \
  --max-num-batched-tokens 32 \
  --max-num-seqs 8 \
  --gpu-memory-utilization 0.92 \
  --async-scheduling \
  --quantization ascend \
  --compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY", "cudagraph_capture_sizes":[4,8,12,16,20,24,28,32]}' \
  --kv-transfer-config '{
    "kv_connector": "MooncakeConnectorV1",
    "kv_role": "kv_consumer",
    "kv_port": "30100",
    "engine_id": "1",
    "kv_connector_extra_config": {
      "use_ascend_direct": true,
      "prefill": {"dp_size": 4, "tp_size": 8},
      "decode": {"dp_size": 32, "tp_size": 1}
    }
  }'
```

## Strategy Selection

### GLM-5.1 Example (32 Cards)

```
P Node (16 cards):
  MLA: DP4 + TP8
  MoE: EP16 + TP1

D Node (16 cards):
  MLA: DP32 + TP1
  MoE: EP32 + TP1
```

### DeepSeek-V3 Example (16 Cards)

```
P Node (8 cards):
  MLA: DP2 + TP8
  MoE: EP8 + TP1

D Node (8 cards):
  MLA: DP8 + TP1
  MoE: EP8 + TP1
```

## KV Transfer Options

| Option | Description |
|--------|-------------|
| `kv_connector` | Connector type (MooncakeConnectorV1) |
| `kv_role` | `kv_producer` (P) or `kv_consumer` (D) |
| `kv_port` | Port for KV transfer |
| `engine_id` | Unique engine identifier |
| `use_ascend_direct` | Use Ascend direct memory access |
| `prefill.dp_size` | DP size for prefill |
| `prefill.tp_size` | TP size for prefill |
| `decode.dp_size` | DP size for decode |
| `decode.tp_size` | TP size for decode |

## Performance Characteristics

### Prefill Node

- **Optimized for**: TTFT (Time To First Token)
- **Workload**: Compute-bound (prompt processing)
- **Configuration**: High TP, large max-num-batched-tokens
- **Memory**: Higher utilization for prompt processing

### Decode Node

- **Optimized for**: TPOT (Time Per Output Token)
- **Workload**: Memory-bound (token generation)
- **Configuration**: High DP, small batch per instance
- **Memory**: Optimized for KV cache

## Deployment Patterns

### Pattern 1: 1P + 1D (Simple)

```
1 Prefill node + 1 Decode node
Good for: Single-tenant, predictable load
```

### Pattern 2: 1P + ND (Scalable)

```
1 Prefill node + N Decode nodes
Good for: High concurrency, varying output lengths
```

### Pattern 3: NP + ND (Enterprise)

```
N Prefill nodes + N Decode nodes
Good for: High availability, multi-tenant
```

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| KV transfer timeout | Network latency | Increase VLLM_NIXL_ABORT_REQUEST_TIMEOUT |
| P node OOM | Large prompt batch | Reduce max-num-seqs |
| D node slow | Low DP | Increase DP size |
| Connection refused | Wrong IP/port | Verify data-parallel-address |
| Role mismatch | Same kv_role | Ensure P=producer, D=consumer |

## Best Practices

1. **P Node**: Use `--enforce-eager` for flexibility
2. **D Node**: Use graph mode for optimal decode
3. **Network**: Low-latency interconnect between P and D
4. **Monitoring**: Separate metrics for P and D nodes
5. **Scaling**: Scale D nodes independently based on output demand
