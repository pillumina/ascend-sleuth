 # Environment Variables Reference

Complete environment variable configuration for vLLM-Ascend performance tuning.

## Quick Navigation

- [Required Variables (All Scenarios)](#required-variables-all-scenarios)
- [Core Performance Variables](#core-performance-variables)
- [Multi-NPU Communication (HCCL)](#multi-npu-communication-hccl)
- [Memory Management](#memory-management)
- [Device Selection](#device-selection)
- [vLLM V1 Engine](#vllm-v1-engine)
- [Scenario-Specific Configurations](#scenario-specific-configurations)
- [Complete Variable Reference](#complete-variable-reference)
- [Profiling Flags](#profiling-flags)

---

## Required Variables (All Scenarios)

```bash
# Memory Management
export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"
export LD_PRELOAD=/usr/lib/aarch64-linux-gnu/libjemalloc.so.2:$LD_PRELOAD

# Communication
export HCCL_OP_EXPANSION_MODE="AIV"
export HCCL_IF_IP=$local_ip              # Set to local IP
export GLOO_SOCKET_IFNAME=$nic_name      # Network interface name
export TP_SOCKET_IFNAME=$nic_name
export HCCL_SOCKET_IFNAME=$nic_name

# V1 Engine (Required for best performance)
export VLLM_USE_V1=1
export TASK_QUEUE_ENABLE=1
```

---

## Core Performance Variables

| Variable | Description | Default | Recommended |
|----------|-------------|---------|-------------|
| `TASK_QUEUE_ENABLE` | Enable task queue for operator dispatch pipeline | `0` | `1` (always enable) |
| `VLLM_ASCEND_ENABLE_DENSE_OPTIMIZE` | Enable dense model optimizations | `0` | `1` (for dense models) |
| `VLLM_ASCEND_ENABLE_PREFETCH_MLP` | Enable MLP prefetching for better performance | `0` | `1` (recommended) |

### Usage

```bash
# Core performance (almost always needed)
export TASK_QUEUE_ENABLE=1
export VLLM_ASCEND_ENABLE_DENSE_OPTIMIZE=1
export VLLM_ASCEND_ENABLE_PREFETCH_MLP=1
```

---

## Multi-NPU Communication (HCCL)

For tensor parallelism (TP > 1), configure HCCL (Huawei Collective Communication Library).

### Basic HCCL Configuration

| Variable | Description | Default | Recommended |
|----------|-------------|---------|-------------|
| `HCCL_OP_EXPANSION_MODE` | Communication dispatch mode | - | `AIV` (AI Vector Core) |
| `HCCL_BUFFSIZE` | HCCL buffer size | `120` | `256-1024` (scenario dependent) |
| `HCCL_CONNECT_TIMEOUT` | Connection timeout in seconds | `120` | `600` or higher |
| `HCCL_EXEC_TIMEOUT` | Execution timeout in seconds | `120` | `600` or higher |
| `VLLM_ASCEND_ENABLE_FLASHCOMM1` | Enable FlashComm optimization | `0` | `1` for specific models |

### Network Configuration

| Variable | Description | Example |
|----------|-------------|---------|
| `HCCL_IF_IP` | Local IP for HCCL | `141.61.133.111` |
| `HCCL_SOCKET_IFNAME` | Network interface for HCCL | `enp209s0f0` |
| `GLOO_SOCKET_IFNAME` | Network interface for Gloo | `enp209s0f0` |
| `TP_SOCKET_IFNAME` | Network interface for Tensor Parallel | `enp209s0f0` |

### Usage

```bash
# Basic multi-card communication
export HCCL_OP_EXPANSION_MODE="AIV"
export HCCL_BUFFSIZE=1024
export HCCL_CONNECT_TIMEOUT=600
export HCCL_EXEC_TIMEOUT=600

# Network configuration (replace with actual values)
export HCCL_IF_IP=$local_ip
export GLOO_SOCKET_IFNAME=$nic_name
export TP_SOCKET_IFNAME=$nic_name
export HCCL_SOCKET_IFNAME=$nic_name
```

### RDMA Configuration (Optional)

For RDMA-enabled networks:

```bash
# Use RDMA links instead of SDMA for 8P mesh
export HCCL_INTRA_ROCE_ENABLE=1

# RDMA traffic class
export HCCL_RDMA_TC=0

# RDMA service level
export HCCL_RDMA_SL=0
```   ---

## Memory Management

| Variable | Description | Default | Recommended |
|----------|-------------|---------|-------------|
| `PYTORCH_NPU_ALLOC_CONF` | PyTorch NPU memory allocator config | - | `expandable_segments:True` |
| `LD_PRELOAD` | Memory allocator library | - | jemalloc or tcmalloc path |
| `OMP_PROC_BIND` | OpenMP thread binding | - | `false` |
| `OMP_NUM_THREADS` | Number of OpenMP threads | - | `1-10` (scenario dependent) |
| `CPU_AFFINITY_CONF` | CPU affinity configuration | - | `2` |

### Memory Allocator Options

```bash
# jemalloc (recommended for multi-threaded)
export LD_PRELOAD=/usr/lib/aarch64-linux-gnu/libjemalloc.so.2:$LD_PRELOAD

# TCMalloc (alternative)
export LD_PRELOAD=/usr/lib/aarch64-linux-gnu/libtcmalloc.so:$LD_PRELOAD
```

### PYTORCH_NPU_ALLOC_CONF Options

```bash
# Enable expandable segments (memory reuse)
export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"

# Limit memory block split size
export PYTORCH_NPU_ALLOC_CONF="max_split_size_mb:250"

# Combined
export PYTORCH_NPU_ALLOC_CONF="max_split_size_mb:250,expandable_segments:True"
```

### Usage

```bash
# Memory management
export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True
export LD_PRELOAD=/usr/lib/aarch64-linux-gnu/libjemalloc.so.2:$LD_PRELOAD
export OMP_PROC_BIND=false
export OMP_NUM_THREADS=10
export CPU_AFFINITY_CONF=2
```

---

## Device Selection

| Variable | Description | Example |
|----------|-------------|---------|
| `ASCEND_RT_VISIBLE_DEVICES` | Which NPU devices to use | `0` or `0,1,2,3` |
| `ASCEND_DEVICE_ID` | Single device ID | `0` |

### Usage

```bash
# Single card
export ASCEND_RT_VISIBLE_DEVICES=0

# Multi-card TP2
export ASCEND_RT_VISIBLE_DEVICES=0,1

# Multi-card TP4
export ASCEND_RT_VISIBLE_DEVICES=0,1,2,3

# Multi-card TP8
export ASCEND_RT_VISIBLE_DEVICES=0,1,2,3,4,5,6,7

# Multi-card TP16 (two nodes)
export ASCEND_RT_VISIBLE_DEVICES=0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
```

---

## vLLM V1 Engine

| Variable | Description | Default | Recommended |
|----------|-------------|---------|-------------|
| `VLLM_USE_V1` | Enable vLLM V1 engine | `0` | `1` for multi-card |

### Usage

```bash
# Enable V1 engine for better multi-card performance
export VLLM_USE_V1=1
```

---

## Scenario-Specific Configurations

### Low Latency (TPOT ~20ms)

```bash
# Smaller buffer for lower latency
export HCCL_BUFFSIZE=256-500

# More CPU threads for faster scheduling
export OMP_NUM_THREADS=10

# Enable MLA optimizations
export VLLM_ASCEND_ENABLE_MLAPO=1

# Balance scheduling for low latency
export VLLM_ASCEND_BALANCE_SCHEDULING=1
```

### High Throughput (TPOT ~50ms)

```bash
# Larger buffer for higher throughput
export HCCL_BUFFSIZE=500-1024

# Fewer CPU threads (reduces contention)
export OMP_NUM_THREADS=1

# Enable fused MC2 for MoE
export VLLM_ASCEND_ENABLE_FUSED_MC2=1

# FlashComm for communication optimization
export VLLM_ASCEND_ENABLE_FLASHCOMM1=1
```

### Large EP / Multi-Node

```bash
# Aggregation support
export ASCEND_AGGREGATE_ENABLE=1
export ASCEND_TRANSPORT_PRINT=1

# A3 specific
export ASCEND_A3_ENABLE=1
export ACL_OP_INIT_MODE=1

# Timeout for large-scale deployment
export VLLM_NIXL_ABORT_REQUEST_TIMEOUT=300000

# Library path for Mooncake
export LD_LIBRARY_PATH=/usr/local/Ascend/ascend-toolkit/latest/python/site-packages/mooncake:$LD_LIBRARY_PATH
```

---

## Complete Variable Reference

### Memory & Allocation

| Variable | Values | Description |
|----------|--------|-------------|
| `PYTORCH_NPU_ALLOC_CONF` | `expandable_segments:True` | Enable memory reuse |
| `PYTORCH_NPU_ALLOC_CONF` | `max_split_size_mb:250` | Limit memory block split |
| `LD_PRELOAD` | jemalloc/tcmalloc path | Memory allocator |

### HCCL Communication

| Variable | Values | Description |
|----------|--------|-------------|
| `HCCL_OP_EXPANSION_MODE` | `AIV` | AI Vector Core for comm |
| `HCCL_BUFFSIZE` | 256-1024 | Communication buffer size |
| `HCCL_CONNECT_TIMEOUT` | 600+ | Connection timeout (seconds) |
| `HCCL_EXEC_TIMEOUT` | 600+ | Execution timeout (seconds) |
| `HCCL_IF_IP` | IP address | Local IP for HCCL |
| `HCCL_SOCKET_IFNAME` | nic name | Network interface |
| `GLOO_SOCKET_IFNAME` | nic name | Gloo interface |
| `TP_SOCKET_IFNAME` | nic name | Tensor parallel interface |
| `HCCL_INTRA_ROCE_ENABLE` | 1 | Use RDMA for 8P mesh |
| `HCCL_RDMA_TC` | 0 | RDMA traffic class |
| `HCCL_RDMA_SL` | 0 | RDMA service level |

### vLLM-Ascend Specific

| Variable | Values | Description |
|----------|--------|-------------|
| `VLLM_USE_V1` | 1 | Enable V1 engine |
| `TASK_QUEUE_ENABLE` | 1, 2 | Task queue optimization |
| `VLLM_ASCEND_ENABLE_MLAPO` | 1 | MLA optimization (DeepSeek/Qwen) |
| `VLLM_ASCEND_ENABLE_DENSE_OPTIMIZE` | 1 | Dense model optimizations |
| `VLLM_ASCEND_ENABLE_PREFETCH_MLP` | 1 | MLP prefetching |
| `VLLM_ASCEND_ENABLE_FUSED_MC2` | 1 | Fused MC2 for MoE |
| `VLLM_ASCEND_ENABLE_FLASHCOMM1` | 1 | FlashComm optimization |
| `VLLM_ASCEND_BALANCE_SCHEDULING` | 1 | Balance scheduling |
| `VLLM_ASCEND_ENABLE_NZ` | 1 | NZ layout support |

### Large Scale / Multi-Node

| Variable | Values | Description |
|----------|--------|-------------|
| `ASCEND_AGGREGATE_ENABLE` | 1 | Aggregation support |
| `ASCEND_TRANSPORT_PRINT` | 1 | Transport debug print |
| `ASCEND_A3_ENABLE` | 1 | A3 platform enable |
| `ACL_OP_INIT_MODE` | 1 | ACL op init mode |
| `VLLM_NIXL_ABORT_REQUEST_TIMEOUT` | 300000 | Request timeout (ms) |

### CPU & Threading

| Variable | Values | Description |
|----------|--------|-------------|
| `OMP_PROC_BIND` | false | OpenMP thread binding |
| `OMP_NUM_THREADS` | 1-10 | Number of OpenMP threads |
| `CPU_AFFINITY_CONF` | 1, 2 | CPU affinity configuration |

### Device Selection

| Variable | Values | Description |
|----------|--------|-------------|
| `ASCEND_RT_VISIBLE_DEVICES` | 0,1,2,... | Visible NPU devices |
| `ASCEND_DEVICE_ID` | 0 | Single device ID |

---

## Profiling Flags

| Variable | Description | Default | Usage |
|----------|-------------|---------|-------|
| `VLLM_TORCH_PROFILER_DIR` | Output directory for profiling data | - | `/path/to/profiling` |
| `VLLM_TORCH_PROFILER_WITH_STACK` | Include stack trace in profiling | 0 | `1` for detailed profiling |

### Usage

```bash
# Enable profiling
export VLLM_TORCH_PROFILER_DIR=/path/to/profiling
export VLLM_TORCH_PROFILER_WITH_STACK=1
```

---

## Quick Copy Templates

### Single Card (Dense Model)

```bash
export TASK_QUEUE_ENABLE=1
export VLLM_ASCEND_ENABLE_DENSE_OPTIMIZE=1
export VLLM_ASCEND_ENABLE_PREFETCH_MLP=1
export ASCEND_RT_VISIBLE_DEVICES=0
export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"
export LD_PRELOAD=/usr/lib/aarch64-linux-gnu/libjemalloc.so.2:$LD_PRELOAD
```

### Multi-Card (TP > 1)

```bash
# Required
export VLLM_USE_V1=1
export TASK_QUEUE_ENABLE=1
export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"
export LD_PRELOAD=/usr/lib/aarch64-linux-gnu/libjemalloc.so.2:$LD_PRELOAD

# Communication
export HCCL_OP_EXPANSION_MODE="AIV"
export HCCL_BUFFSIZE=1024
export HCCL_CONNECT_TIMEOUT=600
export HCCL_EXEC_TIMEOUT=600

# Network (replace with actual values)
export HCCL_IF_IP=$local_ip
export GLOO_SOCKET_IFNAME=$nic_name
export TP_SOCKET_IFNAME=$nic_name
export HCCL_SOCKET_IFNAME=$nic_name

# Device
export ASCEND_RT_VISIBLE_DEVICES=0,1,2,3,4,5,6,7
```

### Low Latency (MoE Model)

```bash
# Base config
export VLLM_USE_V1=1
export TASK_QUEUE_ENABLE=1
export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"
export HCCL_OP_EXPANSION_MODE="AIV"

# Low latency specific
export HCCL_BUFFSIZE=500
export OMP_NUM_THREADS=10
export VLLM_ASCEND_ENABLE_MLAPO=1
export VLLM_ASCEND_BALANCE_SCHEDULING=1

# Network
export HCCL_IF_IP=$local_ip
export GLOO_SOCKET_IFNAME=$nic_name
export TP_SOCKET_IFNAME=$nic_name
export HCCL_SOCKET_IFNAME=$nic_name
```

### High Throughput (MoE Model)

```bash
# Base config
export VLLM_USE_V1=1
export TASK_QUEUE_ENABLE=1
export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"
export HCCL_OP_EXPANSION_MODE="AIV"

# High throughput specific
export HCCL_BUFFSIZE=1024
export OMP_NUM_THREADS=1
export VLLM_ASCEND_ENABLE_FUSED_MC2=1
export VLLM_ASCEND_ENABLE_FLASHCOMM1=1

# Network
export HCCL_IF_IP=$local_ip
export GLOO_SOCKET_IFNAME=$nic_name
export TP_SOCKET_IFNAME=$nic_name
export HCCL_SOCKET_IFNAME=$nic_name
```

### Large EP / PD Separation

```bash
# Base config
export VLLM_USE_V1=1
export TASK_QUEUE_ENABLE=1
export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"
export HCCL_OP_EXPANSION_MODE="AIV"

# Large scale specific
export HCCL_BUFFSIZE=256
export VLLM_ASCEND_ENABLE_FUSED_MC2=1
export VLLM_ASCEND_ENABLE_FLASHCOMM1=1
export ASCEND_AGGREGATE_ENABLE=1
export ASCEND_TRANSPORT_PRINT=1
export ASCEND_A3_ENABLE=1
export ACL_OP_INIT_MODE=1
export VLLM_NIXL_ABORT_REQUEST_TIMEOUT=300000
export LD_LIBRARY_PATH=/usr/local/Ascend/ascend-toolkit/latest/python/site-packages/mooncake:$LD_LIBRARY_PATH

# Network
export HCCL_IF_IP=$local_ip
export GLOO_SOCKET_IFNAME=$nic_name
export TP_SOCKET_IFNAME=$nic_name
export HCCL_SOCKET_IFNAME=$nic_name
```
