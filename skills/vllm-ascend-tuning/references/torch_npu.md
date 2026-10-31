 # torch_npu Optimization

torch_npu provides several environment variables for performance tuning.

## 1. Memory Optimization

### max_split_size_mb

Controls the maximum size of memory blocks that can be split.

```bash
# Prevent large memory blocks from being fragmented
export PYTORCH_NPU_ALLOC_CONF="max_split_size_mb:250"
```

### expandable_segments

Enables scalable memory segments, allowing early release of communication stream memory for compute stream reuse.

```bash
export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"
```

**Note:** Can be combined:
```bash
export PYTORCH_NPU_ALLOC_CONF="max_split_size_mb:250,expandable_segments:True"
```

## 2. Scheduling Optimization

### TASK_QUEUE_ENABLE

Optimizes operator dispatch queue.

```bash
# May increase memory peak, could degrade when memory is tight
export TASK_QUEUE_ENABLE=2
```

### CPU_AFFINITY_CONF

CPU affinity configuration, significantly improves performance for CPU-bound models.

```bash
export CPU_AFFINITY_CONF=1
```

**Effect:** Binds worker threads to specific CPU cores, reduces cross-NUMA communication.

## 3. Combined Configuration Example

```bash
# Recommended for high-throughput scenarios
export PYTORCH_NPU_ALLOC_CONF="max_split_size_mb:250,expandable_segments:True"
export TASK_QUEUE_ENABLE=2
export CPU_AFFINITY_CONF=1
```

## Summary Table

| Variable | Value | Effect | Note |
|----------|-------|--------|------|
| `max_split_size_mb` | 250 | Prevent memory fragmentation | Adjust based on model size |
| `expandable_segments` | True | Memory reuse between streams | Default in newer versions |
| `TASK_QUEUE_ENABLE` | 2 | Optimize dispatch queue | May increase memory peak |
| `CPU_AFFINITY_CONF` | 1 | CPU binding | Significant for CPU-bound models |
