---
name: ibmc_analyzer
description: 分析华为 iBMC 一键收集/带外日志，判断服务器硬件健康（BMC 层）。当用户给出 dump_info 目录或 BMC 日志压缩包，要求判断机器/BMC 是否健康、汇总硬件问题、多机对比找配置木桶效应、或生成诊断报告时使用。触发词：BMC日志、iBMC日志、一键收集、bmc log、带外日志、分析BMC、BMC健康、BMC诊断报告、BMC对比、多机BMC。不用于 OS/应用层日志故障排查（用 issue-analyzer）；不用于昇腾环境配置快照与比对（用 ascend-dump-analyzer）。
---

# BMC 一键收集日志 → 结构化 JSON + 精美 HTML 报告

一条命令把用户的 iBMC 一键收集日志变成「结论 + 各维度证据 + 问题分级」的专业报告，
让分析人员快速 get 整机情况，并把关键数据沉淀为可复用的 JSON。

## 为什么这样做

- 现网报障时，用户的 iBMC 一键收集包含几十~上百个文件。逐个人工读既慢又容易漏。
- 交付标准（Atlas 26.1.0 一本通 + 判定标准手册 `bmc_reference.md`）给出**每个维度的量化"正常"值**（PSU Vin≈220V、NPU ECC=0、光模块 SNR≥19dB、Inlet<42°C…）。
- 把"哪些文件、读哪些字段、按什么阈值判断"固化成脚本，每次分析结果可复现、可对比。
- 最终产物 JSON（机器/数据 + 判定）+ HTML（人看的报告）两者都留，既给人看也给机器用。

## 适用输入（确定根目录）

1. 解压到的目录，内含 `dump_info/` 子目录（标准一键收集结构）。
2. 直接给出 `dump_info` 目录。
3. 机器目录（如 `HuaKunAT3500G3_SN_时间戳/`），其内含 `dump_info/`。

脚本的 `ensure_root()` 会自动归一化。多台机器可一次传入多个目录（用于集群对比）。

> ⚠️ 若用户给的是压缩包（`.tar.gz` / `.zip`），可先解压到工作区再分析；`run_bmc_report.py` 也支持直接传入压缩包（自动解压）。

## 关键文件清单（按表5-79）与"读什么"

判定权重降序：`当前活动告警 → 电源 → NPU/ECC → 光模块 → 温度/风扇 → RAID → BMC自身 → 指示灯 → 版本 → 网络`。

| 权重 | 文件（dump_info/ 下） | 读出内容 | 正常标准 |
|------|----------------------|---------|---------|
| ★1 | `AppDump/sensor_alarm/current_event.txt` | 当前活动告警 | 空=正常；仅安全Minor=基本正常；有Critical=不正常 |
| 2 | `AppDump/BMC/psu_info.txt` 或 `server_config.txt` | PSU 在位/Vin/Vout/输入模式 | 4个全 present，Vin≈220V(180~264V)，Vout≈12V(11.5~12.6V) |
| 3 | `AppDump/CpuMem/npu_info` + `npu_ecc_info.json` | NPU数量/功率/ECC单双bit | 8卡；ECC 单/多bit=0（多bit>0=硬件故障 P0） |
| 4 | `AppDump/CpuMem/NpuIO/optical_module_static_info` + `port_history_log` | 光模块在位/类型 + 端口 up/down 抖动 | 8个在位；SNR≥19dB；端口频繁抖动需关注 |
| 5 | `AppDump/sensor_alarm/sensor_info.txt` | 全部传感器实时值/状态 | 温度全 ok，Inlet<42°C，NPU HBM<95°C；风扇 7000+RPM |
| 6 | `AppDump/StorageMgnt/RAID_Controller_Info.txt` | 控制器/BBU/逻辑盘/物理盘/PHY误码 | Controller/BBU/磁盘全部 Normal；生产机有逻辑盘 |
| 7 | `AppDump/sensor_alarm/sel.db` | SEL 历史事件（SQLite） | 关注 Critical/Major；当前告警要与历史分开 |
| 8 | `AppDump/sensor_alarm/LedInfo` | SysHealLED/Fan LED | SysHealLED=GREEN/ON，非 RED/BLINKING |
| 9 | `RTOSDump/versioninfo/app_revision.txt` + server_config.txt | iBMC/BIOS/CPLD/NPU 版本 | 对照机型推荐版本（见 references/versions.md） |
| 10 | `AppDump/NetConfig/net_info.txt` | 网络配置/VLAN 使能 | IPv6(SN场景)=手动；Dedicated VLAN=关闭 |

**硬件与系统维度（v2 新增，全面补齐）**：

| 维度 | 文件 | 读出内容 |
|------|------|---------|
| CPU | `AppDump/CpuMem/cpu_info`（**逗号分隔**） | 槽位/型号/核数/线程/L1L2L3/SN |
| 内存 | `AppDump/CpuMem/mem_info`（**逗号分隔**） | DIMM 列表/容量/速率/类型/健康列 |
| 风扇详情 | `AppDump/cooling_app/fan_info.txt`（管道分隔） | 前后转速/PWM/最大范围/型号 |
| 扣卡 | `AppDump/card_manage/card_info` | PCIe扣卡/Riser/硬盘背板 |
| 寄存器 | `Register/cpld_reg_info`,`cpu_reg_info`,`vrd_reg_info` | CPLD/CPU/VRD 寄存器 dump |
| License | `AppDump/LicenseMgnt/lm_info` | ESN / ALM 版本 / License 状态 |
| SP 资产 | `SpLogDump/version.json`,`deviceinfo.json` | SP OS/APP 版本、资产信息 |
| Nginx | `3rdDump/nginx*.conf` 等 | Nginx 配置（存在性+大小） |
| 时区/NTP | `AppDump/BMC/time_zone.txt`,`ntp_info.txt`,`OptPme/pram/BMC_HOSTNAME` | 时区/NTP/主机名 |
| iBMC 系统 | `RTOSDump/sysinfo/*`（uptime/loadavg/meminfo/df_info/free_info） | iBMC 运行时长/负载/内存/分区 |
| 网络 OS | `RTOSDump/networkinfo/*`（ifconfig/route/resolv/ipinfo） | iBMC 网口 IP/路由/DNS |
| 利用率 | `OptPme/pram/*_webview.dat`（power/env/cpu/mem），`PowerMgnt/power_statistics.csv` | 功率/环境温度/CPU内存利用率曲线 |

> ⚠️ **真实文件格式注意**（已验证）：
> - `cpu_info` / `mem_info` 是**逗号分隔**（字段内可能含 `|` 如 "64-bit Capable| Multi-Core"），用 `,` 分割。
> - `psu_info.txt` / `sensor_info.txt` / `fan_info.txt` 是**管道分隔**。
> - `fruinfo.txt` 位于 `AppDump/FruData/`（不是 `AppDump/BMC/`）。
> - `cpu_utilise_webview.dat` 常只含元数据（无曲线点）；`env_web_view.dat` 是 `时间#温度` 行。
> - **Parse 脚本已经按这些真实格式编写，改机型时以真实文件为准微调解析函数。**

辅助/深挖：`PowerMgnt/power_statistics.csv`（功率统计）、`LogDump/*`（操作/安全/维护日志、
ps_black_box 电源黑匣子）、`OSDump/*.rep`/`img*.jpeg`/`systemcom*.tar`（OS录像/截图）、
`Register/vrd_reg_info`（电压纹波）、`3rdDump/*`（Nginx 等3rd日志）。

`LogDump/remote_log`（syslog 聚合）是 **SEL 的补充证据源**——当 SEL 不完整或想确认
NPU 健康降级/电源/端口事件的精确时间线时读它：日志会解析出 `syslog_events`
（含 `npu_health` / `power_events` / `link_events`）。NPU "degraded ... Error Code:
非NA" 多为瞬时降级随后恢复，需与 OS/npu-smi 对齐确认。

## 工作流程

### STEP 1 — 解压（如需要）

把压缩包解压到工作区，确认 `dump_info/` 存在。

### STEP 2 — 运行解析器 → JSON

```bash
python <skill>/scripts/parse_bmc_collect.py <日志根目录1> [根目录2 ...] -o <输出目录>
```

- **无论单机/多机，每台机器都会输出** `<输出目录>/<机器目录名>_bmc.json`，覆盖该机器
  dump_info 下**所有文件的信息**，并按领域分块组织：

```json
{
  "identity":       {产品名/SN/主板/生产日期...},
  "versions":       {iBMC/BIOS/CPLD/SDK/RTOS 版本},
  "bios":           {count, items:[{name,value,display_name,help_text,menu_path,default}]},
                    // BIOS 全量配置（currentvalue.json 全项 + registry.json 配对说明/菜单路径）
  "current_event":  {当前活动告警},
  "led":            {指示灯},
  "sensors":        [全部传感器], "sensor_problems": [异常传感器],
  "psu":            [电源], "cpu": [CPU], "memory": {DIMM+统计},
  "fan_detail":     [风扇], "npu": [NPU], "npu_ecc": {ECC},
  "optical":        {光模块/端口}, "raid": {控制器/逻辑盘/物理盘},
  "network":        {EthGroup}, "network_os": {ifconfig/route/DNS},
  "time_config":    {时区/NTP/主机名}, "ibmc_sys": {uptime/负载/内存/分区},
  "cards":          {PCIe扣卡/Riser/背板}, "register": {CPLD/CPU/VRD},
  "license":        {ESN/License状态}, "sp_asset": {SP版本/资产},
  "nginx":          {Nginx配置}, "utilization": {功率/温度/利用率曲线},
  "nand":           {NAND寿命/写入量}, "lldp": {LLDP}, "mcinfo": {BMC MCU},
  "sel":            {SEL事件+统计}, "logs_summary": {日志清单},
  "syslog_events":  {NPU/电源/链路事件}, "osd_files": {OS录像},
  "parsed_files":   {表5-79 文件命中/缺失清单},
  "health":         {verdict/counts/issues}, "ranks": {42+ 项扁平关键指标}
}
```

  用 `identity.product_sn` 定位 SN；`ranks` 是所有关键指标的扁平汇总（供对比矩阵/速览用）。

- **多台时额外输出 `all_machines_bmc.json`**，结构：

```json
{
  "machines": [ <每台完整 JSON> ],
  "count": 8,
  "comparison": {
    "fields": ["product_sn","npu_count","psu_vin","inlet_temp", ...],
    "machines": [ {"machine_tag":"...","product_sn":"...","verdict":"...",
                   "counts":{...}, "fields":{ <字段→值矩阵> }} ]
  }
}
```

- **BIOS 全量配置**：`bios.items` 含 currentvalue.json 的全部项（276+），每项带
  `display_name`（中文名）、`help_text`（帮助说明）、`menu_path`（BIOS 菜单路径）、
  `default`（默认值）——来自 registry.json 的官方定义，是报告"参数说明列"的数据源。

- **`health` 结构**（脚本判定结果，报告据此渲染）：

```json
{
  "verdict": "正常|基本正常（存在需关注项）|有风险|不正常",
  "counts": {"P0":0,"P1":0,"P2":1,"P3":1,"OK":0},
  "issues": [ {"level":"P2","topic":"...","detail":"证据(文件+数值)"} ]
}
```

- `parsed_files` 记录表5-79 关键文件命中/缺失清单（可追溯性）。
- 健康判定只读源码 `score_health()` 可增量改进；先跑通再调阈值。

### STEP 3 — 核对手工判读（关键！）

脚本是"第一遍筛选"，**结论必须能追溯到具体文件+数值**。重点人工复核：

1. `current_event.txt` 是否与 SEL 历史冲突？→ 以当前快照为准，历史 Critical 标 P3 已恢复。
2. PSU 当前 Vin/Vout 是否真正常？（避免把历史掉电当当前故障）
3. 逻辑盘/物理盘是否与交付规划一致？（直通 HBA 不算"无逻辑盘"错误）
4. SEL 异常重启是 `[Chassis control][LOCAL]`（主动）还是 `[IPMB]`/watchdog（异常）？
5. `syslog_events.npu_health` 里 NPU "degraded + Error Code 非NA" 是否集中在某个时间点
   （可能是掉电/链路抖动引发的瞬时降级，而非持续硬件故障）。

### STEP 4 — 生成 HTML 报告

```bash
python <skill>/scripts/generate_bmc_report.py <json1> [json2 ...] -o <报告.html>
# 或传入一个 all_machines_bmc.json
```

生成器**根据机器数量自动切换模板**：

- **单机模板**：左侧固定导航（结论→身份版本→告警→指示灯→电源→CPU内存→NPU/ECC→
  光模块→温度风扇→RAID→网络→BMC系统/扣卡/寄存器→NAND/LLDP→**BIOS 配置全量**→
  利用率曲线→SEL→日志OS→文件清单→问题清单）。分析先行（判定卡 + 关键指标速览 +
  置顶问题清单），随后每维度展开详情。**BIOS 配置区**列出全部项（参数名/默认值/当前值/参数说明+菜单路径）。
- **多机对比模板**：左侧固定导航（集群总结论→问题主题分布→逐维度对比矩阵→
  分块对比：身份版本/硬件配置/温度健康/RAID存储/网络/**BIOS配置**/SEL事件/资产OS→
  各机器详情）。分析先行（集群级判定 + 健康分条形 + 逐机判定表），随后：
  - **逐维度对比矩阵**：每行一个参数、每列一台机器、**最后一列是该参数的说明**
    （BIOS 参数用 registry.json 的 DisplayName/HelpText/菜单路径；其它参数用内置字典）；
  - **BIOS 配置块**：全部 BIOS 项横向比对（各机当前值 + 说明列）；
  - 各机不一致的参数**黄色高亮**，快速定位配置漂移/差异；
  - 最后每台机器可折叠详情。
- 报告先结论、后证据、可点击导航，适合专业分析人员快速 get 整机情况。

### STEP 5 — 输出结论给用户

- **判定维度**（权重降序）：当前告警 > 电源 > NPU/ECC > 光模块 > 温度 > RAID > BMC自身 > 指示灯 > 版本 > 网络。
- **问题分级**：P0🔴 当前Critical/掉电/NPU丢失；P1🟡 日志满/证书/温度Major史/磁盘异常；
  P2🟢 版本旧/无逻辑盘/端口抖动/异常重启较多；P3⚪ 安全弱项/已恢复历史事件。
- **异常重启怎么判（不要只看次数）**：先统计 `System Restart [Unknown][IPMB]` / watchdog 型重启的**时间分布**——
  - 若集中在**交付/上架窗口**（常与 operate_log 里 KVM 引导、BIOS 写盘、MCU/BMC 固件升级节奏吻合），且之后长时间无重启，
    → 判为**交付期历史事件**，写 P3/提示观察，**不是当前硬件故障**；
  - 若重启**持续出现到最近**（覆盖用户报障时间点）→ 才是 P2 需要关联 OS/dmesg/掉电时间线定位。
  - 用 `operate_log`（用户/升级操作）与 `sel.db` 时间线对齐，能极大提升结论准确度。
- **端口 down 风暴 ≠ 光路故障**：`remote_log` 里若**几乎所有端口（NIC/FLEX IO/PCIe 卡）在几秒~几分钟内同时 down 再 up**，
  通常是**系统重启/下电重启时的网卡初始化伴随现象**，要与 SEL 里的 System Restart / 掉电事件**对齐时间点**再判断；
  只有**个别端口**高频 flapping 才指向光模块/线缆/对端。整体端口同时断开应归因于系统重启，而非单点硬件。
- **SEL 里的 "Sensor access degraded"**：是**历史**事件（时间在 SEL 里），必须与当前 `sensor_info.txt` 交叉——
  当前对应传感器 status=ok → 已恢复，判 P3；当前仍不可读/异常 → 才 P2。
- **禁忌**：
  - 不要把「已恢复的历史掉电(SEL)」当当前故障（对当前快照）。
  - 不要把「版本旧」当硬件故障（P2 建议升级即可）。
  - 不要把「集合通信不达标」当 BMC 故障（先查 `ASCEND_GLOBAL_LOG_LEVEL`=1→改3）。
  - `port_history_log` 的 NPU link up/down 是 OS/参数面信息，要与 SEL 时间线对齐。

## 自定义与扩展

- **新增文件/字段**：在 `parse_bmc_collect.py` 加一个 `parse_xxx()`，在 `parse_one()` 挂载。
- **调整阈值**：改 `RULES` 字典（PSU/NPU/光学/温度/风扇…）。
- **报告样式**：改 `generate_bmc_report.py` 顶部 `CSS` / `JS`。

## 交付物建议

```
单机：
<输出目录>/
├── <机器目录名>_bmc.json                # 结构化数据（分块覆盖该机全部文件信息；SN 在 identity.product_sn）
└── BMC诊断报告_<机型>_<SN>.html         # 单机分析报告（左导航 + 分析先行 + BIOS 全量）

多机（集群）：
<输出目录>/
├── <机器1>_bmc.json ... <机器N>_bmc.json # 每台机器独立 JSON（每台都出，分块）
├── all_machines_bmc.json                 # 多机合并 + comparison 字段×机器矩阵
└── BMC诊断报告_集群对比_N台机器.html      # 集群对比报告（分块全参数比对 + 参数说明列 + 各机器详情）
```

> 在 Windows 控制台运行时，脚本中文 stdout 可能乱码（cp936），**文件本身是 UTF-8 不受影响**。
> 若要控制台正常显示中文，先 `set PYTHONIOENCODING=utf-8`（`run_bmc_report.py` 已自动处理）。

## 参考

- `references/versions.md` — 各机型 iBMC 推荐/最低版本与固件包名。
- `references/judgement.md` — 正常/异常量化标准与 SEL 解读速查（提炼自 bmc_reference.md）。
- `references/file_inventory.md` — 表5-79 完整文件收集项说明（可按需查）。
