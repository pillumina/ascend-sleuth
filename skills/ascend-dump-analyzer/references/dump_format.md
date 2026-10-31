# Dump JSON Format Reference

Complete schema for dump JSON files produced by `msprechecker_dump.py` or `msprechecker dump`.

## Top-Level Structure

```json
{
  "_meta": { ... },
  "system": { ... },
  "hardware": { ... },
  "npu": { ... },
  "ascend": { ... },
  "env": { ... },
  "runtime": { ... },
  "network": { ... },
  "mies config": { ... },
  "user config": { ... },
  "mindie env": { ... },
  "model config": { ... },
  "weight": { ... },
  "ping": { ... },
  "hccl": { ... },
  "link": [ ... ],
  "vnic": [ ... ],
  "tls": [ ... ]
}
```

Core collectors are always attempted on Linux; their data sections can be absent on failure. Use `_meta.collection` to distinguish success, partial, failed, and skipped. Older dumps without this metadata have unknown coverage; absence alone does not establish that a collector was not requested.

---

## _meta

Collection metadata. Exclude the exact `_meta` section from comparison, include relevant fields in the report header.

Version 1.1 adds (existing data section names remain unchanged):

- `schema_version`: `"1.1"`.
- `status`: `success` or `partial`; any failed/partial collector makes the dump partial.
- `collection`: section name to `{status, errors, command_failures, reason?}`. `success` means the collector completed without a recorded failure, not that every possible field was observed or that the host is healthy. Inspect field evidence before diagnosing.
- Status `skipped` means an optional input was not supplied; `failed` means a requested operation failed; `partial` means some data remains usable. Errors inside structured sub-results and external command failures are retained.
- `collection.env`: additionally records `scope` (`all`/`filtered`), `included_keys`, and `critical_keys_in_scope`. Only the explicitly covered keys can be interpreted as unset when absent and collection succeeded.
- `collection.npu/link/vnic/tls/hccl.device_ids`: actual visible device IDs, sorted. For `link/vnic/tls` lists, index maps through this array, not directly to the device number.
- `redaction`: describes sharing safeguards and omitted process arguments. Sensitive fields, credential URLs, common credential assignments and known secret copies are masked. This is not a guarantee that arbitrary raw text is safe to share.
- NPU per-device `queries`: return code/status per subcommand. Ascend components add `source`, `collection_status` (`success`/`unavailable`/`failed`), and optional `reason`/`error`.

Compatibility and report rules:

- Old dump data remains readable. A component `{}` or a missing section means insufficient evidence unless a collection status explains it.
- New comparator paths use typed brackets: `$["ascend"]["driver"]["version"]`; literal dict keys are JSON-escaped strings and list indices are integers. Empty containers retain their JSON types; missing is distinct from null.
- Comparison outputs list only loaded inputs in `files`/`file_paths`; `requested_files`, `skipped_files`, and `status` expose incomplete coverage. Colliding basenames receive unique display labels.
- Sensitive changes can retain a difference count while values are masked; identical masked values cannot establish equality of the original credentials.
- Similarity measures field agreement, not compatibility, health, or the safety of critical differences.


| Field | Type | Description |
|-------|------|-------------|
| `tool` | string | Tool name (`msprechecker_dump.py` or `msprechecker`) |
| `version` | string | Tool version |
| `timestamp` | string | Collection time `YYYY-MM-DD HH:MM:SS` |
| `hostname` | string | Server hostname |
| `python_version` | string | Python version |
| `collect_duration_seconds` | float | Collection duration in seconds |

---

## system

System information collected from `lscpu`, `/proc/cpuinfo`, `platform.uname()`, sysfs.

| Field | Type | Description | Expected |
|-------|------|-------------|----------|
| `model_name` | string | CPU model name | Any valid CPU |
| `virtual_machine` | bool | Whether running in VM | `false` for bare metal |
| `high_performance` | bool | CPU in performance mode | `true` |
| `system` | string | Kernel name (e.g. `Linux`) | `Linux` |
| `node` | string | Hostname | — |
| `release` | string | Kernel release (e.g. `5.10.0-xxx`) | — |
| `version` | string | Kernel version string | — |
| `machine` | string | Architecture (`aarch64` / `x86_64`) | — |
| `processor` | string | CPU architecture | — |
| `transparent_hugepage` | string | THP status | Workload-specific; value is `always`, `madvise`, or `never` |
| `page_size` | int | Memory page size in bytes | Architecture/software-specific |
| `overcommit_memory` | string | Memory overcommit policy | `0` |

---

## ascend

Ascend component versions. Each component is a dict with version/timestamp/commit fields.

```json
{
  "driver": {"version": "24.1.0"},
  "toolkit": {"version": "8.0.0", "timestamp": "2025-01-01 00:00:00"},
  "opp_kernel": {"version": "8.0.0"},
  "mindstudio_toolkit": {"version": "8.0.0"},
  "atb": {"version": "x.x.x", "commit": "abc123"},
  "mindie": {"version": "x.x.x", "timestamp": "..."},
  "atb-models": {"version": "x.x.x", "time": "...", "commit": "abc123"}
}
```

### Components

| Component | version.info Path | Version Keys | Notes |
|-----------|-------------------|--------------|-------|
| `driver` | `/usr/local/Ascend/driver/version.info` | `version` | Absolute path, always at fixed location |
| `toolkit` | `$ASCEND_TOOLKIT_HOME/toolkit/version.info` | `version`, `version_dir` | Default: `/usr/local/Ascend/ascend-toolkit/latest/` |
| `opp_kernel` | `$ASCEND_TOOLKIT_HOME/opp_kernel/version.info` | `version`, `version_dir` | Same base as toolkit |
| `mindstudio_toolkit` | `$ASCEND_TOOLKIT_HOME/mindstudio-toolkit/version.info` | `version` | Same base as toolkit |
| `atb` | `$ATB_HOME_PATH/../../version.info` | `ascend-cann-atb version` | Default: `.../atb/latest/atb/cxx_abi_0` |
| `mindie` | `$MINDIE_LLM_HOME_PATH/../version.info` | `ascend-mindie` | Default: `.../mindie/latest/mindie-llm` |
| `atb-models` | `$ATB_SPEED_HOME_PATH/version.info` | `atb-models version` | Default: `/usr/local/Ascend/atb-models` |

An empty `{}` in older dumps means no version evidence was obtained. It does not establish that the component is uninstalled. Version 1.1 records the attempted path and collection status.

---

## env

All environment variables or the filtered Ascend-related subset, with sensitive values masked. This is the collector process environment, not necessarily the service environment. Optional tuning variables being unset is not by itself a failure.

When `--filter` is used, the critical variables listed below are retained when set, in addition to names containing these substrings:
`ASCEND`, `MINDIE`, `ATB_`, `HCCL_`, `MIES`, `RANKTABLE`, `GE_`, `TORCH`, `ACL_`, `NPU_`, `LCCL_`, `LCAL_`, `OPS`, `INF_`

### Critical Environment Variables

| Variable | Purpose |
|----------|---------|
| `ASCEND_HOME_PATH` | Ascend driver home |
| `ASCEND_TOOLKIT_HOME` | CANN toolkit home |
| `LD_LIBRARY_PATH` | Dynamic library search path (must include Ascend libs) |
| `MINDIE_LLM_HOME_PATH` | MindIE-LLM installation path |
| `ATB_HOME_PATH` | ATB library path |
| `ATB_SPEED_HOME_PATH` | ATB-Models installation path |
| `HCCL_BUFFSIZE` | HCCL communication buffer size |
| `TASK_QUEUE_ENABLE` | Task queue feature switch |
| `RANK_TABLE_FILE` | Path to rank table file |
| `OMP_NUM_THREADS` | OpenMP thread count |
| `PYTORCH_NPU_ALLOC_CONF` | PyTorch NPU memory allocation config |

---

## mies config

MindIE service `config.json` file content (raw JSON object).

Typically located at `/usr/local/Ascend/mindie/latest/mindie-service/conf/config.json`.

Key fields to analyze:
- `BackendConfig.ModelDeployConfig.ModelConfig[*].modelWeightPath`
- `BackendConfig.ModelDeployConfig.ModelConfig[*].modelType`
- `BackendConfig.ModelDeployConfig.ModelConfig[*].npuDeviceIds`
- `ServeConfig.ip` / `ServeConfig.port`
- `SchedulerConfig.maxBatchSize`
- `SchedulerConfig.maxPrefillBatchSize`

---

## user config

`user_config.json` for large EP / PD disaggregation scenarios.

---

## mindie env

`mindie_env.json` for PD disaggregation / large EP scenarios.

---

## model config

`config.json` from the model weight directory (HuggingFace-style model config).

Key fields:
- `model_type` — model architecture type
- `torch_dtype` — validate against the actual model and runtime support; do not assume only `float16` is valid
- `transformers_version` — metadata to check against actual compatibility requirements, not a universal installed-version bound
- `hidden_size`, `num_attention_heads`, `num_hidden_layers`

---

## weight

SHA256 hashes of `.safetensors` weight files.

```json
{
  "00001": "abc123def456...",
  "00002": "789abc012def...",
  "model": "fff000eee111..."
}
```

Key is the tensor ID extracted from filename pattern `(\d{5})-of-\d{5}.safetensors`, or the full basename if pattern doesn't match.

---

## ping

Ping results for each host in the rank table.

```json
{
  "192.168.1.1": "PING 192.168.1.1 ... 3 packets transmitted, 3 received, 0% packet loss, time 2003ms\n...",
  "192.168.1.2": "ping failed"
}
```

Parse the complete loss percentage; substring matching `0% packet loss` also matches `100% packet loss`. Check command/collection errors first.
Bad: contains `100% packet loss`, `ping failed`, or error message

---

## hccl

HCCL HCCS ping results between NPU devices.

```json
{
  "/usr/local/Ascend/driver/tools/hccn_tool -i 0 -hccs_ping -g address 192.168.1.2": [0, "output..."],
  "/usr/local/Ascend/driver/tools/hccn_tool -i 0 -ping -g address 192.168.1.2": [1, "output..."]
}
```

Key is the full command string. Value is `[return_code, output_string]`.

Good: return code `0` and output contains `3 received`
Bad: non-zero return code or output contains `100% packet loss`

---

## link

Link status for each NPU device (output of `hccn_tool -i N -link -g`).

```json
[
  "link status: UP\n...",
  "link status: UP\n...",
  "link status: DOWN\n...",
  "link status: UP\n..."
]
```

For version 1.1, array position maps through `_meta.collection.link.device_ids`; device IDs can be sparse. Older dumps used a contiguous-ID assumption. Check collection errors before interpreting link output.

---

## vnic

VNIC status for each NPU device (output of `hccn_tool -i N -vnic -g`).

Only relevant for A3 boards. Each entry should have:
- `link status: UP`
- IP address configured
- Netmask configured

---

## tls

TLS certificate status for each NPU device (output of `hccn_tool -i N -tls -g`).

```json
[
  "tls switch[0] : 0\n...",
  "tls switch[0] : 0\n..."
]
```

`tls switch[0]` value:
- `0` = TLS disabled (expected for non-TLS deployments)
- `1` = TLS enabled

---

## hardware

Hardware resources: CPU topology/runtime state, memory, kernel tunables, clock, disk, PCIe/NUMA topology. Sub-fields degrade gracefully (with `error`/`raw` notes) when sysfs or commands are unavailable.

| Field | Type | Description | Expected |
|-------|------|-------------|----------|
| `cpu_topology` | dict | `socket_count` / `numa_node_count` / `physical_cores` / `logical_cpus_online` / `numa_cpu_map` / `socket_cpu_map` / `raw` (lscpu -p) | counts > 0 on physical hosts |
| `cpu_runtime` | dict | Per-core `governor` / `cur_freq` / `online` state | governor `performance` for inference hosts |
| `memory` | dict | From `/proc/meminfo`: `MemTotal` / `MemAvailable` / `SwapTotal` / `SwapFree` (KB) | swap usually disabled on training hosts |
| `kernel_params` | dict | `vm.swappiness` / `vm.max_map_count` / `vm.overcommit_memory` / `fs.file-max` / `kernel.numa_balancing` / `kernel.core_pattern` / `limits` (ulimit snapshot) | see per-key expectations below |
| `clock` | dict | `timedatectl_raw` (NTP sync state) | `NTP synchronized: yes` |
| `disk` | dict | `filesystems` (df) / `block_devices` (lsblk) / `bios_bmc` (dmidecode) / raw | weight disk free > model size |
| `pcie_numa` | dict | `npu_pcie_devices` / `npu_numa_map` / `nic_pcie` / `numactl_raw` / `lspci_npu_raw` | NPU/NIC NUMA affinity consistent |

Illustrative tuning values, not universal pass/fail requirements. Apply only with workload-specific deployment evidence:
- `vm.swappiness` = `0`~`10` for inference/training hosts
- `kernel.numa_balancing` = `0` (avoid NUMA migration jitter)
- `ulimit nofile` >= `655350`, `memlock` = `unlimited`

---

## npu

NPU runtime state via `npu-smi` plus device nodes and log dirs. `count` is the detected NPU count; per-device details live in `devices` when `npu-smi` is available.

| Field | Type | Description | Expected |
|-------|------|-------------|----------|
| `count` | int | Number of NPUs detected | matches board spec (e.g. 8) |
| `devices` | list | Per-device dict: `device_id` / `name` / `health` / `temperature` / `power` / `aicore_util` / `hbm_util` / `ecc` | all devices uniform; no `Error`/overheat |
| `board` | dict | `npu-smi info -t board` snapshot (firmware version etc.) | firmware consistent across hosts |
| `device_nodes` | dict | `/dev/davinci*`, `davinci_manager`, `devmm_svm`, `hisi_hdc` stat info (mode/owner) | readable for the service user; critical in containers |
| `log_dirs` | dict | `~/ascend/log` dir sizes and latest mtimes | — |
| `optical` | dict | `hccn_tool` optical/port transceiver snapshot (host only) | — |
| `note` | string | Degradation reason when `npu-smi` is absent | — |

---

## runtime

Software runtime: Python environment, watched pip packages, inference processes, container/cgroup context.

| Field | Type | Description | Expected |
|-------|------|-------------|----------|
| `python_version` / `python_executable` / `pip` | string | Interpreter and pip identity | matches deployment env |
| `watched` | dict | Key packages: `torch` / `torch-npu` / `vllm` / `vllm-ascend` / `transformers` / `mindspore` / `numpy` / `triton` / `onnx` / `onnxruntime` | version matrix consistent across ranks |
| `pip_list_raw` | list | Full `pip list --format=freeze` fallback | — |
| `targets` | list | Matching processes (`mindie` / `vllm` / `torchrun` / `python`): `pid` / `ppid` / `cmdline` / `threads` / `cpus_allowed_list` / `status` | affinity covers multiple cores, not just CPU0 |
| `in_container` | bool | Multi-signal container detection (dockerenv / cgroup markers / cgroup v2 root / PID1) | `false` on bare metal |
| `container` | dict | cgroup version, `cpuset`, memory limit, `/dev` NPU passthrough, mounts (containers only) | NPU devices fully mapped |
| `npu_devices_in_dev` | list | `/dev/davinci*` entries visible to this process | 8 on an 8-card host |

---

## network

Network details: NIC state, routes, RDMA/RoCE GIDs, TCP listeners, and inter-rank port reachability (rank table hosts).

| Field | Type | Description | Expected |
|-------|------|-------------|----------|
| `nics` | list | Per-NIC: `name` / `mtu` / `speed_mbps` / `duplex` / `operstate` / `mac` / `driver` / `bond` info | all ranks `UP`, same speed/MTU |
| `mtu_consistent` | bool | Whether all NIC MTUs agree | `true` |
| `routes` | dict | `ip route` / `ip -6 route` / `default_gateway` | — |
| `rdma` | dict | `/sys/class/infiniband` GID table per port + `ibv_devinfo` raw | present when RoCE enabled |
| `tcp_listen` | list | Local LISTEN ports parsed from `/proc/net/tcp(6)` | — |
| `peers` | dict | Per-rank-host TCP probe results (business ports from local listeners, max 8): `open` / `filtered` / `refused` / `unreachable` | business ports `open` on peer ranks |
| `devices` / `error` / `note` | — | Degradation info when sysfs/tools unavailable | — |

Note: ICMP ping success does not imply business port reachability; use `peers` for service-level connectivity checks.
