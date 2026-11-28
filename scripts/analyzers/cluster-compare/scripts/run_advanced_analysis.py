#!/usr/bin/env python3
"""
run_advanced_analysis.py
msprof-analyze 进阶分析编排脚本。

职责:
  1. 检测集群数据格式（DB/TEXT）与 msprof-analyze 工具可用性;
  2. 判断哪些进阶 feature 可运行, 必要时自动补跑前置 cluster_time_summary;
  3. 执行进阶 feature, 已有输出时直接复用（--force 可强制重跑）;
  4. 解析输出（CSV / SQLite 表）为结构化数据, 输出 advanced_analysis.json,
     供 generate_cluster_report.py --advanced 注入 HTML 报告「进阶分析」章节。

进阶分析能力对照（源自 msprof-analyze advanced_features 文档）:
  - cluster_time_compare_summary : 双集群 rank/step 级时间拆解对比, 需两侧 DB 均含
    ClusterTimeSummary 表（缺失时本脚本自动补跑）; 纯 TEXT 模式数据不支持。
  - free_analysis                : 单集群空闲原因分析, 支持 --export_type text 输出 CSV
    （cluster_analysis_output/FreeAnalysis/free_analysis.csv）。
  - communication_bottleneck     : 单集群通信瓶颈定位（慢/快 rank + 原因）, 支持
    --export_type text（cluster_analysis_output/CommunicationBottleneckAnalysis/
    communication_bottleneck.csv）。
  其余 feature（freq_analysis / ep_load_balance / slow_rank / slow_link / hccl_sum /
  communication_matrix_sum / mstx_sum / cann_api_sum / export_summary 等）可按相同
  模式扩展: 补一个 run_xxx + parse_xxx 即可。

用法:
  python run_advanced_analysis.py --cluster-a <dirA> [--cluster-b <dirB>] --output <advanced.json>
  python run_advanced_analysis.py --cluster-a <dirA> --cluster-b <dirB> --output adv.json --dry-run

注意:
  单集群 feature（free_analysis / communication_bottleneck）会对 A、B 两个集群分别执行,
  msprof 输出目录按集群隔离（<work-dir>/cluster_A、<work-dir>/cluster_B）, 结果记录带
  cluster 标注；缓存按角色和来源目录隔离，只复用已完成的结果。
"""
import argparse
from contextlib import closing, contextmanager
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime

FEAT_TIME_CMP = "cluster_time_compare_summary"
FEAT_FREE = "free_analysis"
FEAT_COMM_BN = "communication_bottleneck"

TIME_SUMMARY_TABLE = "ClusterTimeSummary"
COMPARE_TABLE = "ClusterTimeCompareSummary"

CSV_FREE = "free_analysis.csv"
CSV_COMM_BN = "communication_bottleneck.csv"

DEFAULT_TIMEOUT = 7200  # 秒, 集群级分析可能较慢


def log(msg):
    print(msg, flush=True)


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _pick(row, *names):
    """大小写不敏感、忽略空格/下划线差异地从 DictReader 行中取列值。"""
    norm = {}
    for k, v in row.items():
        if k is None:
            continue
        norm[k.strip().lower().replace(" ", "").replace("_", "")] = (v or "").strip()
    for n in names:
        v = norm.get(n.strip().lower().replace(" ", "").replace("_", ""))
        if v:
            return v
    return ""


# ==================== 环境与数据探测 ====================

def find_msprof(bin_name):
    return shutil.which(bin_name)


def get_tool_version(msprof):
    _, out, err = run_tool(msprof, ["--version"], timeout=60)
    lines = (out.strip() or err.strip()).splitlines()
    return next((line[:120] for line in lines if line.lower().startswith("version ")),
                lines[0][:120] if out and lines else "")


def detect_db(data_dir):
    for cand in (
        os.path.join(data_dir, "cluster_analysis_output", "cluster_analysis.db"),
        os.path.join(data_dir, "cluster_analysis.db"),
        os.path.join(data_dir, "cluster.db"),
    ):
        if os.path.isfile(cand):
            return cand
    return None


def detect_text_dir(data_dir):
    for sub in (os.path.join(data_dir, "cluster_analysis_output"), data_dir):
        if sub and os.path.isfile(os.path.join(sub, "cluster_step_trace_time.csv")):
            return sub
    return None


def table_exists(db_path, table):
    try:
        with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)) as con:
            row = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            return row is not None
    except (OSError, sqlite3.Error):
        return False


def detect_cluster(data_dir):
    info = {
        "data_dir": data_dir,
        "db_path": None,
        "db_kind": None,
        "text_dir": None,
        "format": "unknown",
        "has_time_summary_table": False,
    }
    if not data_dir or not os.path.isdir(data_dir):
        info["format"] = "not_found"
        return info
    db = detect_db(data_dir)
    if db:
        info["db_path"] = db
        info["db_kind"] = "db_new" if os.path.basename(db) == "cluster_analysis.db" else "db_old"
        info["format"] = "db"
        info["has_time_summary_table"] = table_exists(db, TIME_SUMMARY_TABLE)
    txt = detect_text_dir(data_dir)
    if txt:
        info["text_dir"] = txt
        info["format"] = info["format"] if info["db_path"] else "text"
    return info


def junction_workspace():
    for base in (tempfile.gettempdir(), os.environ.get("PUBLIC"), os.getcwd()):
        if not base or not base.isascii():
            continue
        try:
            return Path(tempfile.mkdtemp(prefix="msprof-", dir=base))
        except OSError:
            continue
    return None


@contextmanager
def tool_path_args(args, env):
    adjusted = list(args)
    non_ascii = {i + 1: os.path.abspath(args[i + 1]) for i, arg in enumerate(args[:-1])
                 if arg in ("-d", "--bp", "-o") and not os.path.abspath(args[i + 1]).isascii()}
    if os.name != "nt" or not non_ascii:
        yield adjusted
        return
    root = junction_workspace()
    if root is None:
        log("  [warn] 无法创建全 ASCII 的临时目录，将使用原始路径调用 msprof-analyze。")
        yield adjusted
        return

    links = {}
    created = []
    try:
        for index, target in non_ascii.items():
            if target not in links:
                link = root / f"path-{index}"
                try:
                    subprocess.run(
                        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                         "$ErrorActionPreference = 'Stop'; New-Item -ItemType Junction "
                         "-Path $env:CLUSTER_COMPARE_LINK -Target $env:CLUSTER_COMPARE_TARGET | Out-Null"],
                        env={**env, "CLUSTER_COMPARE_LINK": str(link), "CLUSTER_COMPARE_TARGET": target},
                        check=True, capture_output=True, timeout=30,
                    )
                    links[target] = link
                    created.append(link)
                    log(f"  [路径] 临时目录联接：{link} → {target}")
                except (OSError, subprocess.SubprocessError) as exc:
                    if os.path.lexists(link):
                        created.append(link)
                    log(f"  [warn] 无法为 {target} 创建 ASCII 目录联接（{type(exc).__name__}），将使用原始路径。")
                    continue
            adjusted[index] = str(links[target])
        yield adjusted
    finally:
        for path in [*created, root]:
            try:
                os.rmdir(path)  # 只删除联接本身，绝不递归删除所指向的数据目录。
            except OSError as exc:
                log(f"  [warn] 无法清理临时目录或联接 {path}：{exc}")


def run_tool(msprof, args_list, timeout=DEFAULT_TIMEOUT):
    log(f"  [exec] {' '.join([msprof, *args_list])}")
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        with tool_path_args(args_list, env) as args:
            p = subprocess.run([msprof, *args], capture_output=True, encoding="utf-8",
                               errors="replace", env=env, timeout=timeout)
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except FileNotFoundError:
        return 127, "", f"命令不存在: {msprof}"
    except subprocess.TimeoutExpired:
        return 124, "", "执行超时"
    except Exception as e:
        return 1, "", str(e)


def find_output_file(roots, filename, max_depth=4):
    """在候选根目录下限深递归搜索文件, 返回第一个命中路径。"""
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            if dirpath[len(root):].count(os.sep) >= max_depth:
                dirnames[:] = []
                continue
            if filename in filenames:
                return os.path.join(dirpath, filename)
    return None


def find_db_with_table(roots, table, max_depth=4):
    """搜索包含指定表的 cluster_analysis.db。"""
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            if dirpath[len(root):].count(os.sep) >= max_depth:
                dirnames[:] = []
                continue
            if "cluster_analysis.db" in filenames:
                p = os.path.join(dirpath, "cluster_analysis.db")
                if table_exists(p, table):
                    return p
    return None


def result_scope(work_dir, feature, top_num, *sources):
    """缓存按来源目录、集群角色（上级目录）及工具参数隔离。"""
    paths = [os.path.normcase(os.path.realpath(source)) for source in sources]
    fingerprint = hashlib.sha256(json.dumps([paths, top_num]).encode("utf-8")).hexdigest()[:20]
    return Path(work_dir).absolute() / f"{feature}-{fingerprint}"


def cached_result(scope):
    markers = sorted(scope.glob("run-*/.result"), key=lambda path: path.stat().st_mtime, reverse=True)
    for marker in markers:
        result = marker.parent / marker.read_text(encoding="utf-8")
        if result.is_file():
            return str(result)
    return None


def record_result(run_dir, result):
    marker = run_dir / ".result.tmp"
    marker.write_text(str(Path(result).relative_to(run_dir)), encoding="utf-8")
    marker.replace(run_dir / ".result")


def new_run_dir(scope):
    scope.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="run-", dir=scope))


# ==================== 输出解析 ====================

def parse_free_csv(csv_path, top_n=10):
    """free_analysis text 输出解析: 列含 Rank ID/Start Time(us)/End Time(us)/
    Duration(us)/Pytorch Idle Time(us)/Cann Idle Time(us)/Reason。按 Reason 聚合。"""
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row:
                rows.append(row)
    agg = {}
    total_us = 0.0
    for r in rows:
        reason = _pick(r, "Reason") or "未标注原因"
        dur_us = _to_float(_pick(r, "Duration(us)", "Duration"))
        rank = _pick(r, "Rank ID", "Rank")
        total_us += dur_us
        a = agg.setdefault(reason, {"count": 0, "duration_us": 0.0, "ranks": set()})
        a["count"] += 1
        a["duration_us"] += dur_us
        if rank:
            a["ranks"].add(rank)
    reasons = []
    for reason, a in agg.items():
        reasons.append({
            "reason": reason[:200],
            "count": a["count"],
            "total_ms": round(a["duration_us"] / 1000.0, 2),
            "pct": round(a["duration_us"] / total_us * 100, 1) if total_us > 0 else 0,
            "rank_count": len(a["ranks"]),
            "sample_ranks": sorted(a["ranks"])[:8],
        })
    reasons.sort(key=lambda x: x["total_ms"], reverse=True)
    return {
        "rows_total": len(rows),
        "total_ms": round(total_us / 1000.0, 2),
        "reasons": reasons[:top_n],
    }


def parse_comm_bn_csv(csv_path, top_n=20):
    """communication_bottleneck text 输出解析: 列含 Communication Op/
    Slow Rank ID/Fast Rank ID/Reason 等（列名以实际文件为准）。"""
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = [
            {k.strip(): (v or "").strip() for k, v in r.items() if k}
            for r in csv.DictReader(f) if r
        ]
    items = []
    for r in rows:
        op = _pick(r, "Communication Op", "CommunicationOp", "Op Name", "Op")
        slow = _pick(r, "Slow Rank ID", "SlowRankID", "Slow Rank")
        fast = _pick(r, "Fast Rank ID", "FastRankID", "Fast Rank")
        reason = _pick(r, "Reason")
        dur_us = _to_float(_pick(r, "Duration(us)", "Elapsed(us)", "Time(us)", "Transit Time(us)"))
        items.append({
            "op": op[:120],
            "slow_rank": slow,
            "fast_rank": fast,
            "reason": reason[:300],
            "duration_ms": round(dur_us / 1000.0, 2),
        })
    items.sort(key=lambda x: x["duration_ms"], reverse=True)
    return {
        "rows_total": len(rows),
        "columns": list(rows[0].keys()) if rows else [],
        "items": items[:top_n],
    }


def parse_compare_summary(db_path, top_n=10):
    """ClusterTimeCompareSummary 表解析: 字段 rank/step/{metrics}/{metrics}Base/
    {metrics}Diff, 时间单位 μs → 统一转 ms。"""
    con = sqlite3.connect(db_path)
    try:
        cur = con.execute(f"SELECT * FROM {COMPARE_TABLE}")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()
    if not rows:
        return {"rows_total": 0}
    diff_cols = [c for c in cols if c.endswith("Diff")]
    metrics = [c[:-4] for c in diff_cols]
    key_cols = [c for c in cols if not c.endswith("Base") and not c.endswith("Diff")]

    def _nums(r, col):
        v = r.get(col)
        return v if isinstance(v, (int, float)) else None

    overall = {}
    for m in metrics:
        b = [v for r in rows if (v := _nums(r, m + "Base")) is not None]
        c = [v for r in rows if (v := _nums(r, m)) is not None]
        d = [v for r in rows if (v := _nums(r, m + "Diff")) is not None]
        overall[m] = {
            "base_avg_ms": round(sum(b) / len(b) / 1000.0, 2) if b else None,
            "cur_avg_ms": round(sum(c) / len(c) / 1000.0, 2) if c else None,
            "diff_avg_ms": round(sum(d) / len(d) / 1000.0, 2) if d else None,
        }

    rank_col = next(
        (c for c in key_cols if c.strip().lower() in ("rank", "rank_id", "rankid", "index")),
        None,
    )
    top_ranks = []
    if rank_col and metrics:
        stage_metric = next((m for m in metrics if "stage" in m.lower()), metrics[0])
        by_rank = {}
        for r in rows:
            by_rank.setdefault(r.get(rank_col), []).append(r)
        for rk, rs in by_rank.items():
            item = {"rank": rk, "step_count": len(rs)}
            for m in metrics:
                vals = [v for x in rs if (v := _nums(x, m + "Diff")) is not None]
                item[m + "_diff_ms"] = round(sum(vals) / len(vals) / 1000.0, 2) if vals else None
            top_ranks.append(item)
        top_ranks.sort(key=lambda x: (x.get(stage_metric + "_diff_ms") or 0), reverse=True)
        top_ranks = top_ranks[:top_n]
    return {
        "rows_total": len(rows),
        "key_cols": key_cols,
        "metrics": metrics,
        "overall": overall,
        "rank_col": rank_col,
        "top_ranks": top_ranks,
    }


# ==================== feature 编排 ====================

def feature_availability(name, tool_available, ca, cb):
    """返回 (available, reason)。"""
    if not tool_available:
        return False, "msprof-analyze 工具不可用（未安装或不在 PATH）"
    if name == FEAT_TIME_CMP:
        if not (ca and cb):
            return False, "cluster_time_compare_summary 需要提供两个集群目录（缺少 --cluster-b）"
        for tag, c in (("集群A", ca), ("集群B", cb)):
            if not c["db_path"]:
                return False, f"{tag} 无 DB 格式数据（当前格式: {c['format']}），该 feature 仅支持 DB 输入"
            recipe_db = Path(c["data_dir"]) / "cluster_analysis_output" / "cluster_analysis.db"
            if recipe_db.resolve() != Path(c["db_path"]).resolve():
                return False, f"{tag} 的时间拆解对比需要采集目录下的 cluster_analysis_output/cluster_analysis.db"
        return True, ""
    target = cb or ca
    if not target or target["format"] in ("unknown", "not_found"):
        return False, "目标集群目录下未识别到 cluster_analysis_output / profiling 数据"
    return True, ""


def ensure_time_summary(msprof, c, tag):
    """确保集群 DB 含 ClusterTimeSummary 表; 缺失时自动补跑。返回 (ok, msg)。"""
    if c["has_time_summary_table"]:
        return True, ""
    log(f"  [prep] {tag} 缺少 {TIME_SUMMARY_TABLE} 表，将向原始 DB 追加该表：{c['db_path']}")
    rc, out, err = run_tool(msprof, ["-m", "cluster_time_summary", "-d", c["data_dir"], "--export_type", "db"])
    c["has_time_summary_table"] = table_exists(c["db_path"], TIME_SUMMARY_TABLE)
    if c["has_time_summary_table"]:
        c["time_summary_added"] = True
        log(f"  [数据写入] 已向 {tag} 的 DB 追加 {TIME_SUMMARY_TABLE} 表：{c['db_path']}")
    if rc != 0:
        tail = (err or out or "").strip().splitlines()[-5:]
        return False, f"{tag} 补跑 cluster_time_summary 失败(rc={rc}): " + " | ".join(tail)[-400:]
    if not c["has_time_summary_table"]:
        tail = (err or out or "").strip().splitlines()[-5:]
        if tail:
            log(f"  [warn] {tag} 的工具输出：" + " | ".join(tail))
        return False, f"{tag} 补跑结束，但原始 DB 中未找到 {TIME_SUMMARY_TABLE} 表"
    return True, ""


def time_summary_steps(cluster):
    try:
        db_uri = Path(cluster["db_path"]).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(db_uri, uri=True)) as con:
            return {str(step) for (step,) in con.execute(f"SELECT DISTINCT step FROM {TIME_SUMMARY_TABLE}")
                    if step is not None}
    except (OSError, sqlite3.Error):
        return set()


def run_feature_time_cmp(msprof, ca, cb, work_dir, top_num, force, dry_run=False):
    feat = {
        "name": FEAT_TIME_CMP,
        "label": "集群时间拆解对比",
        "desc": "双集群 rank/step 级时间指标对比（基准/当前/差值），需两侧 DB 含 ClusterTimeSummary 表",
    }
    ok, reason = feature_availability(FEAT_TIME_CMP, bool(msprof), ca, cb)
    feat["available"], feat["reason"] = ok, reason
    if dry_run:
        feat["status"] = "pending" if ok else "not_available"
        return feat
    if not ok:
        feat["status"] = "skipped" if not (ca and cb) else "not_available"
        return feat

    ok1, msg1 = ensure_time_summary(msprof, ca, "集群A(基准)")
    ok2, msg2 = ensure_time_summary(msprof, cb, "集群B(对比)")
    if not (ok1 and ok2):
        feat["status"] = "failed"
        feat["reason"] = msg1 or msg2
        return feat

    scope = result_scope(work_dir, FEAT_TIME_CMP, top_num, ca["data_dir"], cb["data_dir"])
    existing = None if force else cached_result(scope)
    if existing and table_exists(existing, COMPARE_TABLE):
        feat["status"] = "cached"
        feat["data"] = parse_compare_summary(existing, top_num)
        feat["data"]["source_db"] = existing
        return feat

    run_dir = new_run_dir(scope)
    cmd = ["-m", FEAT_TIME_CMP, "-d", cb["data_dir"], "--bp", ca["data_dir"],
           "--export_type", "db", "-o", str(run_dir)]
    feat["command"] = " ".join(cmd)
    rc, out, err = run_tool(msprof, cmd)
    db_hit = find_db_with_table([str(run_dir)], COMPARE_TABLE) if rc == 0 else None
    diagnostics = f"{out}\n{err}".lower()
    if "no valid compare data" in diagnostics or (not db_hit and "unmatched rank-step" in diagnostics):
        steps_a, steps_b = time_summary_steps(ca), time_summary_steps(cb)
        feat["status"] = "skipped"
        feat["reason"] = ("两侧采集的 Step 区间不重叠，无法进行逐步配对对比（属正常不可比情形）"
                          if steps_a and steps_b and steps_a.isdisjoint(steps_b)
                          else "两侧没有可用于逐步对比的 Rank 和 Step 配对数据（属正常不可比情形）")
        return feat
    if rc == 0 and db_hit:
        feat["status"] = "success"
        feat["data"] = parse_compare_summary(db_hit, top_num)
        feat["data"]["source_db"] = db_hit
        record_result(run_dir, db_hit)
    else:
        tail = (err or out or "").strip().splitlines()[-5:]
        feat["status"] = "failed"
        feat["reason"] = (f"执行失败(rc={rc}): " + " | ".join(tail))[-500:] if tail else "执行完成但未找到结果 DB"
    return feat


def run_feature_on_target(msprof, target, work_dir, top_num, force,
                          feat_name, feat_label, feat_desc, csv_name,
                          cluster_tag=None, dry_run=False):
    """单集群 feature（free_analysis / communication_bottleneck）通用编排。

    cluster_tag: 集群标识（"A"/"B"）。提供时 msprof 输出目录改为 <work_dir>/cluster_<tag>,
    缓存仅使用来源一致且已成功完成的输出。
    """
    feat = {"name": feat_name, "label": feat_label, "desc": feat_desc}
    if cluster_tag:
        feat["cluster"] = cluster_tag
    ok, reason = feature_availability(feat_name, bool(msprof), target, None)
    feat["available"], feat["reason"] = ok, reason
    if dry_run:
        feat["status"] = "pending" if ok else "not_available"
        return feat
    if not ok:
        feat["status"] = "not_available"
        return feat

    out_dir = os.path.join(work_dir, f"cluster_{cluster_tag}") if cluster_tag else work_dir
    scope = result_scope(out_dir, feat_name, top_num, target["data_dir"])
    parser = parse_free_csv if feat_name == FEAT_FREE else parse_comm_bn_csv
    existing = None if force else cached_result(scope)
    if cluster_tag and not force and not existing:
        embedded_scope = result_scope(Path(target["data_dir"]) / "advanced_work", feat_name,
                                      top_num, target["data_dir"])
        existing = cached_result(embedded_scope)
    if existing:
        feat["status"] = "cached"
        feat["data"] = parser(existing, top_num)
        feat["data"]["source_csv"] = existing
        return feat

    run_dir = new_run_dir(scope)
    cmd = ["-m", feat_name, "-d", target["data_dir"],
           "--export_type", "text", "--top_num", str(top_num), "-o", str(run_dir)]
    feat["command"] = " ".join(cmd)
    rc, out, err = run_tool(msprof, cmd)
    csv_hit = find_output_file([str(run_dir)], csv_name) if rc == 0 else None
    if rc == 0 and csv_hit:
        feat["status"] = "success"
        feat["data"] = parser(csv_hit, top_num)
        feat["data"]["source_csv"] = csv_hit
        record_result(run_dir, csv_hit)
    else:
        tail = (err or out or "").strip().splitlines()[-5:]
        feat["status"] = "failed"
        feat["reason"] = (f"执行失败(rc={rc}): " + " | ".join(tail))[-500:] if tail else "执行完成但未找到输出 CSV"
    return feat


# ==================== 主流程 ====================

def main():
    ap = argparse.ArgumentParser(description="msprof-analyze 进阶分析编排（供集群比对报告注入）")
    ap.add_argument("--cluster-a", required=True, help="集群A目录（基准; 单集群模式下同时作为分析目标）")
    ap.add_argument("--cluster-b", default=None, help="集群B目录（对比; 提供后单集群 feature 优先分析 B）")
    ap.add_argument("--output", required=True, help="输出 advanced_analysis.json 路径")
    ap.add_argument("--msprof", default="msprof-analyze", help="msprof-analyze 可执行文件名/路径")
    ap.add_argument("--top-num", type=int, default=10, help="各 feature 结果 Top N")
    ap.add_argument("--work-dir", default=None, help="msprof 输出目录（默认: <output 同目录>/advanced_work）")
    ap.add_argument("--dry-run", action="store_true", help="仅检测可用性，不执行任何分析")
    ap.add_argument("--force", action="store_true", help="忽略已有输出，强制重新执行")
    args = ap.parse_args()

    out_path = os.path.abspath(args.output)
    out_dir = os.path.dirname(out_path) or "."
    os.makedirs(out_dir, exist_ok=True)
    work_dir = os.path.abspath(args.work_dir or os.path.join(out_dir, "advanced_work"))
    if not args.dry_run:
        os.makedirs(work_dir, exist_ok=True)

    msprof = find_msprof(args.msprof)
    tool = {
        "bin": args.msprof,
        "available": msprof is not None,
        "path": msprof or "",
        "version": "",
    }
    if tool["available"]:
        tool["version"] = get_tool_version(msprof)

    ca = detect_cluster(os.path.abspath(args.cluster_a))
    cb = detect_cluster(os.path.abspath(args.cluster_b)) if args.cluster_b else None
    log(f"[detect] 集群A: format={ca['format']}, db={ca['db_path']}, "
        f"time_summary={ca['has_time_summary_table']}")
    if cb:
        log(f"[detect] 集群B: format={cb['format']}, db={cb['db_path']}, "
            f"time_summary={cb['has_time_summary_table']}")

    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dry_run": bool(args.dry_run),
        "tool": tool,
        "clusters": {"A": ca, "B": cb},
        "features": [],
    }

    if not tool["available"]:
        log("[warn] msprof-analyze 不可用, 所有 feature 标记为 not_available")

    # 1) 双集群时间拆解对比（DB only）
    result["features"].append(run_feature_time_cmp(msprof, ca, cb, work_dir, args.top_num, args.force, args.dry_run))

    # 2/3) 单集群 feature: free_analysis / communication_bottleneck（对 A、B 分别执行）
    for tag, cluster in (("A", ca), ("B", cb)):
        if cluster is None:
            continue
        tag_label = "基准" if tag == "A" else "对比"
        for feat_name, feat_label, feat_desc, csv_name in (
            (FEAT_FREE, "空闲时间原因分析",
             "定位单集群空闲（Free）时间的成因分类与耗时排名, 辅助 Host 下发瓶颈定位",
             CSV_FREE),
            (FEAT_COMM_BN, "通信瓶颈定位",
             "定位单集群慢卡/快卡与通信瓶颈原因, 辅助链路劣化排查",
             CSV_COMM_BN),
        ):
            feat = run_feature_on_target(
                msprof, cluster, work_dir, args.top_num, args.force,
                feat_name, feat_label, feat_desc, csv_name, cluster_tag=tag, dry_run=args.dry_run)
            result["features"].append(feat)
            log(f"[feat] 集群{tag}({tag_label}) {feat_name}: {feat['status']}"
                + (f"（{feat['reason']}）" if feat.get("reason") and feat["status"] != "success" else ""))

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log(f"[done] 进阶分析结果已写入: {out_path}")
    for f in result["features"]:
        log(f"  - {f['name']}: {f['status']}" + (f"（{f['reason']}）" if f.get("reason") and f["status"] != "success" else ""))


if __name__ == "__main__":
    main()
