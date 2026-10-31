#!/usr/bin/env python3
"""
cluster_data_extractor.py
Ascend 集群性能数据提取器 — 自动识别 DB/TEXT 格式，提取全景数据，输出 JSON。

修复记录:
  1. DB 文件名识别: cluster.db (旧) + cluster_analysis.db (新，在 cluster_analysis_output/ 下)
  2. SQL index 保留字: 用双引号包裹
  3. TEXT 路径检测: 支持直接路径和嵌套路径两种
  4. TEXT base_info: 从 communication_group.json 或 CSV 提取 rank 信息
  5. cluster_communication.json 解析: 提取通信算子耗时
  6. cluster_communication_matrix.json 解析: 提取通信矩阵 (4 层嵌套 JSON)
  7. TEXT 模式 rank fallback: 当 communication_group.json 为空时，从 CSV 提取 rank 列表
"""
import argparse
import csv
import json
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime


# ==================== 格式检测 ====================

def detect_format(data_dir):
    """识别数据格式: db_old / db_new / text / mixed

    DB 文件名:
      - cluster.db (旧格式，通常在根目录)
      - cluster_analysis.db (新格式，在 cluster_analysis_output/ 下)
    TEXT 文件:
      - cluster_step_trace_time.csv (在 cluster_analysis_output/ 下或直接在 data_dir 下)
    """
    result = {"format": "unknown", "db_path": None, "text_dir": None}

    # --- DB 检测 ---
    # 1. cluster.db (旧格式) — 在根目录或 cluster_analysis_output/ 下
    for db_candidate in [
        os.path.join(data_dir, "cluster.db"),
        os.path.join(data_dir, "cluster_analysis_output", "cluster.db"),
    ]:
        if os.path.exists(db_candidate):
            result["db_path"] = db_candidate
            result["format"] = "db_old"
            break

    # 2. cluster_analysis.db (新格式) — 在 cluster_analysis_output/ 下
    new_db = os.path.join(data_dir, "cluster_analysis.db")
    if not os.path.isfile(new_db):
        new_db = os.path.join(data_dir, "cluster_analysis_output", "cluster_analysis.db")
    if os.path.exists(new_db):
        if result["format"] == "db_old":
            result["format"] = "mixed"
        else:
            result["format"] = "db_new"
        result["db_path"] = new_db

    # --- TEXT 检测 ---
    # 支持两种路径:
    #   a) data_dir/cluster_step_trace_time.csv (用户直接提供 cluster_analysis_output 目录)
    #   b) data_dir/cluster_analysis_output/cluster_step_trace_time.csv (嵌套结构)
    text_csv_direct = os.path.join(data_dir, "cluster_step_trace_time.csv")
    text_csv_nested = os.path.join(data_dir, "cluster_analysis_output", "cluster_step_trace_time.csv")

    if os.path.exists(text_csv_direct):
        if result["format"] in ("db_old", "db_new"):
            result["format"] = "mixed"
        else:
            result["format"] = "text"
        result["text_dir"] = data_dir
    elif os.path.exists(text_csv_nested):
        if result["format"] in ("db_old", "db_new"):
            result["format"] = "mixed"
        else:
            result["format"] = "text"
        result["text_dir"] = os.path.join(data_dir, "cluster_analysis_output")

    return result


# ==================== DB 工具函数 ====================

def get_table_list(conn):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [row[0] for row in cur.fetchall()]


def get_columns(conn, table):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]


def quote_field(field_name):
    """处理 SQL 保留字字段名，用双引号包裹"""
    sql_reserved = {"index", "order", "group", "key", "value", "table", "select", "from", "where", "type"}
    if field_name.lower() in sql_reserved:
        return f'"{field_name}"'
    return field_name


def query_to_dicts(conn, sql, params=None):
    cur = conn.cursor()
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def build_step_summary(rows, f_step, f_compute, f_comm, f_free, f_stage, f_overlap):
    """从行数据构建 step_summary 和 rank_summary（复用逻辑）"""
    step_summary = {}
    rank_summary = {}
    for r in rows:
        sid = str(r.get(f_step, "?"))
        rid = str(r.get("rank_id", r.get("index", r.get("Index", "?"))))
        if sid not in step_summary:
            step_summary[sid] = {"compute": [], "comm": [], "free": [], "stage": [], "overlap": []}
        s = step_summary[sid]
        s["compute"].append(float(r.get(f_compute, 0) or 0))
        s["comm"].append(float(r.get(f_comm, 0) or 0))
        s["free"].append(float(r.get(f_free, 0) or 0))
        s["stage"].append(float(r.get(f_stage, 0) or 0))
        s["overlap"].append(float(r.get(f_overlap, 0) or 0))

        if rid not in rank_summary:
            rank_summary[rid] = {"compute": [], "comm": [], "free": [], "stage": []}
        rs = rank_summary[rid]
        rs["compute"].append(float(r.get(f_compute, 0) or 0))
        rs["comm"].append(float(r.get(f_comm, 0) or 0))
        rs["free"].append(float(r.get(f_free, 0) or 0))
        rs["stage"].append(float(r.get(f_stage, 0) or 0))

    # 求均值
    result_step = {}
    for sid, s in step_summary.items():
        n = len(s["compute"])
        result_step[sid] = {
            "avg_compute": round(sum(s["compute"]) / n, 2),
            "avg_comm": round(sum(s["comm"]) / n, 2),
            "avg_free": round(sum(s["free"]) / n, 2),
            "avg_stage": round(sum(s["stage"]) / n, 2),
            "avg_overlap": round(sum(s["overlap"]) / n, 2),
        }
    result_rank = {}
    for rid, rs in rank_summary.items():
        n = len(rs["compute"])
        result_rank[rid] = {
            "avg_compute": round(sum(rs["compute"]) / n, 2),
            "avg_comm": round(sum(rs["comm"]) / n, 2),
            "avg_free": round(sum(rs["free"]) / n, 2),
            "avg_stage": round(sum(rs["stage"]) / n, 2),
        }
    return result_step, result_rank


# ==================== DB 旧格式提取 (cluster.db) ====================

def extract_db_old(db_path):
    data = {"format": "db_old", "tables_found": [], "tables_empty": []}
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    conn.row_factory = sqlite3.Row
    tables = get_table_list(conn)
    data["tables_found"] = tables

    # cluster_base_info
    if "cluster_base_info" in tables:
        rows = query_to_dicts(conn, "SELECT key, value FROM cluster_base_info")
        data["base_info"] = {row["key"]: row["value"] for row in rows}

    # step_statistic_info
    if "step_statistic_info" in tables:
        rows = query_to_dicts(conn, "SELECT * FROM step_statistic_info ORDER BY step_id, rank_id")
        if rows:
            data["step_statistic"] = rows
            ss, rs = build_step_summary(rows, "step_id", "compute_time", "communication_time",
                                        "free_time", "stage_time", "overlap_communication_time")
            data["step_summary"] = ss
            data["rank_summary"] = rs
        else:
            data["tables_empty"].append("step_statistic_info")
    else:
        data["tables_empty"].append("step_statistic_info")

    # communication_time_info
    if "communication_time_info" in tables:
        rows = query_to_dicts(conn,
            "SELECT op_name, AVG(elapse_time) as avg_elapsed, AVG(transit_time) as avg_transit, "
            "AVG(wait_time) as avg_wait, AVG(synchronization_time) as avg_sync "
            "FROM communication_time_info GROUP BY op_name ORDER BY avg_elapsed DESC LIMIT 20")
        if rows:
            data["comm_time_ops"] = rows
        else:
            data["tables_empty"].append("communication_time_info")

    # communication_bandwidth_info
    if "communication_bandwidth_info" in tables:
        rows = query_to_dicts(conn,
            "SELECT transport_type, AVG(bandwidth_size) as avg_bw, AVG(transit_size) as avg_size, "
            "AVG(transit_time) as avg_time FROM communication_bandwidth_info GROUP BY transport_type")
        if rows:
            data["comm_bandwidth"] = rows
        else:
            data["tables_empty"].append("communication_bandwidth_info")

    # communication_matrix
    if "communication_matrix" in tables:
        rows = query_to_dicts(conn,
            "SELECT src_rank, dst_rank, transport_type, AVG(bandwidth) as avg_bw, "
            "AVG(transit_size) as avg_size FROM communication_matrix "
            "GROUP BY src_rank, dst_rank, transport_type LIMIT 50")
        if rows:
            data["comm_matrix"] = rows
        else:
            data["tables_empty"].append("communication_matrix")

    conn.close()
    return data


# ==================== DB 新格式提取 (cluster_analysis.db) ====================

def extract_db_new(db_path):
    data = {"format": "db_new", "tables_found": [], "tables_empty": []}
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    conn.row_factory = sqlite3.Row
    tables = get_table_list(conn)
    data["tables_found"] = tables
    if 'ClusterBaseInfo' in tables:
        data['base_info'] = {r['key']: r['value'] for r in query_to_dicts(conn, 'SELECT key, value FROM ClusterBaseInfo')}
        distributed = data['base_info'].get('distributed_args')
        if distributed:
            try:
                args = json.loads(distributed)
                data['base_info'].update({k: str(v) for k, v in args.items()})
                for key, source in [('tp_size', 'tensor_model_parallel_size'), ('pp_size', 'pipeline_model_parallel_size')]:
                    data['base_info'][key] = str(args.get(source, 1))
            except (TypeError, ValueError):
                data.setdefault('warnings', []).append('ClusterBaseInfo.distributed_args invalid JSON')
    # New ClusterCommunicationTime schema stores ms (also verified against native output).
    data['units'] = {'step_time': 'us', 'communication_time': data.get('base_info', {}).get('communication_time_unit', 'ms')}

    # 确定步骤表名
    step_table = None
    for t in ["ClusterStepTraceTime", "step_statistic_info"]:
        if t in tables:
            step_table = t
            break

    if step_table:
        cols = get_columns(conn, step_table)
        # 自适应字段名
        f_step = "step" if "step" in cols else "step_id"
        f_type = "type" if "type" in cols else None
        f_index = "index" if "index" in cols else "rank_id"
        f_compute = "computing" if "computing" in cols else "compute_time"
        f_comm = "communication" if "communication" in cols else "communication_time"
        f_free = "free" if "free" in cols else "free_time"
        f_stage = "stage" if "stage" in cols else "stage_time"
        f_overlap = "overlapped" if "overlapped" in cols else "overlap_communication_time"

        # 修复: index 是 SQL 保留字，用双引号包裹
        f_index_sql = quote_field(f_index)
        f_step_sql = quote_field(f_step)

        type_filter = f" WHERE {f_type} = 'rank'" if f_type else ""
        # 使用引号包裹的字段名构建 ORDER BY
        order_clause = f" ORDER BY {f_step_sql}, {f_index_sql}"
        rows = query_to_dicts(conn, f"SELECT * FROM {step_table}{type_filter}{order_clause}")

        if rows:
            data["step_statistic"] = rows
            ss, rs = build_step_summary(rows, f_step, f_compute, f_comm, f_free, f_stage, f_overlap)
            data["step_summary"] = ss
            data["rank_summary"] = rs
        else:
            data["tables_empty"].append(step_table)
    else:
        data["tables_empty"].append("step_table")

    # ClusterCommunicationTime
    if "ClusterCommunicationTime" in tables:
        rows = query_to_dicts(conn,
            "SELECT hccl_op_name, AVG(elapsed_time) as avg_elapsed, AVG(transit_time) as avg_transit, "
            "AVG(wait_time) as avg_wait, AVG(synchronization_time) as avg_sync, AVG(idle_time) as avg_idle "
            "FROM ClusterCommunicationTime GROUP BY hccl_op_name ORDER BY avg_elapsed DESC LIMIT 20")
        if rows:
            data["comm_time_ops"] = [r for r in rows if r['hccl_op_name'] not in ('Total Op Info', 'Total', 'total', 'all')]
        else:
            data["tables_empty"].append("ClusterCommunicationTime")

    # ClusterCommunicationBandwidth
    if "ClusterCommunicationBandwidth" in tables:
        rows = query_to_dicts(conn,
            "SELECT band_type, AVG(bandwidth) as avg_bw, AVG(transit_size) as avg_size, "
            "AVG(transit_time) as avg_time FROM ClusterCommunicationBandwidth GROUP BY band_type")
        if rows:
            data["comm_bandwidth"] = rows
        else:
            data["tables_empty"].append("ClusterCommunicationBandwidth")

    # ClusterCommunicationMatrix
    if "ClusterCommunicationMatrix" in tables:
        rows = query_to_dicts(conn,
            "SELECT src_rank, dst_rank, transport_type, AVG(CAST(bandwidth AS REAL)) as avg_bw, "
            "AVG(transit_size) as avg_size FROM ClusterCommunicationMatrix "
            "GROUP BY src_rank, dst_rank, transport_type LIMIT 50")
        if rows:
            data["comm_matrix"] = rows
        else:
            data["tables_empty"].append("ClusterCommunicationMatrix")

    # CommunicationGroupMapping
    if "CommunicationGroupMapping" in tables:
        rows = query_to_dicts(conn, "SELECT * FROM CommunicationGroupMapping")
        if rows:
            data["comm_group_mapping"] = rows
        else:
            data["tables_empty"].append("CommunicationGroupMapping")

    conn.close()
    return data


# ==================== TEXT 模式提取 ====================

def extract_text(text_dir):
    data = {"format": "text", "tables_found": [], "tables_empty": []}

    # --- 1. cluster_step_trace_time.csv ---
    csv_path = os.path.join(text_dir, "cluster_step_trace_time.csv")
    if os.path.exists(csv_path):
        data["tables_found"].append("cluster_step_trace_time.csv")
        rows = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        if rows:
            rank_rows = [r for r in rows if r.get("Type") == "rank"]
            data["step_statistic"] = rank_rows
            # 构建 step_summary 和 rank_summary
            step_summary = {}
            rank_summary = {}
            csv_ranks = set()  # 修复: 收集 CSV 中的 rank ID 用于 fallback
            for r in rank_rows:
                sid = str(r.get("Step", "?"))
                rid = str(r.get("Index", "?"))
                csv_ranks.add(rid)
                if sid not in step_summary:
                    step_summary[sid] = {"compute": [], "comm": [], "free": [], "stage": [], "overlap": []}
                s = step_summary[sid]
                s["compute"].append(float(r.get("Computing", 0) or 0))
                s["comm"].append(float(r.get("Communication", 0) or 0))
                s["free"].append(float(r.get("Free", 0) or 0))
                s["stage"].append(float(r.get("Stage", 0) or 0))
                s["overlap"].append(float(r.get("Overlapped", 0) or 0))
                if rid not in rank_summary:
                    rank_summary[rid] = {"compute": [], "comm": [], "free": [], "stage": []}
                rs = rank_summary[rid]
                rs["compute"].append(float(r.get("Computing", 0) or 0))
                rs["comm"].append(float(r.get("Communication", 0) or 0))
                rs["free"].append(float(r.get("Free", 0) or 0))
                rs["stage"].append(float(r.get("Stage", 0) or 0))
            data["step_summary"] = {}
            for sid, s in step_summary.items():
                n = len(s["compute"])
                data["step_summary"][sid] = {
                    "avg_compute": round(sum(s["compute"]) / n, 2),
                    "avg_comm": round(sum(s["comm"]) / n, 2),
                    "avg_free": round(sum(s["free"]) / n, 2),
                    "avg_stage": round(sum(s["stage"]) / n, 2),
                    "avg_overlap": round(sum(s["overlap"]) / n, 2),
                }
            data["rank_summary"] = {}
            for rid, rs in rank_summary.items():
                n = len(rs["compute"])
                data["rank_summary"][rid] = {
                    "avg_compute": round(sum(rs["compute"]) / n, 2),
                    "avg_comm": round(sum(rs["comm"]) / n, 2),
                    "avg_free": round(sum(rs["free"]) / n, 2),
                    "avg_stage": round(sum(rs["stage"]) / n, 2),
                }
            # 修复: 保存 CSV rank 列表用于 fallback
            data["_csv_ranks"] = sorted(csv_ranks, key=lambda x: int(x) if x.isdigit() else 999)
        else:
            data["tables_empty"].append("cluster_step_trace_time.csv")
    else:
        data["tables_empty"].append("cluster_step_trace_time.csv")

    # --- 2. communication_group.json (修复: 提取 base_info + fallback) ---
    json_path = os.path.join(text_dir, "communication_group.json")
    if os.path.exists(json_path):
        data["tables_found"].append("communication_group.json")
        with open(json_path, "r", encoding="utf-8") as f:
            comm_group = json.load(f)
        data["comm_group"] = comm_group
        # 从 communication_group.json 提取基础信息
        base_info = {}
        all_ranks = set()
        collective_groups = comm_group.get("collective", [])
        p2p_groups = comm_group.get("p2p", [])
        for group in collective_groups:
            if isinstance(group, list):
                all_ranks.update(group)
        for group in p2p_groups:
            if isinstance(group, list):
                all_ranks.update(group)
        parallel_info = comm_group.get("comm_group_parallel_info", [])
        if parallel_info:
            base_info["collective_group_count"] = str(len(parallel_info))
        # 修复: 如果 communication_group.json 中 rank 为空，使用 CSV 中的 rank 列表
        if all_ranks:
            base_info["ranks"] = json.dumps(sorted(all_ranks))
            base_info["rank_count"] = str(len(all_ranks))
        elif "_csv_ranks" in data:
            base_info["ranks"] = json.dumps(data["_csv_ranks"])
            base_info["rank_count"] = str(len(data["_csv_ranks"]))
            base_info["_rank_source"] = "csv_fallback"
        else:
            base_info["ranks"] = "[]"
            base_info["rank_count"] = "0"
        data["base_info"] = base_info
        # 清理临时数据
        data.pop("_csv_ranks", None)
    else:
        data["tables_empty"].append("communication_group.json")
        # 修复: 如果没有 communication_group.json，从 CSV rank 行提取 rank 列表
        if "_csv_ranks" in data:
            data["base_info"] = {
                "ranks": json.dumps(data["_csv_ranks"]),
                "rank_count": str(len(data["_csv_ranks"])),
                "_rank_source": "csv_fallback"
            }
            data.pop("_csv_ranks", None)
        elif "step_statistic" in data:
            ranks = set()
            for r in data["step_statistic"]:
                ranks.add(str(r.get("Index", "?")))
            data["base_info"] = {"ranks": json.dumps(sorted(ranks)), "rank_count": str(len(ranks))}

    # --- 3. cluster_communication.json (新增: 通信时间分析) ---
    comm_json_path = os.path.join(text_dir, "cluster_communication.json")
    if os.path.exists(comm_json_path):
        data["tables_found"].append("cluster_communication.json")
        with open(comm_json_path, "r", encoding="utf-8") as f:
            try:
                comm_data = json.load(f)
            except json.JSONDecodeError:
                comm_data = {}
        # 解析通信算子耗时统计
        # 结构: {rank_tuple: {step_id: {op_name@group: {rank_id, communication_time_info: {...}, communication_bandwidth_info: {...}}}}}
        op_stats = {}  # {op_name: {elapsed: [], transit: [], wait: [], sync: []}}
        for rank_tuple, step_dict in comm_data.items():
            if not isinstance(step_dict, dict):
                continue
            for step_id, op_dict in step_dict.items():
                if not isinstance(op_dict, dict):
                    continue
                for op_name, rank_info in op_dict.items():
                    if not isinstance(rank_info, dict):
                        continue
                    # 跳过 Total 汇总行
                    clean_name = op_name.split("@")[0]
                    if clean_name.lower().startswith("total"):
                        continue
                    time_info = rank_info.get("communication_time_info", {})
                    if not isinstance(time_info, dict):
                        continue
                    if clean_name not in op_stats:
                        op_stats[clean_name] = {"elapsed": [], "transit": [], "wait": [], "sync": []}
                    # 时间单位: ms (TEXT 模式 JSON 中已经是 ms)
                    op_stats[clean_name]["elapsed"].append(float(time_info.get("transit_time_ms", 0) or 0) +
                                                           float(time_info.get("wait_time_ms", 0) or 0) +
                                                           float(time_info.get("synchronization_time_ms", 0) or 0))
                    op_stats[clean_name]["transit"].append(float(time_info.get("transit_time_ms", 0) or 0))
                    op_stats[clean_name]["wait"].append(float(time_info.get("wait_time_ms", 0) or 0))
                    op_stats[clean_name]["sync"].append(float(time_info.get("synchronization_time_ms", 0) or 0))
        # 求均值并排序
        comm_time_ops = []
        for op_name, stats in op_stats.items():
            n = len(stats["elapsed"]) if stats["elapsed"] else 1
            comm_time_ops.append({
                "op_name": op_name,
                "avg_elapsed": round(sum(stats["elapsed"]) / n, 4),
                "avg_transit": round(sum(stats["transit"]) / n, 4),
                "avg_wait": round(sum(stats["wait"]) / n, 4),
                "avg_sync": round(sum(stats["sync"]) / n, 4),
            })
        comm_time_ops.sort(key=lambda x: x["avg_elapsed"], reverse=True)
        if comm_time_ops:
            data["comm_time_ops"] = comm_time_ops[:20]
        else:
            data["tables_empty"].append("cluster_communication.json (no valid ops)")
    else:
        data["tables_empty"].append("cluster_communication.json")

    # --- 4. cluster_communication_matrix.json (新增: 通信矩阵分析) ---
    matrix_json_path = os.path.join(text_dir, "cluster_communication_matrix.json")
    if os.path.exists(matrix_json_path):
        data["tables_found"].append("cluster_communication_matrix.json")
        with open(matrix_json_path, "r", encoding="utf-8") as f:
            try:
                matrix_data = json.load(f)
            except json.JSONDecodeError:
                matrix_data = {}
        # 解析通信矩阵 (4 层嵌套 JSON)
        # 结构: {rank_group: {step_name: {op_name@group_id: {src-dst: {Transport Type, Transit Time(ms), Transit Size(MB), Op Name, Bandwidth(GB/s)}}}}}
        matrix_records = []
        bw_by_type = {}  # {transport_type: [bandwidth, ...]}
        for rank_group, step_dict in matrix_data.items():
            if not isinstance(step_dict, dict):
                continue
            for step_name, op_dict in step_dict.items():
                if not isinstance(op_dict, dict):
                    continue
                for op_name, pair_data in op_dict.items():
                    if not isinstance(pair_data, dict):
                        continue
                    clean_op = op_name.split("@")[0]
                    if clean_op.lower().startswith("total"):
                        continue
                    for pair_key, metrics in pair_data.items():
                        if not isinstance(metrics, dict):
                            continue
                        try:
                            src, dst = pair_key.split("-")
                            src_rank = int(src)
                            dst_rank = int(dst)
                        except (ValueError, AttributeError):
                            continue
                        transport_type = metrics.get("Transport Type", "UNKNOWN")
                        transit_time = float(metrics.get("Transit Time(ms)", 0) or 0)
                        transit_size = float(metrics.get("Transit Size(MB)", 0) or 0)
                        bandwidth = float(metrics.get("Bandwidth(GB/s)", 0) or 0)
                        matrix_records.append({
                            "src_rank": src_rank, "dst_rank": dst_rank,
                            "transport_type": transport_type,
                            "transit_time_ms": transit_time,
                            "transit_size_mb": transit_size,
                            "bandwidth_gbs": bandwidth,
                            "op_name": clean_op, "step": step_name,
                        })
                        # 按传输类型聚合带宽
                        if transport_type not in bw_by_type:
                            bw_by_type[transport_type] = {"bw": [], "size": [], "time": []}
                        bw_by_type[transport_type]["bw"].append(bandwidth)
                        bw_by_type[transport_type]["size"].append(transit_size)
                        bw_by_type[transport_type]["time"].append(transit_time)
        # 生成带宽汇总
        if bw_by_type:
            comm_bandwidth = []
            for t_type, stats in bw_by_type.items():
                n = len(stats["bw"]) if stats["bw"] else 1
                comm_bandwidth.append({
                    "transport_type": t_type,
                    "avg_bw": round(sum(stats["bw"]) / n, 4),
                    "avg_size": round(sum(stats["size"]) / n, 4),
                    "avg_time": round(sum(stats["time"]) / n, 4),
                })
            data["comm_bandwidth"] = comm_bandwidth
        # 生成通信矩阵汇总 (Top 50)
        if matrix_records:
            matrix_records.sort(key=lambda x: x["bandwidth_gbs"], reverse=True)
            data["comm_matrix"] = matrix_records[:50]
            data["comm_matrix_count"] = len(matrix_records)
    else:
        data["tables_empty"].append("cluster_communication_matrix.json")

    return data


# ==================== 主入口 ====================

def extract_all(data_dir):
    fmt = detect_format(data_dir)
    # 优先使用 DB
    if fmt["format"] in ("db_old", "mixed") and fmt["db_path"]:
        # 检查是旧格式还是新格式
        db_name = os.path.basename(fmt["db_path"])
        if db_name == "cluster_analysis.db":
            return extract_db_new(fmt["db_path"])
        else:
            return extract_db_old(fmt["db_path"])
    if fmt["format"] == "db_new":
        return extract_db_new(fmt["db_path"])
    if fmt["format"] == "text":
        return extract_text(fmt["text_dir"])
    if fmt["format"] == "mixed":
        if fmt["db_path"]:
            db_name = os.path.basename(fmt["db_path"])
            if db_name == "cluster_analysis.db":
                return extract_db_new(fmt["db_path"])
            else:
                return extract_db_old(fmt["db_path"])
    return {"format": "unknown", "error": "无法识别数据格式", "data_dir": data_dir}


def main():
    parser = argparse.ArgumentParser(description="集群数据提取器")
    parser.add_argument("--data-dir", required=True, help="集群数据目录路径")
    parser.add_argument("--output", default=None, help="输出 JSON 文件路径")
    args = parser.parse_args()

    data = extract_all(args.data_dir)
    data["data_dir"] = args.data_dir
    data["extract_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"数据已提取到: {args.output}")
        # 打印摘要
        ss = data.get("step_summary", {})
        rs = data.get("rank_summary", {})
        bi = data.get("base_info", {})
        print(f"  格式: {data.get('format')}")
        print(f"  Rank 数: {len(rs)}")
        print(f"  Step 数: {len(ss)}")
        print(f"  通信算子: {len(data.get('comm_time_ops', []))} 个")
        print(f"  带宽类型: {len(data.get('comm_bandwidth', []))} 种")
        print(f"  通信矩阵: {data.get('comm_matrix_count', len(data.get('comm_matrix', [])))} 条")
        print(f"  空表: {data.get('tables_empty', [])}")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
