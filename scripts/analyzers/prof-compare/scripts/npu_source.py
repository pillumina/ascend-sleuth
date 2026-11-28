"""Locate a single-rank Ascend export and decode native profiler tables."""
import csv
import sqlite3
from collections import defaultdict
from contextlib import closing, contextmanager
from decimal import Decimal
from pathlib import Path


DB_PREFIXES = ("ascend_pytorch_profiler", "ascend_mindspore_profiler", "msmonitor")


def is_main_db(path):
    return path.suffix == ".db" and path.name.startswith(DB_PREFIXES)


def npu_source(path):
    """Return the exact main DB or the directory containing the text export."""
    path = Path(path)
    if path.is_file():
        if path.suffix == ".db" and not is_main_db(path):
            raise ValueError(f"{path.name} 不是 profiler 主库，请选择 ascend_*_profiler*.db 或采集目录")
        if is_main_db(path) and not path.stat().st_size:
            raise ValueError(f"{path} 是空 DB；有文本导出时请指定其目录")
        return path if is_main_db(path) else None
    child = path / "ASCEND_PROFILER_OUTPUT"
    folder = child if child.is_dir() else path
    dbs = sorted(p for p in folder.glob("*.db") if is_main_db(p) and p.stat().st_size)
    if len(dbs) > 1:
        raise ValueError(f"{folder} 中有多个 profiler 主库，请指定一个 rank 的 DB 文件")
    if dbs:
        return dbs[0]
    if any((folder / f).is_file() for f in ("kernel_details.csv", "operator_details.csv", "trace_view.json")):
        return folder
    if any(is_main_db(p) for p in folder.glob("*.db")):
        raise ValueError(f"{folder} 中只有空的 profiler 主库")
    return None


@contextmanager
def open_db(path):
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            yield db
    except sqlite3.Error as exc:
        raise ValueError(f"读取 {path} 失败：{exc}") from exc


def columns(db, table):
    return {r["name"] for r in db.execute(f'PRAGMA table_info("{table}")')}


def string_ids(db):
    return dict(db.execute("SELECT id, value FROM STRING_IDS"))


def has_operator_memory(source):
    if is_main_db(source):
        with open_db(source) as db:
            return bool(columns(db, "OP_MEMORY") and db.execute("SELECT 1 FROM OP_MEMORY LIMIT 1").fetchone())
    path = source / "operator_memory.csv"
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as f:
            return next(csv.DictReader(f), None) is not None
    return False


def device_tasks(db):
    if columns(db, "TASK"):
        for table in ("COMPUTE_TASK_INFO", "COMMUNICATION_SCHEDULE_TASK_INFO"):
            if columns(db, table):
                for r in db.execute(f"""
                        SELECT c.*, t.startNs, t.endNs, t.deviceId, t.streamId, t.taskId, t.connectionId
                        FROM TASK t JOIN {table} c USING(globalTaskId)
                        ORDER BY t.rowid, c.rowid"""):
                    yield dict(r, schedule=table == "COMMUNICATION_SCHEDULE_TASK_INFO")
    if columns(db, "COMMUNICATION_OP"):
        for r in db.execute("SELECT * FROM COMMUNICATION_OP ORDER BY rowid"):
            yield dict(r, name=r["opName"], core="COMMUNICATION")


def db_kernels(path):
    with open_db(path) as db:
        strings = string_ids(db)
        steps = [(str(i), int(a), int(b)) for i, a, b in db.execute(
            "SELECT id,startNs,endNs FROM STEP_TIME WHERE startNs IS NOT NULL AND endNs IS NOT NULL"
        )] if columns(db, "STEP_TIME") else []
        for row in device_tasks(db):
            start, end = row["startNs"], row["endNs"]
            if start is None or end is None:
                continue
            start, end = int(start), int(end)
            r = {key: strings.get(row.get(col)) or "" for key, col in (
                ("Name", "name"), ("Type", "opType"), ("Accelerator Core", "taskType"),
                ("Input Shapes", "inputShapes"), ("Input Data Types", "inputDataTypes"),
                ("Input Formats", "inputFormats"), ("Output Shapes", "outputShapes"),
                ("Output Data Types", "outputDataTypes"), ("Output Formats", "outputFormats"))}
            if "core" in row:
                r["Accelerator Core"] = row["core"]
            wait = row.get("waitNs")
            r.update({"Duration(us)": str(Decimal(end-start).scaleb(-3)),
                      "Start Time(us)": str(Decimal(start).scaleb(-3)),
                      "Wait Time(us)": int(wait)/1000 if wait is not None else None,
                      "Block Num": row.get("blockNum"),
                      "Device_id": str(row.get("deviceId", "未知")), "Stream ID": str(row.get("streamId", "")),
                      "Task ID": str(row.get("taskId", "")), "connection": row.get("connectionId"),
                      "globalTaskId": row.get("globalTaskId"),
                      "comm_detail": bool(row.get("schedule") or row.get("core") == "COMMUNICATION"),
                      "Step Id": next((i for i, a, b in steps if a <= start < b), "未知")})
            yield r


def db_host_spans(path, *, include_data=False):
    """Yield framework ops once even when one API launches several device tasks."""
    with open_db(path) as db:
        fields = columns(db, "PYTORCH_API")
        if not fields:
            return
        strings = string_ids(db)
        links = defaultdict(set)
        if columns(db, "CONNECTION_IDS"):
            for group, conn in db.execute("SELECT id,connectionId FROM CONNECTION_IDS"):
                if conn is not None:
                    links[group].add(conn)
        sql = "SELECT rowid AS source_rowid,* FROM PYTORCH_API" if include_data else "SELECT * FROM PYTORCH_API"
        if "type" in fields:
            sql += (" WHERE type IN (SELECT id FROM ENUM_API_TYPE WHERE lower(name)='op')"
                    if columns(db, "ENUM_API_TYPE") else " WHERE type=50001")
        for r in db.execute(sql):
            name = strings.get(r["name"])
            if not name or r["startNs"] is None or r["endNs"] is None:
                continue
            span = (r["globalTid"], int(r["startNs"]), int(r["endNs"]), name,
                    strings.get(r["inputShapes"]) if "inputShapes" in fields else None,
                    links.get(r["connectionId"], ()) if "connectionId" in fields else ())
            if include_data:
                span += ({"id": r["source_rowid"],
                          "dtype": strings.get(r["inputDtypes"]) if "inputDtypes" in fields else None},)
            yield span
