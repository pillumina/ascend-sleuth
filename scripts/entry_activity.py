#!/usr/bin/env python3
"""entry_activity.py —— 条目使用记录的**格式与读写口径**（单一事实源，四个脚本共用）。

为什么要有这个模块：条目使用记录有三处会各写一份口径的地方——汇总脚本写源、生成器读源写生成物、
校验脚本判源与生成物——口径写在三个文件里就是三份实现，迟早对不上（本仓反复出现的形态）。
所以行 schema、归周规则、聚合规则、渲染规则都收在这里，其余三个脚本只做「取数」与「判据」。

记录分两层（`docs/mechanism/diagnosis-observability.md` 第 2 节的表）：

  源        `metrics/entry-activity.d/<周>.yaml`     一周一个文件，一次运行追加若干行，一行一条
  生成物    `metrics/entry-activity/<部署>.yaml`     由 build_entry_activity.py 重建，读端只读它

**一行一条**是硬约束，不是排版偏好：源文件配了 `merge=union`（`.gitattributes`），而 union 是
**行级**文本合并——嵌套结构里两人各插一段会拼出非法 YAML。所以每条记录压成一个 flow mapping
写在一行里；`purpose` 这类小映射也在行内展开，不做块状缩进。

行的三个键 `(run, kind, id)` 是唯一键：`run` 是一次**脚本运行**的时间戳（`YYYY-MM-DD-HHMM`；
搬运行是 `baseline-<日期>`），`kind` 取 `case` / `ref` / `tool` / `baseline`，`id` 是条目 id 或
工具名。同一次知识整理里汇总与结算各印自己的 `run`（各自是一次运行），因此同一个 case 在同一轮
整理里可能有两行、字段互补；聚合按 id 求和，不按行取最后一条。

计数键**全部写出（含 0）**：行是自包含的，缺键与 0 两种写法的读端要各判一次，而判错的那一次
是静默的（少写一个键会被读成"这轮没查过"而不是"这轮查了 0 次"）。唯一的例外是 `purpose`：
它是一个五键的小映射，只写非零项，否则每行都要带五个 0。
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from pathlib import Path

import yaml

from _stdio import write_text_lf
from exec_log_path import log_lock, main_checkout, resolve_rel

# ---------------------------------------------------------------- 目录与文件名

SOURCE_DIR_REL = Path("metrics") / "entry-activity.d"
GENERATED_DIR_REL = Path("metrics") / "entry-activity"
# 本机明细（一次诊断一行，含逐次工具调用）：gitignored，锚主检出，供面板与汇总脚本读。
LOCAL_DIR_REL = Path("metrics") / "entry-activity.local"

RUN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{4}$")
BASELINE_RUN_RE = re.compile(r"^baseline-\d{4}-\d{2}-\d{2}$")
WEEK_FILE_RE = re.compile(r"^(\d{4}-W\d{2})\.yaml$")

HEADER = (
    "# 条目使用记录的源：一周一个文件，一次运行追加若干行，一行一条自包含记录。\n"
    "#\n"
    "# 谁写：scripts/trace_entry_activity.py（汇总：被选中/被加载/被排除、先验三态与消费点、工具分布）\n"
    "#       scripts/settle_trace_feedback.py（结算：现场确认解决/自证解决/误诊）\n"
    "#       scripts/migrate_confidence_baseline.py（搬运：案例文件里原有的累计值，kind: baseline）\n"
    "# 谁读：scripts/build_entry_activity.py 聚合成 metrics/entry-activity/<部署>.yaml，读端只读生成物。\n"
    "#\n"
    "# 不要改已经写下的行：追加是唯一写动作。同一周多人各写各的行，配 merge=union（行级合并）两侧都留住。\n"
    "# 行的唯一键是 (run, kind, id)；同一行被重复保留只算一次，键相同而内容不同的两行判重复（校验脚本报红）。\n"
)

GENERATED_HEADER = (
    "# 条目使用记录的生成物（由 scripts/build_entry_activity.py 从 metrics/entry-activity.d/ 重建）。\n"
    "#\n"
    "# 读端只读这一份：面板与知识整理不解析源文件、也不自行求和。不要手改——改了会在 --check 上报过期。\n"
    "# 重建命令：python3 scripts/build_entry_activity.py\n"
    "#\n"
    "# `tools` 的 p50_ms/p90_ms 是**按调用次数加权的各运行分位均值**：跨运行的分位数无法从各运行的\n"
    "# 分位数精确合成，这里给的是量级读数，逐次与逐运行的精确值只在本机明细里（metrics/entry-activity.local/）。\n"
)

# ---------------------------------------------------------------- 行 schema

KINDS = ("case", "ref", "tool", "baseline")

#: 每种 kind 的计数键（**全部写出，缺省即 0 是禁止的**——见模块头注）。
COUNT_KEYS = {
    "case": ("selected", "loaded", "resolved", "misdiagnosed", "self_resolved", "excluded"),
    "ref": ("lookups", "hit", "miss", "skipped"),
    "tool": ("calls", "p50_ms", "p90_ms", "errors", "timeouts"),
    "baseline": ("resolved", "misdiagnosed", "self_resolved"),
}
#: 每种 kind 允许的附加键（非计数）。
EXTRA_KEYS = {
    "case": (),
    "ref": ("purpose",),
    "tool": (),
    "baseline": ("last_hit", "note"),
}
#: 两种 kind 才带的运行元信息。
SESSION_KINDS = ("case", "ref")
META_KEYS = ("run", "deployment", "checkout", "kb_rev", "sessions", "kind", "id")

PURPOSES = ("collect", "signature", "background", "fix", "procedure")
#: 生成物里每个 id 保留的最近运行条数。
RECENT_KEEP = 8


def row_keys(kind: str):
    """一种 kind 的完整键序（写行与校验共用，别在两处各排一遍）。"""
    keys = ["run", "deployment", "checkout", "kb_rev"]
    if kind in SESSION_KINDS:
        keys.append("sessions")
    keys += ["kind", "id"]
    keys += list(COUNT_KEYS[kind])
    keys += list(EXTRA_KEYS[kind])
    return keys


# ---------------------------------------------------------------- 时间与标识


def iso_week(d: date) -> str:
    """ISO 周标签（如 `2026-W42`）。本地时区，与知识整理的周节律一致。"""
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_of_run(run: str):
    """`run` → 它**按自身时间戳**落在哪个 ISO 周；搬运行与无法解析的值返回 None。

    注意：归周以**文件名**为准（校验脚本按文件名归周并报出不一致的 run），本函数只用来判
    「run 与它所在的周文件是否一致」。
    """
    if BASELINE_RUN_RE.match(run or ""):
        try:
            return iso_week(datetime.strptime(run[len("baseline-"):], "%Y-%m-%d").date())
        except ValueError:
            return None
    if not RUN_RE.match(run or ""):
        return None
    try:
        return iso_week(datetime.strptime(run, "%Y-%m-%d-%H%M").date())
    except ValueError:
        return None


def week_of_value(v):
    """把案例里搬过来的 `last_hit`（历史上是日期）归一成 ISO 周；已是周标签则原样返回。

    搬运行自带的 `last_hit` 只有这一处会带：`confidence.last_hit` 的历史取值实测是
    `2026-W35` 这类周标签，但更早的写法可能是日期，两种都收——收到日期就换算，换不出来返回 None
    （返回 None 而不是猜一个周，猜出来的周会进面板的「最后」列当事实显示）。
    """
    s = str(v or "").strip().strip("'\"")
    if not s:
        return None
    if re.match(r"^\d{4}-W\d{2}$", s):
        return s
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            return iso_week(datetime.strptime(s, "%Y-%m-%d").date())
        except ValueError:
            return None
    return None


def now_run() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M")


# ---------------------------------------------------------------- 运行元信息


def deployment(root: Path) -> str:
    """本次运行的部署标识：先取 `ASCEND_SLEUTH_DEPLOYMENT`，其次**主检出**目录名。

    不取当前 worktree 的目录名：本项目要求改动走 worktree，按 worktree 取名会把同一部署拆成
    多条排行（`docs/mechanism/diagnosis-observability.md` 3.3）。
    """
    env = (os.environ.get("ASCEND_SLEUTH_DEPLOYMENT") or "").strip()
    if env:
        return env
    main = main_checkout(Path(root))
    return Path(main or root).resolve().name


def _git(root: Path, *args: str):
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                           text=True, timeout=10, encoding="utf-8", errors="replace")
    except (OSError, Exception):
        return None
    return (r.stdout or "").strip() if r.returncode == 0 else None


def checkout_rev(root: Path) -> str:
    """当前检出的短 sha；拿不到给 `unknown`（不编值——编出来的版本号会让比对给出假结论）。"""
    return _git(Path(root), "rev-parse", "--short", "HEAD") or "unknown"


def kb_rev(root: Path) -> str:
    """知识库版本：取**主检出** HEAD（与 trace 顶层 `kb_rev` 同口径）。"""
    main = main_checkout(Path(root)) or Path(root)
    return checkout_rev(main)


# ---------------------------------------------------------------- 源文件读写


def source_dir(root: Path) -> Path:
    return Path(root) / SOURCE_DIR_REL


def source_file(root: Path, week: str) -> Path:
    return source_dir(root) / f"{week}.yaml"


def generated_dir(root: Path) -> Path:
    return Path(root) / GENERATED_DIR_REL


def generated_file(root: Path, dep: str) -> Path:
    return generated_dir(root) / f"{dep}.yaml"


def local_dir(root: Path) -> Path:
    """本机明细目录：**解析到主检出共享侧**（worktree 里跑出的明细，面板与汇总脚本要读得到）。"""
    path, _where = resolve_rel(Path(root), LOCAL_DIR_REL)
    return path


def write_local_record(dir_path: Path, session_id: str, doc: dict) -> Path:
    """写一次诊断的本机明细（gitignored，目录由 shared_dir 解析到主检出共享侧）。"""
    Path(dir_path).mkdir(parents=True, exist_ok=True)
    f = Path(dir_path) / f"{session_id}.yaml"
    text = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, default_flow_style=False)
    write_text_lf(f, text, encoding="utf-8")
    return f


def read_local_record(dir_path: Path, session_id: str):
    f = Path(dir_path) / f"{session_id}.yaml"
    if not f.exists():
        return None
    try:
        return yaml.safe_load(f.read_text(encoding="utf-8")) or None
    except yaml.YAMLError:
        return None


def format_row(row: dict) -> str:
    """一条记录 → 一行（`- {k: v, ...}`，键序固定，值按需加引号）。"""
    kind = row["kind"]
    parts = []
    for k in row_keys(kind):
        if k not in row:
            continue
        v = row[k]
        if k == "purpose":
            inner = ", ".join(f"{p}: {int((v or {}).get(p, 0))}"
                              for p in PURPOSES if int((v or {}).get(p, 0)))
            parts.append(f"purpose: {{{inner}}}" if inner else "purpose: {}")
            continue
        if isinstance(v, str):
            # 值里含 `: ` 或 ` #` 时必须加引号，否则 YAML 从那里起当新键/注释（值被静默截断）。
            needs = (": " in v) or (" #" in v) or v == "" or v.startswith(("[", "{", "*", "&", "!", "|", ">", "%", "@", "`"))
            parts.append(f"{k}: '{v}'" if needs else f"{k}: {v}")
        else:
            parts.append(f"{k}: {v}")
    return "- {" + ", ".join(parts) + "}"


def parse_row(line: str) -> dict:
    """源文件的一行 → 行 dict。解析不出返回 None（由调用方决定报错口径）。"""
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    if s.startswith("- "):
        s = s[2:]
    try:
        doc = yaml.safe_load(s)
    except yaml.YAMLError:
        return None
    return doc if isinstance(doc, dict) else None


def read_source(root: Path):
    """读全部源文件 → (rows, problems)。

    每行带上 `_week`（**按文件名归周**，不是按 run——文档 4 节的边界表规定）与 `_file`。
    解析失败、缺键、键集不合法都进 problems，由校验脚本决定红不红；读取本身不抛。
    """
    rows, problems = [], []
    d = source_dir(root)
    if not d.is_dir():
        return rows, problems
    for f in sorted(d.glob("*.yaml")):
        m = WEEK_FILE_RE.match(f.name)
        week = m.group(1) if m else None
        if week is None:
            problems.append(f"{f.name}: 文件名不是 <YYYY-Www>.yaml 形状——归不了周")
            continue
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip() or line.strip().startswith("#"):
                continue
            row = parse_row(line)
            if row is None:
                problems.append(f"{f.name}:{lineno}: 不是合法的单行 flow mapping")
                continue
            row = dict(row)
            row["_week"] = week
            row["_file"] = f.name
            row["_line"] = lineno
            rows.append(row)
    return rows, problems


def check_row_shape(row: dict):
    """一条记录的键集与类型 → 问题列表（空 = 合法）。"""
    bad = []
    kind = row.get("kind")
    if kind not in KINDS:
        return [f"kind {kind!r} 不在 {KINDS}"]
    for k in ("run", "deployment", "id"):
        if not str(row.get(k) or "").strip():
            bad.append(f"缺 {k}")
    allowed = set(row_keys(kind)) | {"_week", "_file", "_line"}
    extra = sorted(set(row) - allowed)
    if extra:
        bad.append(f"{kind} 行不该有键 {extra}")
    missing = [k for k in row_keys(kind) if k not in row and k not in ("checkout", "kb_rev", "sessions",
                                                                       "last_hit", "note", "purpose")]
    if missing:
        bad.append(f"{kind} 行缺计数键 {missing}")
    for k in COUNT_KEYS[kind]:
        v = row.get(k)
        if v is None:
            continue
        if not isinstance(v, int) or isinstance(v, bool):
            bad.append(f"{k} 应为整数（{v!r}）")
        elif k.endswith("_ms"):
            if v < 0:
                bad.append(f"{k} 不应为负（{v}）")
        elif v < 0:
            bad.append(f"{k} 不应为负（{v}）")
    if kind == "ref":
        pur = row.get("purpose")
        if pur is not None:
            if not isinstance(pur, dict):
                bad.append(f"purpose 应为映射（{pur!r}）")
            else:
                unknown = sorted(set(pur) - set(PURPOSES))
                if unknown:
                    bad.append(f"purpose 有词表外的键 {unknown}（词表 {list(PURPOSES)}）")
    if kind == "baseline":
        lh = row.get("last_hit")
        if lh is not None and not re.match(r"^\d{4}-W\d{2}$", str(lh)):
            bad.append(f"last_hit 应为 ISO 周（如 2026-W39），得到 {lh!r}")
    run = str(row.get("run") or "")
    if not (RUN_RE.match(run) or BASELINE_RUN_RE.match(run)):
        bad.append(f"run 形状非法（{run!r}；应为 YYYY-MM-DD-HHMM 或 baseline-YYYY-MM-DD）")
    return bad


def append_rows(root: Path, week: str, rows: list) -> Path:
    """把若干行追加到该周的源文件（持锁、LF、文件不存在时写头注）。

    read-modify-write 必须持锁：`log_lock` 是同一克隆里共享运行件的写锁原语（exec-log 同一条）。
    """
    f = source_file(root, week)
    f.parent.mkdir(parents=True, exist_ok=True)
    with log_lock(f):
        existing = f.read_text(encoding="utf-8") if f.exists() else ""
        if not existing:
            existing = HEADER
        if not existing.endswith("\n"):
            existing += "\n"
        body = "\n".join(format_row(r) for r in rows)
        write_text_lf(f, existing + body + "\n", encoding="utf-8")
    return f


# ---------------------------------------------------------------- 聚合


def _zero(kind: str) -> dict:
    return {k: 0 for k in COUNT_KEYS[kind]}


def _add_counts(acc: dict, row: dict, kind: str):
    for k in COUNT_KEYS[kind]:
        acc[k] = acc.get(k, 0) + int(row.get(k, 0) or 0)


def _add_purpose(acc: dict, row: dict):
    for p, n in (row.get("purpose") or {}).items():
        acc[p] = acc.get(p, 0) + int(n or 0)


def aggregate(rows: list, dep: str, library_cases: int, library_refs: list):
    """某一部署的记录行 → 生成物文档。

    `totals` 含搬运行（它是生命周期累计）、`by_week` 与本期增量**不含**（搬运行不计活动），
    `cold` 因此按非 baseline 行统计——否则排行、本期增量与长期零选中的判断都会被这份人造基线污染。
    """
    mine = [r for r in rows if r.get("deployment") == dep]
    cases, refs, tools = {}, {}, {}
    weeks, checkouts, runs = set(), set(), []
    active_case_ids = set()
    looked_up_refs = set()

    for r in mine:
        run, kind, rid = str(r.get("run")), r.get("kind"), str(r.get("id"))
        runs.append(run)
        # 归周以**文件名**为准（`read_source` 填的 `_week`）；直接传进来的行（测试、
        # 以后可能的其它读端）没有它，就按 `run` 自己的时间戳归——两条路都能走，
        # 而「按文件名归周」这条口径的判定与报出在校验脚本里（`run` 与文件名不一致要报红）。
        week = r.get("_week") or week_of_run(run)
        if week:
            weeks.add(week)
        if r.get("checkout") and r["checkout"] != "unknown":
            checkouts.add(r["checkout"])
        if kind == "case":
            e = cases.setdefault(rid, {"totals": _zero("case"), "by_week": {}, "recent": []})
            _add_counts(e["totals"], r, "case")
            active_case_ids.add(rid)
            if week:
                w = e["by_week"].setdefault(week, _zero("case"))
                _add_counts(w, r, "case")
            # 本期增量的「最后」由最近一次 resolved / misdiagnosed 的**周**推出；
            # 自证的解决不计入（与结算脚本的口径一致：自证不是独立命中）。
            # 取更近的那一周而不是「后读到的那一行」：同一个 id 可能既有本期行又有搬运行，
            # 按行序覆盖会让结果取决于行在文件里的先后（实测两种顺序得到两个答案）。
            if int(r.get("resolved", 0) or 0) + int(r.get("misdiagnosed", 0) or 0) > 0:
                e["last_hit"] = _later_week(e.get("last_hit"), week)
            e["recent"].append({"run": run, "week": week, **_pick(r, "case")})
        elif kind == "ref":
            e = refs.setdefault(rid, {"totals": _zero("ref"), "purpose": {}, "by_week": {}, "recent": []})
            _add_counts(e["totals"], r, "ref")
            _add_purpose(e["purpose"], r)
            if week:
                w = e["by_week"].setdefault(week, {**_zero("ref"), "purpose": {}})
                _add_counts(w, r, "ref")
                _add_purpose(w["purpose"], r)
            entry = {"run": run, "week": week, **_pick(r, "ref")}
            if r.get("purpose"):
                entry["purpose"] = {p: int(n) for p, n in r["purpose"].items() if int(n or 0)}
            e["recent"].append(entry)
        elif kind == "tool":
            t = tools.setdefault(rid, {"calls": 0, "errors": 0, "timeouts": 0, "_p50w": 0.0, "_p90w": 0.0})
            calls = int(r.get("calls", 0) or 0)
            t["calls"] += calls
            t["errors"] += int(r.get("errors", 0) or 0)
            t["timeouts"] += int(r.get("timeouts", 0) or 0)
            # 跨运行的分位数无法从各运行的分位数精确合成：按调用次数加权平均，量级读数。
            t["_p50w"] += calls * float(r.get("p50_ms", 0) or 0)
            t["_p90w"] += calls * float(r.get("p90_ms", 0) or 0)
        elif kind == "baseline":
            e = cases.setdefault(rid, {"totals": _zero("case"), "by_week": {}, "recent": []})
            for k in COUNT_KEYS["baseline"]:
                e["totals"][k] = e["totals"].get(k, 0) + int(r.get(k, 0) or 0)
            if r.get("last_hit"):
                e["last_hit"] = _later_week(e.get("last_hit"), r["last_hit"])
            e["totals"]["baseline"] = True

    # 先验零查询：本部署记录里从未出现 lookups 行的先验（清单口径见生成物头注与文档 3.3）。
    for r in mine:
        if r.get("kind") == "ref":
            looked_up_refs.add(str(r.get("id")))

    out_tools = {}
    for name in sorted(tools):
        t = tools[name]
        calls = t["calls"]
        out_tools[name] = {
            "calls": calls,
            "p50_ms": int(round(t["_p50w"] / calls)) if calls else 0,
            "p90_ms": int(round(t["_p90w"] / calls)) if calls else 0,
            "errors": t["errors"],
            "timeouts": t["timeouts"],
        }

    out_cases = {}
    for cid in sorted(cases):
        e = cases[cid]
        e["recent"] = sorted(e["recent"], key=lambda x: (str(x.get("run") or "")))[-RECENT_KEEP:]
        e["by_week"] = {w: e["by_week"][w] for w in sorted(e["by_week"])}
        out_cases[cid] = e

    out_refs = {}
    for rid in sorted(refs):
        e = refs[rid]
        e["recent"] = sorted(e["recent"], key=lambda x: (str(x.get("run") or "")))[-RECENT_KEEP:]
        e["by_week"] = {w: e["by_week"][w] for w in sorted(e["by_week"])}
        out_refs[rid] = e

    active = active_case_ids
    doc = {
        "covered": {
            "deployment": dep,
            "runs": len(set(runs)),
            "weeks": sorted(weeks),
            "checkouts": sorted(checkouts),
        },
        "cases": out_cases,
        "references": out_refs,
        "tools": out_tools,
        "cold": {"cases": max(0, library_cases - len(active))},
        "cold_never_looked_up": sorted(set(library_refs) - looked_up_refs),
    }
    return doc


def _later_week(a, b):
    """两个 ISO 周标签取更近的那个；任一为空时取另一个。"""
    if not a:
        return b
    if not b:
        return a
    return a if str(a) >= str(b) else b


def _pick(row: dict, kind: str) -> dict:
    return {k: int(row.get(k, 0) or 0) for k in COUNT_KEYS[kind]}


# ---------------------------------------------------------------- 渲染


def _flow(v) -> str:
    """小映射 / 短列表 → 行内 flow 写法（生成物按 id 一行一读，块状缩进会把文件撑成四倍长）。"""
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_flow(x)}" for k, x in v.items()) + "}"
    if isinstance(v, list):
        return "[" + ", ".join(_flow(x) for x in v) + "]"
    if isinstance(v, str):
        return v if re.match(r"^[A-Za-z0-9_.\-]+$", v) else "'" + v + "'"
    return str(v)


def render(doc: dict) -> str:
    """生成物文档 → 文本（头注 + 有序 YAML，确定性输出，`--check` 逐字节比它）。

    自己渲染而不是 `yaml.safe_dump`：每个 id 的计数要**一行读完**（面板与知识整理都是按 id 扫的），
    而块状缩进会把一份几百个 id 的生成物撑成上千行、diff 也变成整段位移。
    """
    body = {k: v for k, v in doc.items() if not k.startswith("_")}
    out = [GENERATED_HEADER.rstrip("\n")]
    cov = body["covered"]
    out.append(f"covered: {_flow(cov)}")
    out.append("cases:")
    if not body["cases"]:
        out.append("  {}")
    for cid, e in body["cases"].items():
        out.append(f"  {cid}:")
        out.append(f"    totals: {_flow(e['totals'])}")
        if "last_hit" in e:
            out.append(f"    last_hit: '{e['last_hit']}'")
        out.append("    by_week:" if e["by_week"] else "    by_week: {}")
        for w, v in e["by_week"].items():
            out.append(f"      {w}: {_flow(v)}")
        out.append("    recent:" if e["recent"] else "    recent: []")
        for r in e["recent"]:
            out.append(f"    - {_flow(r)}")
    out.append("references:")
    if not body["references"]:
        out.append("  {}")
    for rid, e in body["references"].items():
        out.append(f"  {rid}:")
        out.append(f"    totals: {_flow(e['totals'])}")
        out.append(f"    purpose: {_flow(e['purpose']) if e['purpose'] else '{}'}")
        out.append("    by_week:" if e["by_week"] else "    by_week: {}")
        for w, v in e["by_week"].items():
            out.append(f"      {w}: {_flow(v)}")
        out.append("    recent:" if e["recent"] else "    recent: []")
        for r in e["recent"]:
            out.append(f"    - {_flow(r)}")
    out.append("tools:")
    if not body["tools"]:
        out.append("  {}")
    for name, v in body["tools"].items():
        out.append(f"  {name}: {_flow(v)}")
    out.append(f"cold: {_flow(body['cold'])}")
    cold = body["cold_never_looked_up"]
    if cold:
        out.append("cold_never_looked_up:")
        out += [f"- {x}" for x in cold]
    else:
        out.append("cold_never_looked_up: []")
    return "\n".join(out) + "\n"


def library_inventory(root: Path):
    """全库清点 → (案例条目数, 先验 id 列表)。只读 `knowledge/` 与 `references/` 的活跃面。"""
    root = Path(root)
    case_ids = []
    kdir = root / "knowledge"
    if kdir.is_dir():
        for f in sorted(kdir.rglob("*.yaml")):
            if f.name.startswith("_") or "_archive" in f.parts:
                continue
            try:
                d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            for c in (d.get("cases") or []):
                if c.get("id"):
                    case_ids.append(str(c["id"]))
    ref_ids = []
    rdir = root / "references"
    if rdir.is_dir():
        for f in sorted(rdir.rglob("*.yaml")):
            if f.name.startswith("_"):
                continue
            try:
                d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            # 只收 `status: active`：诊断只读 active 词条，「从没被查过」这个读数说的也是
            # 活跃层。把 deprecated 也算进去，清单里会混进一批根本不会被检索的词条，
            # 读的人去补它们的词面是白花功夫。
            if isinstance(d, dict) and d.get("id") and d.get("status") == "active":
                ref_ids.append(str(d["id"]))
    return len(case_ids), sorted(set(ref_ids))
