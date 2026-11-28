# plog / slog / device / 框架 / dmesg 日志

## 用途

按问题时间窗收集 CANN 平台日志、Device 日志、Host 内核日志与训练/推理框架日志，交给 `issue-analyzer` 做日志取证：清单、错误提取、聚合与回验。

## 适用环境

- Linux 宿主机或容器。
- 业务用户可读 `~/ascend/log/plog/`；`dmesg`、`/var/log/messages` 和部分 Device 日志需要 root。
- 不同 CANN 版本的日志目录可能不同，先用实际目录核对，不要假设固定路径。

## 权限与影响

- 只读：列目录、读日志、打包。
- 不改日志级别、不重启 slogd、不重启业务进程。
- 打包前按问题时间窗核对日志和轮转文件，保留原始行及前后上下文。

## 采集命令

先确定问题发生的时间窗和受影响 rank。以下命令按现场路径调整。

```bash
# 问题时间窗；按实际时间替换
START="2026-08-28 10:00"
END="2026-08-28 10:40"

# 内核日志
dmesg -T > dmesg_$(hostname)_$(date +%Y%m%d_%H%M).log

# 系统日志（有 journalctl 时）
journalctl --since "$START" --until "$END" > journal_$(hostname).log

# NPU 设备状态与故障历史（问题复现时采最准）
npu-smi info > npu_smi_info_$(hostname).txt
npu-smi info -t board -i 0 > npu_smi_board_0.txt
npu-smi info -t fault -i 0 > npu_smi_fault_0.txt

# plog：列出从问题开始后仍有写入的候选文件
PLOG_DIR="$HOME/ascend/log/plog"
find "$PLOG_DIR" -type f -name '*.log*' -newermt "$START" -print

# 框架 / rank 日志：nohup.out、torchrun 输出、各 rank 目录，按现场实际路径打包
FRAMEWORK_LOG_DIR="./framework-logs"
tar -czf "framework_$(hostname).tar.gz" -- "$FRAMEWORK_LOG_DIR"
```

按日志内时间戳检查候选文件和相邻轮转文件。保留覆盖问题窗口的文件，包括事后仍在写入的活动日志。上面的 `find` 按文件修改时间筛选。

在可写的交付目录中运行以下命令。把示例文件名换成上一步选出的相对路径，涵盖受影响的 Host 和 Device 日志。

```bash
tar -czf "plog_$(hostname)_window.tar.gz" -C "$PLOG_DIR" -- "host/host-0.log" "device/device-0.log"
```

`npu-smi` 的子命令与参数随版本不同，先用 `npu-smi info -h` 核对；不支持 `-t fault` 时保留 `npu-smi info` 输出即可。

## 客户需要返回

- `plog_<host>_window.tar.gz`
- `dmesg_<host>_<时间>.log`
- `journal_<host>.log`（有则给）
- `npu_smi_info_<host>.txt`，以及按卡采集的 board/fault 输出（有则给）
- 训练/推理框架日志与各 rank 输出
- 问题时间窗、受影响 rank、任务启动时间

工程师收到归档后先解包，再将一个日志目录或一个或多个日志文件传给 `issue-analyzer`。

## 敏感信息

日志可能含 IP、路径、模型名、账号与业务数据。按客户要求脱敏后再流转；不要把无关时间窗的整包日志一起发出。

## 注意

- 日志已被滚动覆盖时如实说明，不要用其他时间窗的日志顶替。
- 多机时先核对各机时钟，再比较「哪个 rank 先报错」。
- Device 日志文件名通常含 `device-<id>`；Host 日志含 `host`，按实际扫描结果确认。
