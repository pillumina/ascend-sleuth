#!/usr/bin/env python3
# metrics_snapshot.py —— 一期快照的**单一产出命令**（覆盖全部来源，每块标出处）
#
# 为什么需要（2026-09-10 审计实测）：
#   `docs/metrics.md` 写"所有指标由 trace_metrics.py 计算（单一数据源）"——**不成立**：
#   timeline 里的指标实际来自四类来源：
#     ① 诊断侧   `trace_metrics.py`（traces/*.yaml）
#     ② 结构侧   `build_index.py` 头注（容量格子 / case 总数）+ `verify_references.py`（词条数）
#     ③ 内容流程 `log_skill_exec.py` → `tail_exec_log.py --summary`（收尾次数 / 无信号次数）
#     ④ 评测侧   ixn / golden / S2 等按需产出（本命令不臆造，缺就如实不写）
#   周批流程第 1 步只跑 trace_metrics → ②③④ 全靠人手工搬运 → 实测结构指标 10 天没进快照
#   （快照 `case_total 52` vs 现实 **158**，某格 `85/30` 已是 soft_cap 的 2.8 倍，
#   而快照里那次还是 `36/30`）。本命令把 ①②③ 拼成一份骨架（④ 按需），每块标 source，
#   人复核后 append —— 消除手工搬运这个环节。
#
# 用法：
#   python3 scripts/metrics_snapshot.py                 # 人读摘要 + YAML 骨架
#   python3 scripts/metrics_snapshot.py --emit-yaml     # 只输出 YAML 骨架（供 append）
#   python3 scripts/metrics_snapshot.py --json          # 机器读（体检脚本/实验断言）
#   python3 scripts/metrics_snapshot.py --period 2026-W37 --kind live
#
# 边界（诚实退化）：拿不到的来源如实不写并在摘要里点名，**不写 0 冒充**。

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import yaml

from exec_log_path import resolve as resolve_exec_log     # noqa: F401  （路径语义单一事实源）
from tail_exec_log import aggregate as aggregate_exec_log, load_records


def _run_no_pipe(root: Path, args: list, env):
    """无管道捕获地跑子进程：输出重定向到临时文件，再把文件读回来。

    为什么必须有（2026-09-11 实测）：诊断面板跑体检时，`subprocess.run(capture_output=True)`
    报 `PermissionError: [WinError 5] 拒绝访问`——受限执行环境里**管道创建**被拒。
    于是 `collect_structural` 整体抛错，面板上"容量越界 85/30"这种最要命的信号直接消失
    （只见一截看不懂的 traceback）。管道不可用是环境的限制，不是"这个数拿不到"——
    改用文件重定向就能拿到同一个结果，检测腿不必因此断掉。
    落在 tempfile.gettempdir()（环境保证可写），用完即删。
    """
    fd_out, path_out = tempfile.mkstemp(prefix="metrics_run_", suffix=".out")
    fd_err, path_err = tempfile.mkstemp(prefix="metrics_run_", suffix=".err")
    os.close(fd_out)
    os.close(fd_err)
    try:
        with open(path_out, "wb") as fo, open(path_err, "wb") as fe:
            r = subprocess.run([sys.executable, *args], cwd=str(root), stdout=fo, stderr=fe,
                               stdin=subprocess.DEVNULL, env=env, timeout=300)
        with open(path_out, "rb") as fo:
            out = fo.read().decode("utf-8", "replace")
        with open(path_err, "rb") as fe:
            err = fe.read().decode("utf-8", "replace")
        return r.returncode, out + err
    finally:
        for p in (path_out, path_err):
            try:
                os.unlink(p)
            except OSError:
                pass


def _run(root: Path, args: list):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        r = subprocess.run([sys.executable, *args], cwd=str(root), capture_output=True, text=True,
                           env=env, encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (PermissionError, OSError) as e:
        # 管道被拒（受限执行环境）→ 退回文件重定向；连它也不成，才如实报"跑不了"
        try:
            return _run_no_pipe(root, args, env)
        except Exception as e2:
            msg = " ".join(str(e2).split())
            return 127, (f"子进程无法执行（{type(e).__name__}: {' '.join(str(e).split())}；"
                         f"文件重定向回退也失败：{type(e2).__name__}: {msg[:160]}）")


def resolve_trace_root(root: Path):
    """traces/ 该读哪一份：优先**主检出**（各检出各一份的运行时件；worktree 里往往为空），
    退化到当前检出；两处都没有则如实说"没有"。返回 (根目录, where, session 数)。

    为什么需要（2026-09-10 实测）：`traces/` 是 .gitignore 运行时件、各 worktree 各一份，
    而周批的指标生产者要读它——**在 worktree 里跑周批会静默产出空诊断指标**
    （"未找到任何 traces/*.yaml"），而仓库纪律要求 agent 都在 worktree 里干活。
    """
    from exec_log_path import main_checkout
    main = main_checkout(root)
    for cand, where in ((main, "主检出（同一克隆共享侧）"), (root, "当前检出")):
        if cand is None:
            continue
        files = sorted((cand / "traces").glob("*.yaml")) if (cand / "traces").is_dir() else []
        if files:
            return cand, where, len(files)
    return (main or root), "两处都没有 traces/*.yaml", 0


def collect_trace(root: Path):
    """诊断侧：复用 trace_metrics.py 的既有计算（不重实现），取其 YAML 块。"""
    trace_root, where, n = resolve_trace_root(root)
    rc, out = _run(root, ["scripts/trace_metrics.py", "--emit-yaml-only", "--root", str(trace_root)])
    if rc != 0:
        return None, f"trace_metrics.py 失败（exit {rc}）：{out.strip().splitlines()[-1][:120] if out.strip() else '无输出'}", None
    try:
        doc = yaml.safe_load(out)
        metrics = (doc or {}).get("metrics")
        if not isinstance(metrics, dict):
            return None, f"trace_metrics.py 输出里没有 metrics（traces 来源：{where}，{n} 个 session）", None
        return metrics, None, f"trace_metrics.py（traces/*.yaml ← {where}，{n} 个 session）"
    except Exception as e:
        return None, f"trace_metrics.py 输出解析失败：{e}", None


def collect_structural(root: Path):
    """结构侧：容量格子 / case 总数（build_index 头注）+ 词条数（verify_references 的权威计数）。"""
    out = {"case_total": None, "reference_total": None, "capacity_by_ns": {}}
    notes = []
    index_path = root / "knowledge" / "_index.yaml"
    if index_path.exists():
        text = index_path.read_text(encoding="utf-8")
        m = re.search(r"case 总数：\s*(\d+)", text)
        if m:
            out["case_total"] = int(m.group(1))
        else:
            notes.append("_index.yaml 头注里没有 'case 总数'（格式变了？）")
        try:
            # 复用面板侧的解析实现（同一格式，避免第三份正则副本）
            import ev_board_data
            out["capacity_by_ns"] = ev_board_data.parse_index_header(text)
        except Exception as e:
            notes.append(f"容量头注解析失败：{e}")
    else:
        notes.append("knowledge/_index.yaml 不存在（先跑 build_index.py）")

    rc, vout = _run(root, ["scripts/verify_references.py", "--check"])
    if rc == 0:
        m = re.search(r"（(\d+) 个词条", vout)
        out["reference_total"] = int(m.group(1)) if m else None
        if out["reference_total"] is None:
            notes.append("verify_references 输出里没找到词条数")
    else:
        notes.append(f"verify_references --check 失败（exit {rc}）——词条数取不到")
    return out, notes


def collect_content_flow(root: Path):
    """内容流程侧：exec-log 聚合（收尾次数 / 其中无信号次数）。同一克隆共享件，见 exec_log_path.py。"""
    import tail_exec_log
    records, state, path, where = load_records(root)
    rows = [tail_exec_log.summarize(r) for r in records if isinstance(r, dict)]
    agg = aggregate_exec_log(rows)
    return {
        "content_flow_runs": agg["total"],
        "evolve_check_runs": agg["evolve_check_runs"],
        "evolve_check_no_signal": agg["evolve_check_no_signal"],
    }, {"state": state, "path": str(path), "where": where}


def build_metrics(root: Path):
    """三块拼一份 metrics；拿不到的块如实缺席并记录原因。"""
    metrics, sources, missing = {}, {}, []

    trace, err, src = collect_trace(root)
    if trace:
        metrics.update(trace)
        sources["diagnose_side"] = src
    else:
        missing.append(f"诊断侧：{err}")

    structural, s_notes = collect_structural(root)
    if structural["case_total"] is not None:
        metrics["case_total"] = structural["case_total"]
    if structural["reference_total"] is not None:
        metrics["reference_total"] = structural["reference_total"]
    if structural["capacity_by_ns"]:
        metrics["capacity_by_ns"] = structural["capacity_by_ns"]
    sources["structural_side"] = "build_index.py 头注（容量/case 总数）+ verify_references.py（词条数）"
    missing.extend(s_notes)

    flow, flow_meta = collect_content_flow(root)
    metrics.update(flow)
    sources["content_flow_side"] = f"log_skill_exec.py → tail_exec_log.py（{flow_meta['where']}）"
    if flow["content_flow_runs"] == 0:
        missing.append("内容流程侧：exec-log 当前为空（尚无收尾记录）")

    return metrics, sources, missing


def main():
    ap = argparse.ArgumentParser(description="metrics 一期快照的单一产出命令")
    ap.add_argument("--emit-yaml", action="store_true", help="只输出 YAML 骨架")
    ap.add_argument("--json", action="store_true", help="输出 JSON（体检脚本/实验断言）")
    ap.add_argument("--period", default=None, help="期号（默认按 ISO 周推断，如 2026-W37）")
    ap.add_argument("--kind", default="live", choices=["live", "replay", "example"])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()
    root = args.root.resolve()

    iso = date.today().isocalendar()
    period = args.period or f"{iso[0]}-W{iso[1]:02d}"
    metrics, sources, missing = build_metrics(root)

    if args.json:
        print(json.dumps({"period": period, "kind": args.kind, "metrics": metrics,
                          "sources": sources, "missing": missing}, ensure_ascii=False, default=str))
        return 0

    if args.emit_yaml:
        print(yaml.safe_dump({"periods": [{
            "period": period, "kind": args.kind,
            "title": "本期指标（metrics_snapshot.py 组装，人复核）",
            "recorded_at": date.today().isoformat(),
            "source": "metrics_snapshot.py（诊断侧+结构侧+内容流程侧，逐块见 sources）",
            "sources": sources,
            "metrics": metrics,
            "notes": "# 人复核时补：分母是否够、miss 归因、本期说明（阈值见 metrics/gates.yaml）\n",
        }]}, allow_unicode=True, sort_keys=False))
        return 0

    print(f"metrics 快照骨架 · {period}（kind={args.kind}）")
    print(f"  指标块 {len(metrics)} 个字段，来源：")
    for k, v in sources.items():
        print(f"    - {k}: {v}")
    if missing:
        print("  如实缺席（不写 0 冒充）：")
        for m in missing:
            print(f"    ! {m}")
    caps = metrics.get("capacity_by_ns") or {}
    over = [(ns, cat, c["count"], c["cap"]) for ns, cells in caps.items()
            for cat, c in cells.items() if c["count"] > c["cap"]]
    if over:
        print("  已越界格子（判据见 metrics/gates.yaml，检测走 metrics_health.py）：")
        for ns, cat, n, cap in over:
            print(f"    ! {ns} · {cat} = {n}/{cap}")
    print("\n下一步：人复核 → `python3 scripts/metrics_health.py` 体检 → append 进 metrics/timeline.yaml → verify_metrics --check")
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
