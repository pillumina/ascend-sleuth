# CANN / HCCL Tuning

HCCL (Huawei Collective Communication Library) tuning is critical for distributed inference performance.

## 1. HCCL AIV Mode

AIV mode uses AI Vector Core for communication dispatch (replacing AI CPU), improving communication performance.

```bash
export HCCL_OP_EXPANSION_MODE="AIV"
```

## 2. RDMA Configuration

### HCCL_INTRA_ROCE_ENABLE

Use RDMA links instead of SDMA for 8P mesh interconnection.

```bash
export HCCL_INTRA_ROCE_ENABLE=1
```

### HCCL_RDMA_TC

Configure RDMA network card traffic class.

```bash
export HCCL_RDMA_TC=0
```

### HCCL_RDMA_SL

Configure RDMA network card service level.

```bash
export HCCL_RDMA_SL=0
```

## 3. Buffer Configuration

### HCCL_BUFFSIZE

Control shared data buffer size between NPUs.

```bash
# Default is usually sufficient, increase for large-scale models
export HCCL_BUFFSIZE=20971520  # 20MB
```

## 4. Combined Configuration Example

```bash
# Recommended for multi-card inference
export HCCL_OP_EXPANSION_MODE="AIV"
export HCCL_INTRA_ROCE_ENABLE=1
export HCCL_BUFFSIZE=20971520
```

## Summary Table

| Variable | Description | Typical Value |
|----------|-------------|---------------|
| `HCCL_OP_EXPANSION_MODE` | Communication dispatch mode | `AIV` |
| `HCCL_INTRA_ROCE_ENABLE` | Use RDMA for 8P mesh | `1` |
| `HCCL_RDMA_TC` | RDMA traffic class | `0` |
| `HCCL_RDMA_SL` | RDMA service level | `0` |
| `HCCL_BUFFSIZE` | NPU shared buffer size | `20971520` |

## Notes

- RDMA configuration requires hardware support
- AIV mode may not be available on all NPU generations
- Buffer size should be adjusted based on model size and available HBM
