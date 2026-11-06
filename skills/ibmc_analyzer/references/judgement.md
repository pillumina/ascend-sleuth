# BMC 正常/异常判定标准速查（提炼自判定标准手册 bmc_reference.md）

> 用途：判读 `parse_bmc_collect.py` 的输出与 HTML 报告时，快速对齐"正常 / 异常 / 分级"口径。

## 1. 全局结论规则

| 当前告警情况 | 全局结论 | 对应级别 |
|---|---|---|
| 当前告警列表为空 | 机器正常 | OK |
| 仅有安全类 Minor（SNMP v2、RMCP 弱加密套件等） | 基本正常 | P3 |
| 存在非安全类 Minor / Major 告警 | 有风险，需排查 | P1 / P2 |
| 存在 Critical 告警 | 不正常，立即处理 | P0 |

注意：**当前告警与历史 SEL 必须分开表述**——SEL 是历史流水，当前告警才是此刻状态，两者不能混为一谈。

## 2. 各维度正常标准

| # | 维度 | 正常标准 |
|---|---|---|
| 1 | 当前告警 | 为空，或仅含安全类 Minor（SNMP v2 / RMCP 弱套件） |
| 2 | 电源 | 4 个 PSU 全部在位（present）；Vin 180~264V；Vout 11.5~12.6V；InputMode=AC |
| 3 | NPU | 8 卡全部在位；ECC 错误计数为 0 |
| 4 | 光模块 | 8 个全部在位；无 TxLos / RxLos；SNR≥19dB；RX≥0.63mW；TX≥0.2mW |
| 5 | 温度 / 风扇 | Inlet<42°C；HBM<95°C；AI_Tj<105°C；风扇转速≥7000 RPM |
| 6 | RAID | 所有物理盘状态 Normal；MediaError=0 |
| 7 | BMC 自身 | 操作日志 / 安全日志 / SEL 均未满；证书未过期 |
| 8 | 指示灯 | 健康指示灯 GREEN；其他指示灯 ON/OFF 符合预期 |
| 9 | 版本 | 与 references/versions.md 中对应机型 / 伙伴机型的推荐版本一致 |
| 10 | 网络 | IPv6 为手动配置；VLAN 处于关闭状态 |

## 3. 问题分级

| 级别 | 含义 | 典型场景 |
|---|---|---|
| P0 🔴 | 严重故障，立即处理 | 当前存在 Critical 告警；电源掉电；NPU 丢失；RAID 故障 |
| P1 🟡 | 明确问题，尽快处理 | 操作/安全日志满；证书到期；温度 Major（含历史）；磁盘异常 |
| P2 🟢 | 建议关注，择机处理 | 版本偏旧；RAID 无逻辑盘；NPU 端口抖动；异常重启较多 |
| P3 ⚪ | 提示项 | 安全弱项（SNMP v2、RMCP 弱套件）；已恢复的历史事件 |

## 4. SEL 事件速查

| SEL 事件 | 默认级别 | 判读要点 |
|---|---|---|
| Power Supply input lost | Critical | 供电中断；结合是否出现 restored 判断是否已恢复 |
| Power Supply input restored | Info | 恢复事件，应与 lost 成对出现 |
| Above upper threshold | Major / Minor | 温度/电压类越限，按传感器与幅度区分严重度 |
| Operation Log Full / Security Log Full | Minor | 日志满，需导出清理 |
| Cert OverDue | Minor | 证书过期，需更换 |
| SEL almost full | Minor | SEL 快满，需导出清理 |
| System Restart [Unknown] / [IPMB] | Info | 未知原因重启，需跟踪出现频率 |
| [Chassis control][LOCAL] | Info | 本机发起的上下电动作，属正常操作 |
| watchdog 复位 | Info | 看门狗触发复位，需跟踪频率 |
| Sensor access degraded | Minor | 传感器访问降级，需关注 |

时间线原则：
- 同一事件反复出现 = 长期问题（如反复 Log Full、反复掉电）。
- 事件在短时间内集中爆发 = 单一根因（如一次掉电引发多条关联事件）。
- lost 与 restored 成对出现 = 已恢复的历史事件，不影响当前结论。

## 5. 常见故障模式

| # | 现象 | 推断 | 级别 | 现场动作 |
|---|---|---|---|---|
| 1 | PSU Vin=0 且当前 Critical | 电源未接电 / 输入丢失 | P0 | 查电源线与供电回路 |
| 2 | NPU ECC 多 bit 错误 > 0 | NPU 硬件异常 | P0 | 联系技术支持 |
| 3 | 装 OS 后 NPU 丢卡 | L1 交换板螺钉未拧紧（A3） | P0 | 拧紧 L1 交换板螺钉后复测 |
| 4 | OS 重启与同期 PSU 掉电 | 市电不稳 | P0 | 排查机房供电 |
| 5 | 温度持续 Major | 散热 / 风道 / 负载问题 | P1 | 查风扇、风道与负载 |
| 6 | Operation/Security Log Full 反复出现 | 日志满且未清理 | P1 | 导出并清理日志 |
| 7 | Cert OverDue | 证书过期 | P1 | 更换证书 |
| 8 | 光模块不达标（SNR / RX / TX） | 光模块或光链路劣化 | P1 | 更换光模块或清洁光纤 |
| 9 | RAID 无逻辑盘 | 未配置或配置丢失 | P2/P3 | 与使用方确认是否预期 |
| 10 | 版本偏旧 | 固件未升级 | P2 | 按推荐版本升级 |
| 11 | NPU 端口频繁 down/up | 链路抖动 | P2 | 查线缆与交换板 |
| 12 | SNMP v2 / RMCP 弱套件 | 安全弱项 | P3 | 建议升级到安全配置 |

## 6. 判读禁忌

1. SEL 里的历史掉电记录 ≠ 当前故障——必须结合 restored 与当前告警综合判断。
2. 版本旧 ≠ 硬件故障的充分条件——版本只作 P2 级建议，不能据此判 P0。
3. 集合通信不达标 ≠ BMC 故障——先查业务侧 ASCEND_GLOBAL_LOG_LEVEL 是否被设为 1（应改回 3）。
4. OS 自动重启 ≠ BMC 硬件问题——先看 kdump / OOM（crashkernel 1024M→2048M），区分系统层与带外层。
5. 伙伴机型出现多个 SN 时，以 BMC 页面显示的 SN 为准。
