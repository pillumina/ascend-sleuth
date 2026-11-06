# iBMC 一键收集 目录/文件 说明（按表5-79 整理，实用向）

> 完整官方说明以交付文档「表5-79 一键收集信息说明」为准。这里给出**分析时最常用的入口**。

## 顶层（dump_info/ 下）

| 文件 | 内容 | 用途 |
|------|------|------|
| `dump_app_log` | 各模块 dump 是否成功（含 begin/finish 时间） | 判定收集完整性（`dump sensor_alarm failed` 说明告警文件可能缺失） |
| `dump_log` | 一键收集结果列表 | 收集时间（`begin at ...`） |

## AppDump/—— 核心

| 目录/文件 | 读什么 |
|-----------|--------|
| `sensor_alarm/current_event.txt` | ★当前活动告警（首要判定） |
| `sensor_alarm/sensor_info.txt` | 全部传感器实时值 + 阈值（温度/电压/风扇/PSU） |
| `sensor_alarm/sel.db` | SEL 事件库（SQLite，表 `sel_data`） |
| `sensor_alarm/LedInfo` | 系统健康灯/风扇灯 |
| `sensor_alarm/cache_event_log.db` | 未上报订阅事件 |
| `BMC/psu_info.txt` | PSU 在位/Vin/Vout/输入模式 |
| `FruData/fruinfo.txt` | FRU 身份：产品名/SN/主板/板卡 |
| `BMC/nandflash_info.txt` | NAND flash 信息 |
| `CpuMem/npu_info` | NPU 数量/功率/单双ECC |
| `CpuMem/npu_ecc_info.json` | NPU ECC 明细（单/多bit + 隔离页） |
| `CpuMem/NpuIO/optical_module_static_info` | 光模块在位/SN/类型 |
| `CpuMem/NpuIO/port_history_log` | NPU 参数面端口 up/down 时间线 |
| `cooling_app/fan_info.txt` | 风扇型号/转速/PWM |
| `NetConfig/net_info.txt` | 网络配置（IP/IPv6/VLAN 使能/MAC） |
| `StorageMgnt/RAID_Controller_Info.txt` | RAID 控制器/BBU/逻辑盘/物理盘/PHY 误码 |
| `PowerMgnt/power_statistics.csv` | 功率统计曲线 |
| `BMC/time_zone.txt` | iBMC 时区 |
| `BMC/ntp_info.txt` | NTP 同步失败错误信息 |
| `CpuMem/cpu_info` | CPU 槽位/型号/核数/缓存/SN（逗号分隔） |
| `CpuMem/mem_info` | DIMM 内存明细（容量/速率/厂商/健康，逗号分隔） |
| `card_manage/card_info` | PCIe 扣卡 / Riser / 硬盘背板 |
| `LicenseMgnt/lm_info` | ESN / ALM 版本 / License 状态 |
| `UPGRADE/upgrade_info` | MCU/Ascend/CPLD 等器件版本 |
| `NetConfig/lldp_info.txt` | LLDP 配置/报文统计 |

## RTOSDump/—— iBMC 系统

| 文件 | 读什么 |
|------|--------|
| `versioninfo/app_revision.txt` | iBMC/BIOS/CPLD/SDK 版本 |
| `versioninfo/ibmc_revision.txt` | commit + baseversion |
| `versioninfo/server_config.txt` | CPU/内存/卡/风扇/PSU/RAID 概览（**全维度一次看全**） |
| `versioninfo/RTOS-Release` | RTOS 版本 |
| `sysinfo/*` | 内核/内存/负载/进程（排查 iBMC 自身问题） |
| `networkinfo/*` | ifconfig/IP/hosts/NTP 等 |

## LogDump/—— 深挖

| 文件 | 用途 |
|------|------|
| `operate_log` | 用户操作日志 |
| `security_log` | 安全日志 |
| `maintenance_log` / `strategy_log` | 维护/策略日志 |
| `ps_black_box.log` | 电源黑匣子（掉电原因） |
| `dmesg_info` / `linux_kernel_log` | 内核环形缓冲/启动（OS 层关联） |
| `kbox_info` | 24h 周期 kbox 信息 |
| `bmccom.dat` | BMC 串口日志 |
| `tmp_PD_SMART_INFO_C*` | 磁盘 SMART |
| `storage/phy/*.csv` | RAID PHY 误码 |
| `storage/IODeterioration.db` / `SubhealthyStatus.db` | 慢盘/亚健康 |
| `app_debug_log_all` | 所有应用调试日志（大，按需） |

## OptPme/pram + save/—— 配置持久化

`per_config*.ini`（iBMC 配置）、`Snmp_*`、`User_*`、`sensor_alarm_sel.bin*`（SEL 原始）。

> 锁/校验文件（.md5/.sha256）一般不用看。

## OSDump/—— OS 层

| 文件 | 用途 |
|------|------|
| `img*.jpeg` | 业务侧最后屏幕（文件名含时间戳） |
| `video_poweroff.rep` / `systemcom*.tar` | 下电录像 / 串口 |
| `video_caterror_rep_is_deleted.info` | 超大录像被删提示 |

## SpLogDump / BMALogDump / CoreDump / DeviceDump / Register / 3rdDump

- `SpLogDump/*`：SP 日志（dmesg/operatelog/maintainlog/version.json）—— **SP 运行时通常无法收集**。
- `BMALogDump/bma_debug_log`：iBMA 日志。
- `CoreDump/core-*`：应用 core dump（大量存在=异常）。
- `DeviceDump/*`：器件级 dump（按需）。
- `Register/*_reg_info`：CPLD/CPU/VRD 寄存器。
- `3rdDump/*`：Nginx 访问/错误日志与配置。
