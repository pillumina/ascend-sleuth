 # CPU Binding Guide

CPU Binding pins vLLM processes and threads to specific CPU cores to reduce CPU-NPU cross-NUMA communication overhead and stabilize inference latency.

## Overview

- Designed for **ARM architecture and Ascend NPUs**
- Only adjusts host-side CPU affinity policies
- Does not alter model execution logic or impact inference results

## Usage

### Online Serving (Enabled by Default)

```bash
vllm serve Qwen/Qwen2.5-7B-Instruct \
  --additional-config '{"enable_cpu_binding": true}'
```

### Disable CPU Binding

```bash
vllm serve Qwen/Qwen2.5-7B-Instruct \
  --additional-config '{"enable_cpu_binding": false}'
```

### Offline Inference

```python
from vllm import LLM

# Enable
llm = LLM(
    model="Qwen/Qwen2.5-7B-Instruct",
    additional_config={"enable_cpu_binding": True},
)

# Disable
llm = LLM(
    model="Qwen/Qwen2.5-7B-Instruct",
    additional_config={"enable_cpu_binding": False},
)
```

## Dependencies

### Ubuntu/Debian
```bash
sudo apt-get install -y util-linux numactl procps
```

### RHEL/CentOS/Alma/Rocky
```bash
sudo yum install -y util-linux numactl procps-ng
```

### openEuler
```bash
sudo dnf install -y util-linux numactl procps-ng
```

## IRQ Binding Additional Considerations

For Docker containers where `systemctl` is unavailable:

**Stop irqbalance on host:**
```bash
sudo systemctl stop irqbalance
```

**Restore after vLLM process:**
```bash
sudo systemctl start irqbalance
```

**Required permissions:**
- Read access to `/proc/self/status` and `/proc/interrupts`
- Write access to `/proc/irq/*/smp_affinity`

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| Can not get running npu info | npu-smi process table empty | Ensure process runs on visible NPUs |
| Insufficient CPUs for binding | CPUs per NPU < 5 | Expand CPU list or reduce visible NPUs |
| NPU topo affinity not found | npu-smi cannot get topology | Verify npu-smi installation |
| Bind cpus failed in rankX | taskset unavailable or no permission | Install required tools, check permissions |

## Performance Impact

- Reduces CPU-NPU cross-NUMA communication
- Stabilizes inference latency
- Most effective on multi-socket servers
- Default enabled for ARM + Ascend configurations
