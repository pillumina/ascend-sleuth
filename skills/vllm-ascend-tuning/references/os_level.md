# OS-Level Tuning

OS-level optimizations can significantly reduce latency jitter and improve throughput.

## 1. Memory Allocator Optimization

### jemalloc

jemalloc is optimized for multi-threaded scenarios, reducing memory fragmentation and lock contention.

```bash
# Install
sudo apt update
sudo apt install libjemalloc2

# Configure (set before starting vLLM)
export LD_PRELOAD=/usr/lib/"$(uname -i)"-linux-gnu/libjemalloc.so.2:$LD_PRELOAD
```

### TCMalloc

TCMalloc uses a multi-level cache structure to reduce mutex contention.

```bash
# Install
sudo apt update
sudo apt install libgoogle-perftools4 libgoogle-perftools-dev

# Find libtcmalloc.so location
find /usr -name libtcmalloc.so*

# Configure (higher priority than jemalloc)
export LD_PRELOAD="$LD_PRELOAD:/usr/lib/aarch64-linux-gnu/libtcmalloc.so"

# Verify
ldd `which python`
```

## 2. CPU Performance Mode

```bash
# Set to performance mode (requires root)
echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

**Effect:** Maintains CPU at maximum frequency, reduces latency jitter.

## 3. Disable Swap

```bash
# Minimize swap tendency (requires root)
sysctl -w vm.swappiness=0
```

**Effect:** Prevents second-level latency jitter caused by swap. Recommended value: 0 or 1.

## 4. Disable Automatic NUMA Balancing

```bash
# Disable automatic NUMA page migration (requires root)
sysctl -w kernel.numa_balancing=0
```

**Applicable scenarios:** Multi-socket servers, explicit NUMA-bound Ascend NPU deployments.

## 5. Increase Scheduler Migration Cost

```bash
sysctl -w kernel.sched_migration_cost_ns=50000
```

**Effect:** Reduces frequent thread migration, improves CPU cache locality, reduces latency jitter.
Recommended range: 50000-100000 ns.

## Summary Table

| Optimization | Command | Effect |
|-------------|---------|--------|
| jemalloc | `export LD_PRELOAD=...libjemalloc.so.2` | Reduce memory fragmentation |
| TCMalloc | `export LD_PRELOAD=...libtcmalloc.so` | Reduce mutex contention |
| CPU Performance | `echo performance > ...scaling_governor` | Reduce latency jitter |
| Disable Swap | `sysctl -w vm.swappiness=0` | Prevent swap latency |
| Disable NUMA Balance | `sysctl -w kernel.numa_balancing=0` | Improve cache locality |
| Migration Cost | `sysctl -w kernel.sched_migration_cost_ns=50000` | Reduce thread migration |
