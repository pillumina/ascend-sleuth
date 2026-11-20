#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_bmc_collect.py — 华为 iBMC 一键收集日志 → 结构化 JSON + 健康评分

依据：华为 Atlas 26.1.0 交付一本通 表5-79「一键收集信息说明」的目录/文件结构，
      以及 bmc_reference.md（判定标准手册）的量化标准。

输入：一个或多个 iBMC 一键收集导出根目录（含 dump_info/ 子目录）
输出：
  - 每台机器一个 <机器名>_bmc.json（单机或多机都会为每台机器生成）
  - 多机时额外输出 all_machines_bmc.json（machines + comparison 字段级矩阵，
    供集群对比报告与程序化 diff 直接使用）

用法：
  python parse_bmc_collect.py <root1> [root2 ...] -o <outdir>
"""

import argparse
import csv
import io
import json
import os
import pathlib
import re
import sqlite3
import sys
from datetime import datetime
from collections import OrderedDict

# ---------------------------------------------------------------------------
# 判定标准(来自 bmc_reference.md 表5-79 对应的量化值)
# ---------------------------------------------------------------------------
RULES = {
    "psu": {
        "count_expected": 4,          # 标准 4 PSU
        "vin_min": 180.0,             # AC 输入下限 V
        "vin_max": 264.0,             # AC 输入上限 V
        "vout_min": 11.5,             # DC 输出下限 V
        "vout_max": 12.6,             # DC 输出上限 V
    },
    "npu": {
        "count_expected": 8,          # A2 标准 8 卡
        "power_min": 0.0,
        "power_max": 200.0,
    },
    "fan": {
        "rpm_min": 7000,
    },
    "memory": {
        "health_ok": "ok",            # mem_info 里 health 列正常值
    },
    "optical": {
        "count_expected": 8,
        "snr_min": 19.0,              # dB
        "rx_min_mw": 0.63,            # mW
        "tx_min_mw": 0.2,             # mW
    },
    "temp": {
        "inlet_minor": 42.0,
        "inlet_major": 46.0,
        "npu_hbm_major": 95.0,
        "npu_ai_major": 105.0,
    },
    "raid": {"controller_ok": "Normal", "bbu_ok": "Normal", "disk_ok": "Normal"},
    "sel_levels": {"INFO": 0, "MINOR": 1, "MAJOR": 2, "CRITICAL": 3},
}

# 表5-79 关键收集文件清单（用于 parsed_files 可追溯性; rel 相对 dump_info）
KEY_FILES = [
    ("AppDump", "FruData/fruinfo.txt"),
    ("AppDump", "BMC/psu_info.txt"),
    ("AppDump", "BMC/time_zone.txt"),
    ("AppDump", "BMC/ntp_info.txt"),
    ("AppDump", "CpuMem/cpu_info"),
    ("AppDump", "CpuMem/mem_info"),
    ("AppDump", "CpuMem/npu_info"),
    ("AppDump", "CpuMem/npu_ecc_info.json"),
    ("AppDump", "CpuMem/NpuIO/optical_module_static_info"),
    ("AppDump", "CpuMem/NpuIO/optical_module_history_info_log.csv"),
    ("AppDump", "CpuMem/NpuIO/port_history_log"),
    ("AppDump", "cooling_app/fan_info.txt"),
    ("AppDump", "sensor_alarm/current_event.txt"),
    ("AppDump", "sensor_alarm/sensor_info.txt"),
    ("AppDump", "sensor_alarm/sel.db"),
    ("AppDump", "sensor_alarm/LedInfo"),
    ("AppDump", "NetConfig/net_info.txt"),
    ("AppDump", "StorageMgnt/RAID_Controller_Info.txt"),
    ("AppDump", "PowerMgnt/power_statistics.csv"),
    ("AppDump", "card_manage/card_info"),
    ("AppDump", "LicenseMgnt/lm_info"),
    ("AppDump", "UPGRADE/upgrade_info"),
    ("AppDump", "BIOS/bios_info"),
    ("RTOSDump", "versioninfo/app_revision.txt"),
    ("RTOSDump", "versioninfo/server_config.txt"),
    ("RTOSDump", "versioninfo/fruinfo.txt"),
    ("RTOSDump", "sysinfo/uptime"),
    ("RTOSDump", "sysinfo/loadavg"),
    ("RTOSDump", "sysinfo/meminfo"),
    ("RTOSDump", "sysinfo/df_info"),
    ("RTOSDump", "sysinfo/free_info"),
    ("RTOSDump", "networkinfo/ifconfig_info"),
    ("RTOSDump", "networkinfo/route_info"),
    ("RTOSDump", "networkinfo/resolv.conf"),
    ("RTOSDump", "networkinfo/ipinfo_info"),
    ("LogDump", "remote_log"),
    ("LogDump", "operate_log"),
    ("LogDump", "security_log"),
    ("LogDump", "ps_black_box.log"),
    ("LogDump", "storage/IODeterioration.db"),
    ("LogDump", "storage/SubhealthyStatus.db"),
    ("OptPme", "pram/cpu_utilise_webview.dat"),
    ("OptPme", "pram/env_web_view.dat"),
    ("OptPme", "pram/powerview.txt"),
    ("OptPme", "pram/BMC_HOSTNAME"),
    ("OptPme", "pram/filelist"),
    ("SpLogDump", "version.json"),
    ("SpLogDump", "deviceinfo.json"),
    ("Register", "cpld_reg_info"),
    ("Register", "cpu_reg_info"),
    ("Register", "vrd_reg_info"),
    ("3rdDump", "nginx.conf"),
    ("OSDump", ""),  # 目录
]

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def safe_read(path, limit_chars=None, encoding="utf-8", errors="replace"):
    """读取文本文件，容错；可选截断。返回字符串或 ''。"""
    try:
        with open(path, "r", encoding=encoding, errors=errors) as f:
            data = f.read()
    except Exception:
        return ""
    if limit_chars and len(data) > limit_chars:
        return data[:limit_chars]
    return data


def ensure_root(root):
    """定位 dump_info 根目录。支持直接给 dump_info 或外层目录或机器目录。"""
    if os.path.isdir(os.path.join(root, "dump_info")):
        return os.path.join(root, "dump_info")
    if os.path.basename(root) == "dump_info":
        return root
    return root


def find_file(info_root, rel_rel):
    """在 dump_info 根下查找相对路径文件（rel_rel 形如 AppDump/... 或 RTOSDump/...）。"""
    p = os.path.join(info_root, rel_rel)
    return p if os.path.isfile(p) else ""


def parse_ts(unix, tz=None):
    # 统一使用本地时区：generate_bmc_report.py 的 _ts_to_unix 用 naive
    # strptime().timestamp()（按本地时区）反向解析；两端必须一致，否则图表时间会偏移。
    try:
        return datetime.fromtimestamp(int(unix)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _split_rows(txt, sep="|"):
    """把管道/制表分隔文本拆成 rows(list[list])，跳过空行与表头行。"""
    rows = []
    for line in txt.splitlines():
        if not line.strip():
            continue
        if sep == "|" and line.strip().startswith(("-", "=")):
            continue
        parts = [p.strip() for p in line.split(sep)]
        if len(parts) < 2:
            continue
        rows.append(parts)
    return rows


def _get_int(s, default=None):
    try:
        v = str(s).strip().replace(",", "")
        return int(float(v)) if v not in ("", "N/A", "na", "-") else default
    except Exception:
        return default


def _get_float(s, default=None):
    try:
        v = str(s).strip()
        return float(v) if v not in ("", "N/A", "na", "-") else default
    except Exception:
        return default


# ---------------------------------------------------------------------------
# 参数字典：用于集群对比表「最后一列说明该参数是什么」（非 BIOS 参数用这里；BIOS 参数用 registry.json）
# ---------------------------------------------------------------------------
PARAM_DOCS = {
    # —— 身份/版本 ——
    "product_name": "产品名称（如 Atlas 800I A2 / HuaKun AT3500G3）",
    "product_sn": "产品序列号 SN，唯一标识一台机器",
    "model": "产品型号 Model（来自 Extend label）",
    "board_name": "主板产品名（Board Product Name）",
    "board_sn": "主板序列号",
    "board_mfg_date": "主板生产日期",
    "ibmc": "iBMC 固件版本（Active）",
    "backup_ibmc": "备用 iBMC 固件版本（Backup）",
    "bios": "BIOS 固件版本",
    "cpld": "CPLD 版本",
    "rtos_release": "RTOS 版本",
    "hostname": "iBMC 主机名",
    "timezone": "iBMC 时区",
    "collected_at": "日志收集时间（dump_log begin at）",
    # —— CPU/内存 ——
    "cpu_count": "CPU 物理颗数",
    "cpu_model": "CPU 型号（如 Kunpeng 920 5250）",
    "cpu_cores": "每颗 CPU 核心数",
    "mem_count": "内存 DIMM 条数",
    "mem_total_gb": "内存总容量（GB）",
    "mem_bad": "健康状态非 OK 的内存条数",
    # —— 电源 ——
    "psu_count": "电源模块总数（标准 4 个）",
    "psu_present": "在位电源个数",
    "psu_vin": "电源输入电压 Vin（V），标准≈220V(180~264V)",
    "psu_vout": "电源输出电压 Vout（V），标准≈12V(11.5~12.6V)",
    # —— NPU ——
    "npu_count": "NPU 卡数量（标准 8 卡）",
    "npu_single_ecc": "NPU 单 bit ECC 计数（>0 需关注趋势）",
    "npu_multi_ecc": "NPU 多 bit ECC 计数（>0=硬件故障 P0）",
    "npu_power_total": "NPU 总功率（W）",
    # —— 光模块 ——
    "optical_count": "光模块在位数量（标准 8 个）",
    "port_events": "NPU 参数面端口 up/down 事件总数",
    # —— 温度/风扇 ——
    "inlet_temp": "进风温度（°C），标准<42°C",
    "hbm_worst": "NPU HBM 最高温度（°C），标准<95°C",
    "fan_count": "风扇模块数量",
    # —— RAID/存储 ——
    "raid_health": "RAID 控制器健康状态（应=Normal）",
    "raid_mode": "RAID 控制器模式（RAID/HBA/JBOD）",
    "logical_drives": "逻辑盘数量（生产机应≥1）",
    "physical_drives": "物理盘数量",
    # —— 网络 ——
    "mgmt_ip": "管理网口 IPv4 地址",
    "net_mode": "管理网口网络模式（Manual/DHCP）",
    "vlan": "Dedicated 端口 VLAN 使能状态（应 disabled）",
    # —— SEL/告警 ——
    "sel_count": "SEL 事件总条数",
    "sel_critical": "SEL 中 CRITICAL 级事件数",
    "sel_major": "SEL 中 MAJOR 级事件数",
    "current_alarm": "当前活动告警（Critical/有内容/空）",
    # —— OS/资产 ——
    "os_name": "SP 操作系统版本",
    "esn": "产品 ESN（License 设备标识）",
    "license_status": "License 状态",
    # —— NAND ——
    "nand_remaining_lifetime": "NAND Flash 剩余寿命（应>10%）",
    "nand_total_written": "NAND Flash 累计写入量",
}


def parse_bios(info_root):
    """BIOS 配置全量提取：currentvalue.json（当前值）+ registry.json（定义/说明/菜单路径）。
    返回 { "items": [ {name, value, type, display_name, help_text, menu_path, default} ], "count": N }
    """
    cv_path = find_file(info_root, os.path.join("AppDump", "BIOS", "currentvalue.json"))
    rg_path = find_file(info_root, os.path.join("AppDump", "BIOS", "registry.json"))
    values = {}
    if cv_path:
        try:
            with open(cv_path, "r", encoding="utf-8", errors="replace") as f:
                values = json.load(f) or {}
        except Exception:
            values = {}
    # registry: AttributeName -> {DisplayName, HelpText, MenuPath, DefaultValue, Type}
    registry = {}
    if rg_path:
        try:
            with open(rg_path, "r", encoding="utf-8", errors="replace") as f:
                rg = json.load(f) or {}
            for attr in rg.get("RegistryEntries", {}).get("Attributes", []) or []:
                name = attr.get("AttributeName")
                if name:
                    registry[name] = {
                        "type": attr.get("Type"),
                        "display_name": attr.get("DisplayName"),
                        "help_text": attr.get("HelpText"),
                        "menu_path": attr.get("MenuPath"),
                        "default": attr.get("DefaultValue"),
                        "read_only": attr.get("ReadOnly"),
                    }
        except Exception:
            registry = {}
    items = []
    for name, value in values.items():
        meta = registry.get(name, {})
        items.append({
            "name": name,
            "value": value,
            "type": meta.get("type", ""),
            "display_name": meta.get("display_name", ""),
            "help_text": meta.get("help_text", ""),
            "menu_path": meta.get("menu_path", ""),
            "default": meta.get("default", ""),
        })
    # 未在 currentvalue 但 registry 有定义的项（补充说明用）
    extra = [name for name in registry if name not in values]
    return {
        "count": len(items),
        "items": items,
        "registry_count": len(registry),
        "registry_unlisted": extra[:50],
    }


def parse_nand(info_root):
    """nandflash_info.txt: NAND Flash 寿命/写入量。"""
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "BMC", "nandflash_info.txt")),
                    limit_chars=4000)
    out = {}
    if not txt:
        return out
    m = re.search(r"Vender Name\s*:\s*(\S+)", txt)
    if m: out["vendor"] = m.group(1)
    m = re.search(r"Remaining Lifetime\s*:\s*(\S+)", txt)
    if m: out["remaining_lifetime"] = m.group(1)
    m = re.search(r"Total Written Amount\s*:\s*(\S+)", txt)
    if m: out["total_written"] = m.group(1)
    m = re.search(r"Data written per day in 15 days\s*:\s*([^\n]+)", txt)
    if m: out["daily_write"] = m.group(1).strip()[:200]
    return out


def parse_lldp(info_root):
    """NetConfig/lldp_info.txt: LLDP 配置。"""
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "NetConfig", "lldp_info.txt")),
                    limit_chars=2000)
    out = {}
    for line in txt.splitlines():
        m = re.match(r"(\w+)\s*:\s*(\S+)", line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def parse_mcinfo(info_root):
    """BMC/mcinfo.txt: BMC 芯片/固件标识。"""
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "BMC", "mcinfo.txt")),
                    limit_chars=2000)
    return {"raw": txt.strip()[:1500]}


def parse_fruinfo(info_root):
    """FRU 身份信息: 产品名/厂商/SN/主板. (AppDump/FruData 或 RTOSDump/versioninfo)"""
    for p in (find_file(info_root, os.path.join("AppDump", "FruData", "fruinfo.txt")),
              find_file(info_root, os.path.join("RTOSDump", "versioninfo", "fruinfo.txt"))):
        txt = safe_read(p, limit_chars=20000)
        if txt:
            break
    out = {"product_name": "", "product_manufacturer": "", "product_sn": "",
           "board_name": "", "board_sn": "", "board_manufacturer": "", "extend_label": "",
           "model": "", "board_mfg_date": "", "board_part_number": ""}
    if not txt:
        return out
    m = re.search(r"^\s*Product Name\s*:\s*(.+)$", txt, re.M)
    if m:
        out["product_name"] = m.group(1).strip()
    m = re.search(r"^\s*Product Manufacturer\s*:\s*(.+)", txt, re.M)
    if m:
        out["product_manufacturer"] = m.group(1).strip()
    m = re.search(r"^\s*Product Serial Number\s*:\s*(\S+)", txt, re.M)
    if m:
        out["product_sn"] = m.group(1).strip()
    m = re.search(r"^\s*Board Product Name\s*:\s*(\S+)", txt, re.M)
    if m:
        out["board_name"] = m.group(1).strip()
    m = re.search(r"^\s*Board Serial Number\s*:\s*(\S+)", txt, re.M)
    if m:
        out["board_sn"] = m.group(1).strip()
    m = re.search(r"^\s*Board Manufacturer\s*:\s*(.+)", txt, re.M)
    if m:
        out["board_manufacturer"] = m.group(1).strip()
    m = re.search(r"^\s*Board Mfg. Date\s*:\s*([^\n]+)", txt, re.M)
    if m:
        out["board_mfg_date"] = m.group(1).strip()
    m = re.search(r"^\s*Board Part Number\s*:\s*(\S+)", txt, re.M)
    if m:
        out["board_part_number"] = m.group(1).strip()
    m = re.search(r"^\s*Extend label\s*:\s*([^\n]+)", txt, re.M)
    if m:
        out["extend_label"] = m.group(1).strip()[:600]
    m = re.search(r"Model=([^\s,]+)", txt)
    if m:
        out["model"] = m.group(1).strip()
    return out


def parse_versions(info_root):
    """iBMC/BIOS/CPLD/NPU 固件版本信息（RTOSDump/versioninfo + upgrade_info）。"""
    out = {
        "ibmc": "", "ibmc_built": "", "backup_ibmc": "", "bios": "",
        "cpld": "", "sdk": "", "uboot": "", "rtos_release": "",
        "ibmc_revision": "", "baseversion": "", "build_date": "", "product_name": "",
    }
    r = find_file(info_root, os.path.join("RTOSDump", "versioninfo", "app_revision.txt"))
    txt = safe_read(r, limit_chars=8000)
    if txt:
        m = re.search(r"Active iBMC\s+Version:\s*(\S+)", txt)
        if m: out["ibmc"] = m.group(1)
        m = re.search(r"Active iBMC\s+Built:\s*([^\n]+)", txt)
        if m: out["ibmc_built"] = m.group(1).strip()
        m = re.search(r"Backup iBMC\s+Version:\s*(\S+)", txt)
        if m: out["backup_ibmc"] = m.group(1)
        m = re.search(r"BIOS\s+Version:\s*(\S+)", txt)
        if m: out["bios"] = m.group(1)
        m = re.search(r"CPLD\s+Version:\s*(.+)", txt)
        if m: out["cpld"] = m.group(1).strip()
        m = re.search(r"SDK\s+Version:\s*(\S+)", txt)
        if m: out["sdk"] = m.group(1)
        m = re.search(r"Active Uboot\s+Version:\s*(\S+)", txt)
        if m: out["uboot"] = m.group(1)
        m = re.search(r"Product\s+Name:\s*(.+)", txt)
        if m: out["product_name"] = m.group(1).strip()
    r = find_file(info_root, os.path.join("RTOSDump", "versioninfo", "RTOS-Release"))
    txt = safe_read(r, limit_chars=500)
    if txt:
        out["rtos_release"] = txt.strip().splitlines()[0].strip()
    r = find_file(info_root, os.path.join("RTOSDump", "versioninfo", "ibmc_revision.txt"))
    txt = safe_read(r, limit_chars=1000)
    if txt:
        out["ibmc_revision"] = txt.strip()[:500]
        m = re.search(r"baseversion:\s*(\S+)", txt)
        if m: out["baseversion"] = m.group(1)
    r = find_file(info_root, os.path.join("RTOSDump", "versioninfo", "build_date.txt"))
    txt = safe_read(r, limit_chars=200)
    if txt:
        out["build_date"] = txt.strip()
    # upgrade_info 里可能有 MCU/Ascend 版本
    r = find_file(info_root, os.path.join("AppDump", "UPGRADE", "upgrade_info"))
    txt = safe_read(r, limit_chars=8000)
    if txt:
        for key in ("MCU", "Ascend", "BMC", "BIOS", "CPLD", "Retimer"):
            m = re.search(rf"(?im)^\s*{key}[^\n:]*[Vv]ersion\s*[:\s]\s*(\S+)", txt)
            if m:
                out.setdefault("upgrade_" + key.lower(), m.group(1))
    return out


def parse_current_event(info_root):
    """当前活动告警 current_event.txt。"""
    p = find_file(info_root, os.path.join("AppDump", "sensor_alarm", "current_event.txt"))
    txt = safe_read(p, limit_chars=20000)
    return {
        "file_exists": bool(os.path.exists(p)),
        "text": txt.strip(),
        "empty": not txt.strip(),
        # 词边界匹配并排除 non-critical 前缀，避免 "Non-Critical" 子串误判为 Critical
        "has_critical": bool(re.search(r"(?<!non-)\bcritical\b", txt, re.IGNORECASE)),
        "has_minor": "minor" in txt.lower(),
    }


def parse_led(info_root):
    """LedInfo: 系统健康灯 + 风扇灯。"""
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "sensor_alarm", "LedInfo")),
                    limit_chars=20000)
    leds = {}
    cur = None
    for line in txt.splitlines():
        line = line.strip()
        m = re.match(r"LED Name\s*:\s*(.+)", line)
        if m:
            cur = m.group(1).strip()
            leds[cur] = {}
            continue
        if cur:
            m = re.match(r"LED (State|Color)\s*:\s*(.+)", line)
            if m:
                leds[cur][m.group(1)] = m.group(2).strip()
    return leds


def parse_sensors(info_root, only_problem=False, limit=None):
    """sensor_info.txt 全部传感器。返回列表 dict；option only_problem 只返回非 ok。"""
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "sensor_alarm", "sensor_info.txt")),
                    limit_chars=200000)
    rows = []
    # 表头: sensor id | sensor name | value | unit | status | lnr | lc | lnc | unc | uc | unr | phys | nhys
    for line in txt.splitlines():
        if line.strip().startswith(("sensor id", "-")):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5:
            continue
        # id 列保留原始字符串(id_hex)。不再强制按十六进制转换：
        # 表头变体/汇总行等非数值首列此前会被 except 分支静默丢弃。
        row = {
            "id_hex": parts[0],
            "name": parts[1],
            "value": parts[2],
            "unit": parts[3],
            "status": parts[4],
        }
        if len(parts) >= 6:
            row["lnr"] = parts[5]
        if len(parts) >= 7:
            row["lc"] = parts[6]
        if len(parts) >= 8:
            row["lnc"] = parts[7]
        if len(parts) >= 9:
            row["unc"] = parts[8]
        if len(parts) >= 10:
            row["uc"] = parts[9]
        rows.append(row)
    if limit:
        rows = rows[:limit]
    if only_problem:
        return [r for r in rows if r["status"] not in ("ok", "na")]
    return rows


def parse_psu(info_root):
    """psu_info.txt 或 server_config.txt 中的 PSU 信息。"""
    psu = []
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "BMC", "psu_info.txt")),
                    limit_chars=8000)
    if not txt:
        # fallback server_config
        txt = safe_read(find_file(info_root, os.path.join("RTOSDump", "versioninfo", "server_config.txt")),
                        limit_chars=100000)
        header_found = False
        for line in txt.splitlines():
            if "presence" in line and "Vin" in line:
                header_found = True
                continue
            if header_found and line.strip():
                m = re.match(r"\s*(\d+)\s*\|\s*(\w+)\s*\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|\s*([\d.]+)\s*\|\s*([\d.]+)", line)
                if m:
                    psu.append({
                        "slot": m.group(1), "presence": m.group(2),
                        "manufacturer": m.group(3).strip(), "type": m.group(4).strip(),
                        "sn": m.group(5).strip(), "version": m.group(6).strip(),
                        "rated_power": m.group(7).strip(), "input_mode": m.group(8).strip(),
                        "partnum": m.group(9).strip(), "device": m.group(10).strip(),
                        "vin": m.group(11), "vout": m.group(12),
                    })
                elif line.startswith("PS") and "Version" in line:
                    pass
        return psu
    # psu_info.txt 解析
    for line in txt.splitlines()[1:]:
        if not line.strip() or line.startswith("Slot"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 12:
            psu.append({
                "slot": parts[0], "presence": parts[1], "manufacturer": parts[2],
                "type": parts[3], "sn": parts[4], "version": parts[5],
                "rated_power": parts[6], "input_mode": parts[7], "partnum": parts[8],
                "device": parts[9], "vin": parts[10], "vout": parts[11],
            })
    return psu


def parse_cpu(info_root):
    """cpu_info: CPU 槽位/型号/核心数/缓存/SN。文件为逗号分隔。"""
    cpus = []
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "CpuMem", "cpu_info")),
                    limit_chars=10000)
    for line in txt.splitlines():
        if line.startswith("slot") or line.startswith("-") or not line.strip():
            continue
        # 逗号分隔（字段内也可能含 |，如 memory technology）
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 14:
            cpus.append({
                "slot": parts[0], "presence": parts[1], "model": parts[2],
                "processor_id": parts[3], "cores": parts[4], "threads": parts[5],
                "l1": parts[7], "l2": parts[8], "l3": parts[9],
                "partnum": parts[10], "device": parts[11], "location": parts[12],
                "sn": parts[13],
            })
    return cpus


def parse_memory(info_root):
    """mem_info: 内存 DIMM 列表 + 统计（总容量/条数/异常条数）。文件为逗号分隔。"""
    dimms = []
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "CpuMem", "mem_info")),
                    limit_chars=150000)
    # 先从表头定位 health 列（不同机型列序可能不同），定位不到则回退固定第 21 列
    health_idx = 21
    for line in txt.splitlines():
        low = line.strip().lower()
        if low.startswith("slot") and "health" in low:
            cols = [c.strip().lower() for c in line.split(",")]
            if "health" in cols:
                health_idx = cols.index("health")
            break
    for line in txt.splitlines():
        if line.startswith("slot") or line.startswith("-") or not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 9:
            dimm = {
                "slot": parts[0], "location": parts[1], "name": parts[2],
                "manufacturer": parts[3], "size": parts[4], "speed": parts[5],
                "current_speed": parts[6], "type": parts[7], "sn": parts[8],
            }
            if len(parts) > health_idx:
                dimm["health"] = parts[health_idx]
            dimms.append(dimm)
    total_mb = 0
    for d in dimms:
        sz = re.search(r"(\d+)", d.get("size", ""))
        if sz:
            total_mb += int(sz.group(1))
    bad = [d for d in dimms if str(d.get("health", "")).lower() not in ("ok", "", "na", "n/a")]
    return {
        "dimms": dimms,
        "count": len(dimms),
        "total_gb": round(total_mb / 1024, 1) if total_mb else 0,
        "bad_count": len(bad),
        "bad_dimms": bad,
    }


def parse_fan_detail(info_root):
    """fan_info.txt: 风扇模块详情（前后转速/最大范围/型号）。"""
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "cooling_app", "fan_info.txt")),
                    limit_chars=20000)
    fans = []
    for line in txt.splitlines():
        s = line.strip()
        if not s or s.startswith("Fan ") and "Presence" in s:
            continue  # 表头行（Fan 后面跟 Presence）
        if s.startswith("-"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 8:
            fans.append({
                "name": parts[0], "presence": parts[1], "pwm": parts[2],
                "speed": parts[3], "max_rpm": parts[4], "model": parts[5],
                "partnum": parts[6], "device": parts[7],
            })
    return fans


def parse_npu(info_root):
    """npu_info: 卡名/功率/ECC单双bit。"""
    npus = []
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "CpuMem", "npu_info")),
                    limit_chars=10000)
    for line in txt.splitlines():
        if line.startswith("Name") or not line.strip():
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 7:
            npus.append({
                "name": parts[0], "board": parts[1], "power_w": parts[2],
                "workmode": parts[3], "single_ecc": parts[4], "double_ecc": parts[5],
                "diversification": parts[6],
                "fw_version": parts[7] if len(parts) > 7 else "",
                "sw_version": parts[8] if len(parts) > 8 else "",
            })
    return npus


def parse_npu_ecc(info_root):
    """npu_ecc_info.json 详细 ECC（单/多 bit 计数）。"""
    p = find_file(info_root, os.path.join("AppDump", "CpuMem", "npu_ecc_info.json"))
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception:
        return {}
    out = {}
    for item in data.get("EccInfo", []):
        name = item.get("Name")
        out[name] = {
            "single_bit": item.get("SingleBitEcc", {}).get("Count", "N/A"),
            "single_agg": item.get("SingleBitEcc", {}).get("AggregateTotalCount", "N/A"),
            "single_isolated": item.get("SingleBitIsolatedPages", {}).get("Count", "N/A"),
            "multi_bit": item.get("MultiBitEcc", {}).get("Count", "N/A"),
            "multi_agg": item.get("MultiBitEcc", {}).get("AggregateTotalCount", "N/A"),
            "multi_isolated": item.get("MultiBitIsolatedPages", {}).get("Count", "N/A"),
        }
    return out


def parse_optical(info_root):
    """光学模块（静态信息 + 历史 CSV + 端口 up/down）。"""
    static = []
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "CpuMem", "NpuIO", "optical_module_static_info")),
                    limit_chars=20000)
    cur = {}
    for line in txt.splitlines():
        m = re.match(r"(\w+):\s*(.+)", line.strip())
        if m:
            cur[m.group(1)] = m.group(2).strip()
            if m.group(1) == "TransceiverType":
                static.append(dict(cur))
                cur = {}
    port_events = []
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "CpuMem", "NpuIO", "port_history_log")),
                    limit_chars=20000)
    for line in txt.splitlines():
        m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\S+)\s+port\s+(up|down)", line.strip())
        if m:
            port_events.append({"time": m.group(1), "port": m.group(2), "event": m.group(3)})
    return {"static": static, "port_events": port_events}


def parse_raid(info_root):
    """RAID_Controller_Info.txt: 控制器/BBU/逻辑盘/磁盘/PHY 误码。"""
    for sub in ("StorageMgnt", "StorageMgmt", "StorageMgr"):
        p = find_file(info_root, os.path.join("AppDump", sub, "RAID_Controller_Info.txt"))
        if os.path.exists(p):
            break
    if not os.path.exists(p):
        return {}
    txt = safe_read(p, limit_chars=200000)
    out = {
        "controller": {}, "bbu": {}, "logical_drives": [], "physical_drives": [],
        "phy_errors": {}, "iodeterioration": None, "subhealthy": None,
    }
    # 控制器
    m = re.search(r"Controller Name\s*:\s*(.+)", txt)
    if m: out["controller"]["name"] = m.group(1).strip()
    m = re.search(r"^Controller Health\s*:\s*(\S+)", txt, re.M)
    if m: out["controller"]["health"] = m.group(1)
    m = re.search(r"^Firmware Version\s*:\s*(\S+)", txt, re.M)
    if m: out["controller"]["fw"] = m.group(1)
    m = re.search(r"^Controller Mode\s*:\s*(\S+)", txt, re.M)
    if m: out["controller"]["mode"] = m.group(1)
    m = re.search(r"^Memory Size\s*:\s*(\S+)", txt, re.M)
    if m: out["controller"]["memory_size"] = m.group(1)
    m = re.search(r"^DDR ECC Count\s*:\s*(\S+)", txt, re.M)
    if m: out["controller"]["ddr_ecc"] = m.group(1)
    # BBU
    m = re.search(r"^BBU Status\s*:\s*(\S+)", txt, re.M)
    if m: out["bbu"]["status"] = m.group(1)
    m = re.search(r"^BBU Type\s*:\s*(\S+)", txt, re.M)
    if m: out["bbu"]["type"] = m.group(1)
    m = re.search(r"^BBU Health\s*:\s*(\S+)", txt, re.M)
    if m: out["bbu"]["health"] = m.group(1)

    # 逻辑盘：Logical Drive Information 下每个 "Target ID : N" 分块
    ld_block = txt.split("Logical Drive Information", 1)[1] if "Logical Drive Information" in txt else ""
    if ld_block:
        # 每个 Target ID 块
        for blk in re.split(r"(?=Target ID\s*:)", ld_block):
            m = re.search(r"^Target ID\s*:\s*(\d+)", blk, re.M)
            if not m:
                continue
            ld = {"target": m.group(1)}
            for key, valkey in [("Name", "name"), ("Type", "type"), ("State", "state"),
                                ("Total Size", "total_size"), ("Strip Size", "strip_size")]:
                mm = re.search(rf"^{re.escape(key)}\s*:\s*(.+)$", blk, re.M)
                if mm:
                    ld[valkey] = mm.group(1).strip()
            out["logical_drives"].append(ld)

    # 物理盘：Physical Drives Information / Pass Through Drives Information 下每个 "ID : N" 分块
    for section_key in ("Physical Drives Information", "Pass Through Drives Information"):
        phy_block = txt.split(section_key, 1)[1] if section_key in txt else ""
        if not phy_block:
            continue
        # 可能有多张控制器的物理盘，截到下一个大节
        for cut in ("[MCTP", "Done", "=============================="):
            idx = phy_block.find(cut)
            if idx != -1:
                phy_block = phy_block[:idx]
        for blk in re.split(r"(?=ID\s*:\s*\d+)", phy_block):
            m = re.search(r"^ID\s*:\s*(\d+)", blk, re.M)
            if not m:
                continue
            disk = {"ID": m.group(1)}
            for line in blk.splitlines():
                line = line.strip()
                if line and ":" in line and not line.startswith("-----"):
                    k, _, v = line.partition(":")
                    disk[k.strip()] = v.strip()
            if "Device Name" in disk:
                out["physical_drives"].append(disk)
    # 去重(同盘重复出现只保留一次)
    seen = set()
    uniq = []
    for d in out["physical_drives"]:
        key = (d.get("Device Name"), d.get("Serial Number"), d.get("ID"))
        if key not in seen:
            seen.add(key)
            uniq.append(d)
    out["physical_drives"] = uniq
    # PHY 误码 (RAID_Card*_PHY_Error_Count.csv / Expander)
    storage_dir = os.path.join(info_root, "LogDump", "storage", "phy")
    if os.path.isdir(storage_dir):
        for f in os.listdir(storage_dir):
            if f.endswith(".csv"):
                fp = os.path.join(storage_dir, f)
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                        out["phy_errors"][f] = fh.read(4000)
                except Exception:
                    pass
    # 慢盘/亚健康 db
    storage = os.path.join(info_root, "LogDump", "storage")
    for name in ("IODeterioration.db", "SubhealthyStatus.db"):
        fp = os.path.join(storage, name)
        if os.path.exists(fp):
            out["iodeterioration" if "IO" in name else "subhealthy"] = {
                "exists": True, "size": os.path.getsize(fp)}
    return out


def parse_network(info_root):
    """net_info.txt / RTOSDump/networkinfo。"""
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "NetConfig", "net_info.txt")),
                    limit_chars=20000)
    out = {"eth_groups": [], "interfaces": {}}
    # EthGroup blocks
    cur = {}
    for line in txt.splitlines():
        m = re.match(r"EthGroup ID\s*:\s*(\S+)", line.strip())
        if m:
            if cur:
                out["eth_groups"].append(cur)
            cur = {"id": m.group(1)}
            continue
        for key in ("Net Mode", "Net Type", "Active Port"):
            m2 = re.match(key + r"\s*:\s*(\S+)", line.strip())
            if m2:
                cur[key] = m2.group(1)
        m2 = re.match(r"(IP Address|Subnet Mask|Default Gateway|MAC Address|IPv6 Mode)\s*:\s*(\S*)", line.strip())
        if m2:
            cur[m2.group(1)] = m2.group(2)
        m2 = re.match(r"(VLAN Information|NCSI Port VLAN State|Dedicated Port VLAN State)\s*:\s*(\S+)", line.strip())
        if m2:
            cur[m2.group(1)] = m2.group(2)
    if cur:
        out["eth_groups"].append(cur)
    return out


def parse_network_os(info_root):
    """RTOSDump/networkinfo：ifconfig / route / resolv / ipinfo。"""
    out = {"ifconfig": {}, "route": [], "resolv": [], "ipinfo": ""}
    txt = safe_read(find_file(info_root, os.path.join("RTOSDump", "networkinfo", "ifconfig_info")),
                    limit_chars=30000)
    iface = None
    for line in txt.splitlines():
        m = re.match(r"(\S+)\s+Link encap:(\S+)", line)
        if m:
            iface = m.group(1)
            out["ifconfig"][iface] = {"encap": m.group(2)}
            continue
        if iface:
            m2 = re.match(r"\s*inet addr:(\S+)\s+Bcast:(\S+)\s+Mask:(\S+)", line)
            if m2:
                out["ifconfig"][iface]["ip"] = m2.group(1)
                out["ifconfig"][iface]["mask"] = m2.group(3)
            m3 = re.match(r"\s*UP (\S+)\s+", line)
            if m3:
                out["ifconfig"][iface]["flags"] = line.strip()
    txt = safe_read(find_file(info_root, os.path.join("RTOSDump", "networkinfo", "route_info")),
                    limit_chars=10000)
    for line in txt.splitlines()[2:]:
        parts = line.split()
        if len(parts) >= 4:
            out["route"].append({"dest": parts[0], "gateway": parts[1], "genmask": parts[2], "iface": parts[-1]})
    txt = safe_read(find_file(info_root, os.path.join("RTOSDump", "networkinfo", "resolv.conf")),
                    limit_chars=5000)
    for line in txt.splitlines():
        if line.startswith("nameserver"):
            parts = line.split()
            if len(parts) >= 2:
                out["resolv"].append(parts[1])
    txt = safe_read(find_file(info_root, os.path.join("RTOSDump", "networkinfo", "ipinfo_info")),
                    limit_chars=20000)
    out["ipinfo"] = txt[:3000]
    return out


def parse_time_config(info_root):
    """时区 / NTP / 主机名 配置。"""
    out = {"timezone": "", "ntp": "", "hostname": ""}
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "BMC", "time_zone.txt")), limit_chars=2000)
    m = re.search(r"[:：]\s*(.+)", txt)
    if m:
        out["timezone"] = m.group(1).strip()
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "BMC", "ntp_info.txt")), limit_chars=2000)
    if txt:
        out["ntp"] = txt.strip()[:1000]
    for p in (os.path.join(info_root, "OptPme", "pram", "BMC_HOSTNAME"),
              os.path.join(info_root, "OptPme", "save", "BMC_HOSTNAME")):
        txt = safe_read(p, limit_chars=500)
        if txt.strip():
            out["hostname"] = txt.strip()
            break
    return out


def parse_ibmc_sys(info_root):
    """RTOSDump/sysinfo: iBMC 系统资源（uptime/loadavg/meminfo/df）。"""
    out = {"uptime": "", "loadavg": "", "mem": {}, "df": [], "free": ""}
    txt = safe_read(find_file(info_root, os.path.join("RTOSDump", "sysinfo", "uptime")), limit_chars=500)
    if txt.strip():
        parts = txt.split()
        if len(parts) >= 2:
            out["uptime"] = f"since {float(parts[0])/86400:.1f} days" 
        else:
            out["uptime"] = txt.strip()
    txt = safe_read(find_file(info_root, os.path.join("RTOSDump", "sysinfo", "loadavg")), limit_chars=500)
    out["loadavg"] = txt.strip()
    txt = safe_read(find_file(info_root, os.path.join("RTOSDump", "sysinfo", "meminfo")), limit_chars=20000)
    for line in txt.splitlines():
        m = re.match(r"(\w+):\s+(\d+)\s*kB", line)
        if m:
            out["mem"][m.group(1)] = int(m.group(2))
    txt = safe_read(find_file(info_root, os.path.join("RTOSDump", "sysinfo", "df_info")), limit_chars=20000)
    for line in txt.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 6:
            out["df"].append({"fs": parts[0], "size_k": parts[1], "used_k": parts[2],
                              "use_pct": parts[4], "mount": parts[5]})
    txt = safe_read(find_file(info_root, os.path.join("RTOSDump", "sysinfo", "free_info")), limit_chars=5000)
    out["free"] = txt.strip()
    return out


def parse_cards(info_root):
    """card_manage/card_info: PCIe扣卡/光模块/垫片/背板。"""
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "card_manage", "card_info")),
                    limit_chars=30000)
    out = {"pcie_cards": [], "nic_modules": [], "risers": [], "backplanes": []}
    section = None
    for line in txt.splitlines():
        s = line.strip()
        if "Pcie Card Info" in s:
            section = "pcie"; continue
        if "NIC Card Optical Module Info" in s:
            section = "nic"; continue
        if "Riser Card Info" in s:
            section = "riser"; continue
        if "HDD Backplane Info" in s:
            section = "bp"; continue
        if s.startswith("Slot"):
            continue
        if not s or s.startswith("-"):
            continue
        parts = [p.strip() for p in s.split("|")]
        if section == "pcie" and len(parts) >= 4:
            out["pcie_cards"].append({"slot": parts[0], "vendor": parts[1], "device": parts[2],
                                      "desc": parts[8] if len(parts) > 8 else "",
                                      "product": parts[17] if len(parts) > 17 else ""})
        elif section == "nic" and len(parts) >= 6:
            out["nic_modules"].append({"card": parts[0], "port": parts[1],
                                       "present": parts[3], "vendor": parts[4], "sn": parts[5]})
        elif section == "riser" and len(parts) >= 4:
            out["risers"].append({"slot": parts[0], "name": parts[2], "type": parts[3] if len(parts) > 3 else ""})
        elif section == "bp" and len(parts) >= 4:
            out["backplanes"].append({"slot": parts[0], "name": parts[2], "type": parts[5] if len(parts) > 5 else ""})
    return out


def parse_register(info_root):
    """Register/: CPLD/CPU/VRD 寄存器 dump（十六进制）。只记录存在性+大小+首行。"""
    out = {}
    for name in ("cpld_reg_info", "cpu_reg_info", "vrd_reg_info", "vrd_reg_info.1.gz"):
        p = os.path.join(info_root, "Register", name)
        if os.path.exists(p):
            head = safe_read(p, limit_chars=400)
            out[name] = {"exists": True, "size": os.path.getsize(p), "head": head[:200]}
    return out


def parse_license(info_root):
    """LicenseMgnt/lm_info: ALM/ESN/License 状态。"""
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "LicenseMgnt", "lm_info")),
                    limit_chars=8000)
    out = {"esn": "", "alm_version": "", "license_status": ""}
    if not txt:
        return out
    m = re.search(r"Product ESN\s*:\s*(\S+)", txt)
    if m:
        out["esn"] = m.group(1)
    m = re.search(r"ALM Version\s*:\s*(\S+)", txt)
    if m:
        out["alm_version"] = m.group(1)
    m = re.search(r"License Status\s*:\s*(\S+)", txt)
    if m:
        out["license_status"] = m.group(1)
    return out


def parse_sp_asset(info_root):
    """SpLogDump: SP 版本 + 资产信息。"""
    out = {"sp_version": {}, "deviceinfo": {}}
    p = find_file(info_root, os.path.join("SpLogDump", "version.json"))
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                out["sp_version"] = json.load(f)
        except Exception:
            pass
    p = find_file(info_root, os.path.join("SpLogDump", "deviceinfo.json"))
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                out["deviceinfo"] = json.load(f)
        except Exception:
            pass
    return out


def parse_nginx(info_root):
    """3rdDump: Nginx 配置信息（仅存在性 + 关键配置片段）。"""
    out = {"exists": os.path.isdir(os.path.join(info_root, "3rdDump")), "files": {}}
    d = os.path.join(info_root, "3rdDump")
    if not out["exists"]:
        return out
    for name in os.listdir(d):
        fp = os.path.join(d, name)
        if os.path.isfile(fp):
            out["files"][name] = os.path.getsize(fp)
    return out


def parse_utilization(info_root):
    """OptPme/pram: CPU/内存/环境温度/功率 曲线（webview.dat 与 powerview.txt）。"""
    out = {"cpu_utilise": "", "mem_utilise": "", "env_temp": [], "hbm_temp": [], "power": []}
    # cpu_utilise_webview.dat / CpuMem_cpu_utilise
    for p in (os.path.join(info_root, "OptPme", "pram", "cpu_utilise_webview.dat"),
              os.path.join(info_root, "OptPme", "pram", "CpuMem_cpu_utilise"),
              os.path.join(info_root, "OptPme", "save", "CpuMem_cpu_utilise")):
        t = safe_read(p, limit_chars=500000)
        if t:
            out["cpu_utilise"] = t[:4000]
            break
    for p in (os.path.join(info_root, "OptPme", "pram", "CpuMem_mem_utilise"),
              os.path.join(info_root, "OptPme", "save", "CpuMem_mem_utilise")):
        t = safe_read(p, limit_chars=500000)
        if t:
            out["mem_utilise"] = t[:4000]
            break
    # env_web_view.dat 温度曲线
    for p in (os.path.join(info_root, "OptPme", "pram", "env_web_view.dat"),
              os.path.join(info_root, "OptPme", "save", "env_web_view.dat")):
        t = safe_read(p, limit_chars=500000)
        if t:
            for line in t.splitlines():
                m = re.match(r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})#(.+)", line.strip())
                if m:
                    out["env_temp"].append({"time": m.group(1), "value": m.group(2)})
            out["env_temp"] = out["env_temp"][-500:]
            break
    # NPU HBM 温度曲线
    pram = os.path.join(info_root, "OptPme", "pram")
    if os.path.isdir(pram):
        for f in sorted(os.listdir(pram)):
            if f.startswith("NPU-") and f.endswith("_hbm_webview.dat"):
                t = safe_read(os.path.join(pram, f), limit_chars=30000)
                if t:
                    out["hbm_temp"].append({"file": f, "sample": t[-3000:]})
    # powerview.txt 功率统计
    for p in (os.path.join(info_root, "OptPme", "pram", "powerview.txt"),
              os.path.join(info_root, "OptPme", "save", "powerview.txt")):
        t = safe_read(p, limit_chars=100000)
        if t:
            out["power"] = t[:4000]
            break
    return out


def parse_power_stat(info_root):
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "PowerMgnt", "power_statistics.csv")),
                    limit_chars=8000)
    out = {"exists": bool(txt), "sample": txt[:3000]}
    return out


def parse_bios_summary(info_root):
    txt = safe_read(find_file(info_root, os.path.join("AppDump", "BIOS", "bios_info")),
                    limit_chars=2000)
    out = {"exists": bool(txt), "head": txt[:1000]}
    return out


def parse_sel(info_root):
    """sel.db (SQLite) 全量事件。"""
    p = find_file(info_root, os.path.join("AppDump", "sensor_alarm", "sel.db"))
    events = []
    stats = {"count": 0, "by_level": {}, "by_entity": {}, "first_ts": "", "last_ts": ""}
    if not os.path.exists(p):
        return {"events": events, "stats": stats, "critical_discrete": []}
    levelmap = {"0": "INFO", "1": "MINOR", "2": "MAJOR", "3": "CRITICAL"}
    statmap = {"0": "Asserted", "1": "Deasserted"}
    try:
        # Windows 盘符/中文/空格路径下，手拼 "file:<反斜杠路径>?mode=ro" 常因
        # URI 规范不符而打开失败；用 pathlib.as_uri() 生成规范百分号编码 URI，
        # 仍失败时退回普通连接（宁可非只读也不能丢掉整份 SEL 数据）。
        try:
            con = sqlite3.connect(pathlib.Path(p).resolve().as_uri() + "?mode=ro", uri=True)
        except (sqlite3.Error, ValueError, OSError):
            con = sqlite3.connect(p)
        cur = con.cursor()
        cur.execute("SELECT selid, level, errornum, alerttime, status, entitytype, entityname, sensortype, sensorname, selrecord FROM sel_data ORDER BY alerttime")
        for r in cur.fetchall():
            lvl = str(r[1])
            lvl_name = levelmap.get(lvl, lvl)
            ts = parse_ts(r[3])
            status = statmap.get(str(r[4]), str(r[4]))
            events.append({
                "id": r[0], "level_code": lvl, "level": lvl_name,
                "time": ts, "status": status,
                "entity_type": r[5], "entity": r[6],
                "sensor_type": r[7], "sensor": r[8], "record": r[9],
            })
        con.close()
    except Exception as e:
        events = []
    stats["count"] = len(events)
    for e in events:
        stats["by_level"][e["level"]] = stats["by_level"].get(e["level"], 0) + 1
        ekey = f"{e['entity_type']}:{e['entity']}"
        stats["by_entity"][ekey] = stats["by_entity"].get(ekey, 0) + 1
    if events:
        stats["first_ts"] = events[0]["time"]
        stats["last_ts"] = events[-1]["time"]
    critical = [e for e in events if e["level"] == "CRITICAL"]
    return {"events": events, "stats": stats, "critical_discrete": critical}


def parse_logs_summary(info_root):
    """LogDump 关键日志的摘要/条数（供诊断人员快速定位）。"""
    logdir = os.path.join(info_root, "LogDump")
    out = {"exists": os.path.isdir(logdir), "memory_files": {}, "sizes": {}}
    interest = [
        "operate_log", "mass_operate_log", "security_log", "strategy_log",
        "maintenance_log", "ps_black_box.log", "imu_log", "dmesg_info",
        "kbox_info", "bmccom.dat", "fdm_output", "linux_kernel_log",
        "remote_log", "ipmi_mass_operate_log", "app_debug_log_all",
    ]
    for name in interest:
        p = os.path.join(logdir, name)
        if os.path.exists(p):
            out["sizes"][name] = os.path.getsize(p)
    # 内存统计关键日志数量级
    return out


def parse_syslog_events(info_root):
    """remote_log (syslog 聚合) 里的关键事件：NPU健康/电源/端口/冗余。
    SEL 可能不完整（如 dump sensor_alarm failed），syslog 是补充证据源。
    返回去重后的 非 Normal 事件 列表（含 时间/级别/内容），供报告展示与判读。
    """
    p = os.path.join(info_root, "LogDump", "remote_log")
    out = {"events": [], "npu_health": [], "power_events": [], "link_events": []}
    if not os.path.exists(p):
        return out
    txt = safe_read(p, limit_chars=1000000)
    # 行格式: <ISO-T+00:00> <host> sensor_alarm:     <id>,<time>,<level>,<code>,<Asserted|Deasserted>,<msg>
    pat = re.compile(
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\S*\s+\S+\s+\S+:\s*"
        r"\d+,\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\s*(\w+),\s*0x[0-9A-Fa-f]+,\s*(\w+),\s*(.+)")
    seen = set()
    for line in txt.splitlines():
        if "sensor_alarm" not in line:
            continue
        m = pat.search(line)
        if not m:
            continue
        ts, level, state, msg = m.group(1), m.group(2), m.group(3), m.group(4).strip()
        key = (ts, level, msg[:80])
        if key in seen:
            continue
        seen.add(key)
        ev = {"time": ts[:19], "level": level, "state": state, "msg": msg}
        out["events"].append(ev)
        low = msg.lower()
        if "npu" in low and ("degrad" in low or "health" in low or "ecc" in low):
            out["npu_health"].append(ev)
        if "power" in low or "ps" in low or "input" in low or "output" in low:
            out["power_events"].append(ev)
        if "link" in low or "port" in low or "interconnect" in low:
            out["link_events"].append(ev)
    return out


def parse_osd(info_root):
    """OSDump 录像/截图文件列表（时间戳从文件名可推断事件时刻）。"""
    d = os.path.join(info_root, "OSDump")
    out = []
    if not os.path.isdir(d):
        return out
    for f in sorted(os.listdir(d)):
        fp = os.path.join(d, f)
        if os.path.isfile(fp):
            out.append({"name": f, "size": os.path.getsize(fp)})
    return out


def parse_parsed_files(info_root):
    """按表5-79 关键文件清单，输出每个文件的 存在/大小（可追溯性）。"""
    found = []
    missing = []
    for group, rel in KEY_FILES:
        if not rel:
            p = os.path.join(info_root, group)
            if os.path.isdir(p):
                found.append({"group": group, "rel": rel or group, "exists": True, "size": -1})
            else:
                missing.append({"group": group, "rel": rel or group, "exists": False})
            continue
        p = os.path.join(info_root, group, rel)
        if os.path.isfile(p):
            try:
                sz = os.path.getsize(p)
            except Exception:
                sz = -1
            found.append({"group": group, "rel": rel, "exists": True, "size": sz})
        else:
            missing.append({"group": group, "rel": rel, "exists": False})
    return {"found_count": len(found), "missing_count": len(missing),
            "found": found[:200], "missing": missing[:100]}


# ---------------------------------------------------------------------------
# 健康判定
# ---------------------------------------------------------------------------
def score_health(data):
    """基于各维度数据给出 issue 分级 (P0/P1/P2/P3) 与总体判定。"""
    issues = []

    # 1. 当前活动告警
    ce = data.get("current_event", {})
    if ce.get("has_critical"):
        issues.append({"level": "P0", "topic": "当前活动告警", "detail": ce.get("text", "")[:500]})
    elif ce.get("text") and any(k in ce.get("text", "").lower() for k in ("minor", "warning")):
        issues.append({"level": "P3", "topic": "当前活动告警(仅Minor/提示)", "detail": ce.get("text", "")[:500]})
    elif ce.get("empty"):
        issues.append({"level": "OK", "topic": "当前活动告警", "detail": "当前无活动告警"})

    # 2. PSU
    psu = data.get("psu", [])
    psu_present = [p for p in psu if p.get("presence", "").lower() == "present"]
    if len(psu) > 0 and len(psu_present) < len(psu):
        miss = [p["slot"] for p in psu if p.get("presence", "").lower() != "present"]
        issues.append({"level": "P1", "topic": "电源在位", "detail": f"PSU 缺失: {miss} / 共{len(psu)}"})
    # 只对在位电源做 Vin/Vout 数值判读：不在位电源 Vin=0 会被误报为 P0 掉电，
    # 其缺失本身已由上面"电源在位"条目提示。
    for p in psu_present:
        try:
            vin = float(p.get("vin", 0))
            vout = float(p.get("vout", 0))
        except (TypeError, ValueError):
            continue
        if vin < RULES["psu"]["vin_min"] or vin > RULES["psu"]["vin_max"]:
            issues.append({"level": "P0", "topic": "电源输入",
                           "detail": f"PSU{p['slot']} Vin={p.get('vin')}V (AC输入异常, 正常{int(RULES['psu']['vin_min'])}~{int(RULES['psu']['vin_max'])}V)"})
        if vout < RULES["psu"]["vout_min"] or vout > RULES["psu"]["vout_max"]:
            issues.append({"level": "P0", "topic": "电源输出",
                           "detail": f"PSU{p['slot']} Vout={p.get('vout')}V 越界"})

    # 3. CPU / 内存
    mem = data.get("memory", {})
    if mem.get("bad_count"):
        bad = [f"{d.get('name')}({d.get('health')})" for d in mem.get("bad_dimms", [])][:6]
        issues.append({"level": "P1", "topic": "内存健康",
                       "detail": f"{mem.get('bad_count')} 条 DIMM 非 OK: {', '.join(bad)}"})
    cpus = data.get("cpu", [])
    cpu_not_present = [c.get("slot") for c in cpus if c.get("presence", "").lower() != "present"]
    if cpu_not_present:
        issues.append({"level": "P1", "topic": "CPU在位", "detail": f"CPU 缺失: {cpu_not_present}"})

    # 4. NPU / ECC
    npus = data.get("npu", [])
    if len(npus) < RULES["npu"]["count_expected"]:
        issues.append({"level": "P0", "topic": "NPU在位",
                       "detail": f"NPU 数量 {len(npus)} < 标准 {RULES['npu']['count_expected']}，疑似丢卡"})
    ecc = data.get("npu_ecc", {})
    for name, e in ecc.items():
        if str(e.get("multi_bit", "0")) not in ("0", "N/A", ""):
            issues.append({"level": "P0", "topic": "NPU ECC 多bit",
                           "detail": f"{name} MultiBitEcc={e.get('multi_bit')}，疑似硬件故障"})
        elif str(e.get("single_bit", "0")) not in ("0", "N/A", ""):
            issues.append({"level": "P2", "topic": "NPU ECC 单bit",
                           "detail": f"{name} SingleBitEcc={e.get('single_bit')}，关注趋势"})

    # 5. 光模块 / 端口抖动
    opt = data.get("optical", {})
    n_opt = len(opt.get("static", []))
    if 0 < n_opt < RULES["optical"]["count_expected"]:
        issues.append({"level": "P2", "topic": "光模块在位",
                       "detail": f"光模块 {n_opt} < {RULES['optical']['count_expected']}"})
    flaps = {}
    for e in opt.get("port_events", []):
        flaps.setdefault(e["port"], {"up": 0, "down": 0})
        flaps[e["port"]][e["event"]] += 1
    for port, cnt in flaps.items():
        if cnt["down"] >= 5:
            issues.append({"level": "P2", "topic": "NPU端口抖动",
                           "detail": f"{port} 断开{cnt['down']}次/建链{cnt['up']}次，需关注光路/模块"})

    # 6. 温度/风扇 —— 区分模拟量(ok 应正常)与离散量(0x8000 等表示无状态/正常)
    sensors = data.get("sensors", [])
    analog_units = ("degrees C", "Volts", "Watts", "RPM", "degrees c")
    for s in sensors:
        status = (s.get("status") or "").lower()
        name = s.get("name", "")
        unit = s.get("unit", "")
        # 模拟量：status 应为 ok；否则异常
        if any(u in unit for u in analog_units):
            if status not in ("ok", "na", ""):
                issues.append({"level": "P2", "topic": "传感器异常",
                               "detail": f"{name}(模拟量) status={s.get('status')}"})
        else:
            # 离散量：0x8000=无状态/正常, 0x8001=正常, 0x8002..0x8004=状态/在位位掩码
            # 只有明确为故障的码(如 0x8009 电源输入丢失)才告警，其余位掩码不误报。
            st = s.get("status", "")
            if st.upper() == "0X8009":
                issues.append({"level": "P1", "topic": "离散传感器异常",
                               "detail": f"{name} status={st}（电源输入丢失）"})
            elif st.upper() in ("0X800A", "0X8008"):
                issues.append({"level": "P3", "topic": "离散传感器状态",
                               "detail": f"{name} status={st}（需对照SEL确认）"})
    # 关键温度
    for key in ("Inlet Temp", "NPUBoard Temp1"):
        for s in sensors:
            if s.get("name") == key:
                try:
                    v = float(s.get("value", 0))
                except ValueError:
                    continue
                if v >= RULES["temp"]["inlet_major"]:
                    issues.append({"level": "P1", "topic": "进风温度",
                                   "detail": f"{key}={v}C >= Major阈值"})
                elif v >= RULES["temp"]["inlet_minor"]:
                    issues.append({"level": "P2", "topic": "进风温度",
                                   "detail": f"{key}={v}C >= Minor阈值"})
    # 风扇转速：只对在位风扇判读；不在位风扇的转速为 0/空，会误报低转速
    fan_detail = data.get("fan_detail", [])
    _fan_here = ("present", "yes", "true", "1", "")
    fan_absent = [f.get("name", "?") for f in fan_detail
                  if str(f.get("presence", "")).lower() not in _fan_here]
    if fan_absent:
        issues.append({"level": "P1", "topic": "风扇在位",
                       "detail": f"风扇缺失/不在位: {fan_absent}"})
    for f in fan_detail:
        if str(f.get("presence", "")).lower() not in _fan_here:
            continue
        spd = f.get("speed", "")
        m = re.search(r"(\d+)", spd.split("/")[0] if "/" in spd else spd)
        if m and int(m.group(1)) < RULES["fan"]["rpm_min"]:
            issues.append({"level": "P2", "topic": "风扇转速",
                           "detail": f"{f.get('name')} 转速 {spd} RPM < {RULES['fan']['rpm_min']}"})

    # 7. RAID/存储
    raid = data.get("raid", {})
    ch = raid.get("controller", {})
    if ch.get("health") and ch["health"] != RULES["raid"]["controller_ok"]:
        issues.append({"level": "P0", "topic": "RAID控制器",
                       "detail": f"Controller Health={ch['health']}"})
    if raid.get("bbu", {}).get("health") and raid["bbu"]["health"] != RULES["raid"]["bbu_ok"]:
        issues.append({"level": "P1", "topic": "RAID BBU", "detail": f"BBU Health={raid['bbu']['health']}"})
    for d in raid.get("physical_drives", []):
        hs = d.get("Health Status", "")
        if hs and hs != "正常" and "normal" not in hs.lower():
            issues.append({"level": "P1", "topic": "磁盘健康",
                           "detail": f"{d.get('Device Name')} Health={hs}"})
    if raid.get("controller", {}).get("ddr_ecc") not in (None, "", "0", "N/A"):
        issues.append({"level": "P1", "topic": "RAID DDR ECC",
                       "detail": f"DDR ECC Count={raid['controller']['ddr_ecc']}"})
    if not raid.get("logical_drives"):
        # 确认是否纯直通(HBA)配置：若控制器模式为 HBA 或物理盘存在但无逻辑盘，
        # 需人工确认交付规划，不一律判为问题
        if raid.get("controller", {}).get("mode", "").upper() not in ("HBA", "JBOD", "PASSTHROUGH"):
            issues.append({"level": "P2", "topic": "逻辑盘", "detail": "未发现逻辑盘(生产机应配置RAID逻辑盘，需确认交付规划)"})
        else:
            issues.append({"level": "P3", "topic": "逻辑盘", "detail": "未发现逻辑盘，控制器为直通模式(HBA/JBOD)，需确认交付规划"})

    # 8. BMC 自身健康 (SEL 中日志满/证书/温度越限)
    sel = data.get("sel", {}).get("events", [])
    for e in sel:
        rec = e.get("record", "")
        lvl = e.get("level")
        if "Op. Log Full" in rec and lvl != "INFO":
            issues.append({"level": "P1", "topic": "操作日志满", "detail": rec})
        if "Sec. Log Full" in rec:
            issues.append({"level": "P1", "topic": "安全日志满", "detail": rec})
        if "Cert OverDue" in rec:
            issues.append({"level": "P1", "topic": "证书过期", "detail": rec})
        if "SEL almost full" in rec:
            issues.append({"level": "P1", "topic": "SEL空间", "detail": rec})
        if "Sensor access degraded" in rec:
            # 关键字是历史事件：必须与当前 sensor_info 快照交叉——
            # 当前对应传感器 ok → 已恢复(P3)；当前仍 na/异常 → 当前风险(P2)
            m_s = re.search(r"Sensor is[:\s]*([^,]+)", rec)
            sensor_key = m_s.group(1).strip() if m_s else rec
            cur_ok = False
            for s in sensors:
                nm = s.get("name", "")
                if nm and (nm in sensor_key or sensor_key in nm):
                    if s.get("status") == "ok":
                        cur_ok = True
                    break
            if cur_ok:
                issues.append({"level": "P3", "topic": "传感器访问降级(历史,已恢复)",
                               "detail": rec + "；当前对应传感器 status=ok，判定已恢复。"})
            else:
                issues.append({"level": "P2", "topic": "传感器访问降级",
                               "detail": rec + "；当前对应传感器不可读/异常，需确认。"})

    # 8b. syslog(NPU健康/电源/端口事件)——SEL 不全时的补充证据
    sys_ev = data.get("syslog_events", {})
    npu_health = sys_ev.get("npu_health", [])
    if npu_health:
        # 仅当存在 "degraded ... Error Code: 非NA" 的 Asserted 事件才提示
        real = [e for e in npu_health
                if "degrad" in e.get("msg", "").lower() and "error code:" in e.get("msg", "").lower()]
        if real:
            deets = sorted({f"{e['time']} {e['level']} {e['msg'][:90]}" for e in real})
            issues.append({"level": "P2", "topic": "NPU健康事件(syslog)",
                           "detail": "; ".join(deets[:6]) + f"（共{len(real)}条，多为瞬时降级后恢复）"})

    # 9. 指示灯
    leds = data.get("led", {})
    for name, info in leds.items():
        st = info.get("State", "")
        color = info.get("Color", "")
        if name.startswith("SysHealLed") and ("BLINKING" in st.upper() or "RED" in color.upper()):
            issues.append({"level": "P0" if "RED" in color.upper() else "P1",
                           "topic": "系统健康灯", "detail": f"{name}: {st}/{color}"})

    # 10. SEL Critical 历史 —— 需与"当前快照"交叉：当前 PSU 全 present 且 Vin 正常
    #    => 历史 Critical（掉电/输入丢失）已恢复，仅 P3 记录，不误报当前故障。
    crit = data.get("sel", {}).get("critical_discrete", [])
    psu_all_ok = False
    if data.get("psu"):
        psu_present = [p for p in data["psu"] if p.get("presence", "").lower() == "present"]
        vin_ok = True
        for p in data["psu"]:
            try:
                if float(p.get("vin", 0)) < RULES["psu"]["vin_min"]:
                    vin_ok = False
            except (TypeError, ValueError):
                vin_ok = False
        psu_all_ok = len(psu_present) == len(data["psu"]) and vin_ok and len(data["psu"]) > 0
    if crit:
        # 电源类 Critical：entity/sensor/record 含 "Power" 或 "PS" 或 "Supply"
        power_crit = [e for e in crit
                      if "Power" in (e.get("entity") or "") or "Power" in (e.get("record") or "")]
        other_crit = [e for e in crit if e not in power_crit]
        if power_crit and not psu_all_ok:
            deets = sorted({f"{e['entity']}: {e['record']} @ {e['time']}" for e in power_crit})
            issues.append({"level": "P1", "topic": "电源Critical(疑似活动中)",
                           "detail": "; ".join(deets[:6]) + f"（当前PSU快照: {len([p for p in data['psu'] if p.get('presence')=='present'])}/{len(data['psu'])}在位）"})
        elif power_crit:
            deets = sorted({f"{e['entity']}: {e['record']} @ {e['time']}" for e in power_crit[-6:]})
            issues.append({"level": "P3", "topic": "电源Critical历史(已恢复)",
                           "detail": "; ".join(deets[:6]) + "（当前PSU全部在位且输入正常，判定为已恢复的历史事件）"})
        for e in other_crit:
            issues.append({"level": "P1", "topic": "其它Critical记录",
                           "detail": f"{e['entity']}: {e['record']} @ {e['time']}"})

    # 11. 系统重启：先看时间分布，再决定级别（不要只看次数）。
    unexpected_restarts = [
        e for e in sel
        if ("SysRestart" in e.get("sensor", "") or "System Restart" in e.get("record", ""))
        and ("[IPMB]" in e.get("record", "") or "watchdog" in e.get("record", "").lower())
    ]
    if unexpected_restarts:
        times = [e.get("time", "") for e in unexpected_restarts if e.get("time")]
        times.sort()
        last_ts = times[-1] if times else ""
        # 距样本收集时间（若可取得）的天数；无法取得则保守 0
        collected = data.get("collected_at", "")
        days_since = None
        if last_ts and collected:
            try:
                from datetime import datetime as _dt
                d1 = _dt.strptime(last_ts, "%Y-%m-%d %H:%M:%S")
                d2 = _dt.strptime(collected, "%Y-%m-%d %H:%M:%S")
                days_since = (d2 - d1).days
            except Exception:
                days_since = None
        n = len(unexpected_restarts)
        spread = f"时间跨度 {times[0]} ~ {last_ts}" if len(times) > 1 else f"仅 {last_ts}"
        if days_since is not None and days_since >= 7 and n < 10:
            # 重启集中在过去，且近期（≥7天）无重启 → 判交付/历史期事件
            issues.append({"level": "P3", "topic": "异常重启(历史/交付期)",
                           "detail": f"SEL中{n}次[IPMB]/watchdog重启，{spread}；距收集日{days_since}天无新重启，"
                                     "可能是交付期操作(升级/KVM/BIOS写盘)所致，建议观察。"})
        elif days_since is None and n < 10:
            # 距今天数无法判定（缺收集时间或时间解析失败）时不再落入 P2，
            # 降级为 P3 记录，避免把历史重启误判为近期问题。
            issues.append({"level": "P3", "topic": "系统异常重启记录",
                           "detail": f"SEL中{n}次[IPMB]/watchdog重启，{spread}；距收集日无法确认"
                                     "（缺收集时间或时间解析失败），请人工核对时间线。"})
        elif n >= 5:
            issues.append({"level": "P2", "topic": "系统异常重启较多",
                           "detail": f"SEL中{n}次异常重启，{spread}；若覆盖用户报障时间点，"
                                     "需结合OS/dmesg/掉电时间线定位，并对照operate_log确认是否交付期操作。"})
        elif n >= 2:
            issues.append({"level": "P3", "topic": "系统异常重启记录",
                           "detail": f"SEL中{n}次异常重启，{spread}；建议关注时间线。"})

    # 汇总：先去重(同 topic+detail 只保留一条)，再排序
    seen = {}
    for i in issues:
        key = (i["level"], i["topic"], i["detail"])
        if key not in seen:
            seen[key] = i
    issues = list(seen.values())
    level_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "OK": 4}
    issues_sorted = sorted(issues, key=lambda x: level_order.get(x["level"], 9))
    has_p0 = any(i["level"] == "P0" for i in issues_sorted)
    has_p1 = any(i["level"] == "P1" for i in issues_sorted)
    if has_p0:
        verdict = "不正常"
    elif has_p1:
        verdict = "有风险"
    elif any(i["level"] in ("P2", "P3") for i in issues_sorted):
        verdict = "基本正常（存在需关注项）"
    else:
        verdict = "正常"
    return {"verdict": verdict, "issues": issues_sorted,
            "counts": {lvl: sum(1 for i in issues_sorted if i["level"] == lvl)
                       for lvl in ("P0", "P1", "P2", "P3", "OK")}}


# ---------------------------------------------------------------------------
# 关键指标汇总（供单机报告顶部 + 多机对比矩阵使用）
# ---------------------------------------------------------------------------
def build_ranks(data):
    """提取一台机器的所有关键指标为扁平 dict（用于多机对比/报告速览）。"""
    ident = data.get("identity", {})
    ver = data.get("versions", {})
    psu = data.get("psu", [])
    npus = data.get("npu", [])
    psu_present = sum(1 for p in psu if str(p.get("presence", "")).lower() == "present")
    vin = ""
    vout = ""
    if psu:
        vins = [p.get("vin") for p in psu if p.get("vin")]
        vouts = [p.get("vout") for p in psu if p.get("vout")]
        vin = vins[0] if vins else ""
        vout = vouts[0] if vouts else ""
    ecc = data.get("npu_ecc", {})
    multi_ecc = sum(_get_int(v.get("multi_bit"), 0) for v in ecc.values()) if isinstance(ecc, dict) else 0
    single_ecc = sum(_get_int(v.get("single_bit"), 0) for v in ecc.values()) if isinstance(ecc, dict) else 0
    opt = data.get("optical", {}) or {}
    n_opt = len(opt.get("static", []))
    n_port_events = len(opt.get("port_events", []))
    sensors = data.get("sensors", [])
    inlet = next((s.get("value") for s in sensors if "nlet" in str(s.get("name", ""))), "")
    hbm = [s.get("value") for s in sensors if "HBM" in str(s.get("name", "")) and s.get("value")]
    hbm_worst = ""
    if hbm:
        try:
            hbm_worst = max(float(h) for h in hbm)
        except ValueError:
            hbm_worst = ""
    mem = data.get("memory", {})
    raid = data.get("raid", {})
    sel = data.get("sel", {}).get("stats", {})
    ce = data.get("current_event", {})
    net = data.get("network", {}).get("eth_groups", [])
    first_eth = net[0] if net else {}
    return {
        "product_name": ident.get("product_name") or ver.get("product_name", ""),
        "product_sn": ident.get("product_sn", ""),
        "board_name": ident.get("board_name", ""),
        "model": ident.get("model", ""),
        "ibmc": ver.get("ibmc", ""),
        "bios": ver.get("bios", ""),
        "cpld": ver.get("cpld", ""),
        "rtos": ver.get("rtos_release", ""),
        "hostname": data.get("time_config", {}).get("hostname", ""),
        "timezone": data.get("time_config", {}).get("timezone", ""),
        "mgmt_ip": first_eth.get("IP Address", ""),
        "net_mode": first_eth.get("Net Mode", ""),
        "vlan": first_eth.get("Dedicated Port VLAN State", ""),
        "cpu_count": len(data.get("cpu", [])),
        "cpu_model": data.get("cpu", [{}])[0].get("model", "") if data.get("cpu") else "",
        "mem_count": mem.get("count", 0),
        "mem_total_gb": mem.get("total_gb", 0),
        "mem_bad": mem.get("bad_count", 0),
        "psu_count": len(psu),
        "psu_present": psu_present,
        "psu_vin": vin,
        "psu_vout": vout,
        "npu_count": len(npus),
        "npu_single_ecc": single_ecc,
        "npu_multi_ecc": multi_ecc,
        "optical_count": n_opt,
        "port_events": n_port_events,
        "inlet_temp": inlet,
        "hbm_worst": hbm_worst,
        "fan_count": len(data.get("fan_detail", [])),
        "raid_health": raid.get("controller", {}).get("health", ""),
        "raid_mode": raid.get("controller", {}).get("mode", ""),
        "logical_drives": len(raid.get("logical_drives", [])),
        "physical_drives": len(raid.get("physical_drives", [])),
        "sel_count": sel.get("count", 0),
        "sel_critical": sel.get("by_level", {}).get("CRITICAL", 0),
        "sel_major": sel.get("by_level", {}).get("MAJOR", 0),
        "current_alarm": "Critical" if ce.get("has_critical") else ("空" if ce.get("empty") else "有内容"),
        "os_name": data.get("sp_asset", {}).get("sp_version", {}).get("OSVersion", ""),
        "esn": data.get("license", {}).get("esn", ""),
        "license_status": data.get("license", {}).get("license_status", ""),
        "nand_lifetime": data.get("nand", {}).get("remaining_lifetime", ""),
        "nand_total_written": data.get("nand", {}).get("total_written", ""),
        "bios_items": data.get("bios", {}).get("count", 0),
        "collected_at": data.get("collected_at", ""),
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def parse_one(root):
    info_root = ensure_root(root)
    machine_tag = os.path.basename(os.path.normpath(root))
    fruit = parse_fruinfo(info_root)
    data = {
        "source_root": os.path.normpath(root),
        "machine_tag": machine_tag,
        "collected_at": "",
        "identity": fruit,
        "versions": parse_versions(info_root),
        "bios": parse_bios(info_root),
        "current_event": parse_current_event(info_root),
        "led": parse_led(info_root),
        "sensors": parse_sensors(info_root, limit=400),
        "sensor_problems": parse_sensors(info_root, only_problem=True),
        "psu": parse_psu(info_root),
        "cpu": parse_cpu(info_root),
        "memory": parse_memory(info_root),
        "fan_detail": parse_fan_detail(info_root),
        "npu": parse_npu(info_root),
        "npu_ecc": parse_npu_ecc(info_root),
        "optical": parse_optical(info_root),
        "raid": parse_raid(info_root),
        "network": parse_network(info_root),
        "network_os": parse_network_os(info_root),
        "time_config": parse_time_config(info_root),
        "ibmc_sys": parse_ibmc_sys(info_root),
        "cards": parse_cards(info_root),
        "register": parse_register(info_root),
        "license": parse_license(info_root),
        "sp_asset": parse_sp_asset(info_root),
        "nginx": parse_nginx(info_root),
        "utilization": parse_utilization(info_root),
        "power_stat": parse_power_stat(info_root),
        "bios_summary": parse_bios_summary(info_root),
        "nand": parse_nand(info_root),
        "lldp": parse_lldp(info_root),
        "mcinfo": parse_mcinfo(info_root),
        "sel": parse_sel(info_root),
        "logs_summary": parse_logs_summary(info_root),
        "syslog_events": parse_syslog_events(info_root),
        "osd_files": parse_osd(info_root),
        "parsed_files": parse_parsed_files(info_root),
    }
    # 收集时间从 dump_log
    dl = safe_read(find_file(info_root, "dump_log"), limit_chars=500)
    m = re.search(r"begin at\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", dl)
    if m:
        data["collected_at"] = m.group(1)
    data["health"] = score_health(data)
    data["ranks"] = build_ranks(data)
    return data


def build_comparison(all_data):
    """多机比对：按字段×机器 的矩阵。字段取自每台机器的 ranks + 判定。"""
    if not all_data:
        return {"fields": [], "machines": []}
    rank_keys = sorted({k for d in all_data for k in d.get("ranks", {})})
    rows = []
    for d in all_data:
        r = d.get("ranks", {})
        h = d.get("health", {})
        rows.append({
            "machine_tag": d.get("machine_tag", ""),
            "product_sn": r.get("product_sn", ""),
            "verdict": h.get("verdict", ""),
            "counts": h.get("counts", {}),
            "fields": {k: r.get(k, "") for k in rank_keys},
        })
    return {"fields": rank_keys, "machines": rows}


def main():
    # Windows 控制台默认 cp936，打印中文/特殊字符时可能 UnicodeEncodeError
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="iBMC 一键收集日志 → 结构化 JSON + 健康评分")
    ap.add_argument("roots", nargs="+", help="一个或多个日志根目录")
    ap.add_argument("-o", "--output-dir", required=True, help="输出目录")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    all_data = []
    for root in args.roots:
        print(f"[parse] {root}")
        try:
            d = parse_one(root)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  !! 解析失败: {e}")
            continue
        # 用目录名(machine_tag)保证唯一，真实部署每个机器目录名不同
        unique = re.sub(r'[\\/:*?"<>|]', "_", d["machine_tag"])[-60:]
        outpath = os.path.join(args.output_dir, f"{unique}_bmc.json")
        with open(outpath, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2, default=str)
        print(f"  -> {outpath} | verdict={d['health']['verdict']} | "
              f"P0={d['health']['counts']['P0']} P1={d['health']['counts']['P1']} "
              f"P2={d['health']['counts']['P2']} P3={d['health']['counts']['P3']}")
        all_data.append(d)

    if len(all_data) > 1:
        outpath = os.path.join(args.output_dir, "all_machines_bmc.json")
        with open(outpath, "w", encoding="utf-8") as f:
            json.dump({"machines": all_data, "count": len(all_data),
                       "comparison": build_comparison(all_data)},
                      f, ensure_ascii=False, indent=2, default=str)
        print(f"  [multi] -> {outpath}")

    print("done.")


if __name__ == "__main__":
    main()
