#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内置分析器的公共执行层（本仓代码，不属于上游分析器）。

职责只有四件：判断分析器是否启用、校验输入、跑适配器、统一写 result.json。
分析算法全部在上游实现里（scripts/analyzers/<name>/），本文件不含任何判据。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.append(str(SCRIPTS))

from _fs import atomic_write_text  # noqa: E402
from exec_log_path import resolve_rel  # noqa: E402

SCHEMA_VERSION = 1
ENV_NAME = "SLEUTH_ANALYZERS"
ENABLE_COMMAND = f"{'python' if sys.platform == 'win32' else 'python3'} scripts/analyzers/cli.py enable"
UPSTREAM_COMMIT = "bf82e88"
UPSTREAM_COMMIT_FULL = "bf82e886ddda0a9955c2d5422f50b0b4caeb80b6"
UPSTREAM_URL = "https://github.com/hu669293657/skills"
TRUE_VALUES = {"1", "on", "true", "yes", "y"}
DEFAULT_TIMEOUT = 600


class AnalyzerError(Exception):
    """分析器自报的失败。status 取 blocked / failed。"""

    def __init__(self, reason: str, detail: str = "", status: str = "blocked"):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail
        self.status = status


def analyzer_preference_path() -> Path:
    path, _ = resolve_rel(SCRIPTS.parent, Path(".local") / "analyzers.enabled")
    return path


def analyzer_state() -> tuple[bool, str]:
    raw = os.environ.get(ENV_NAME)
    if raw is not None:
        return raw.strip().lower() in TRUE_VALUES, f"{ENV_NAME}={raw}"

    path = analyzer_preference_path()
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return False, "默认关闭"
    except (OSError, UnicodeError) as exc:
        return False, f"无法读取本机设置 {path}（{exc}）"
    if value in {"on", "off"}:
        return value == "on", str(path)
    return False, f"本机设置 {path} 的值无效"


def save_analyzer_preference(enabled: bool) -> Path:
    path = analyzer_preference_path()
    atomic_write_text(path, "on\n" if enabled else "off\n")
    return path


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_inputs(raw: str) -> list[str]:
    """接受 JSON 数组或换行分隔的路径；保留原始字符串供错误信息使用。"""
    value = (raw or "").strip()
    if not value:
        return []
    if value.startswith("["):
        try:
            data = json.loads(value)
        except json.JSONDecodeError as exc:
            raise AnalyzerError("bad-input", f"--inputs 不是合法 JSON 数组：{exc}")
        if not isinstance(data, list):
            raise AnalyzerError("bad-input", "--inputs 的 JSON 必须是数组")
        return [str(item).strip() for item in data if str(item).strip()]
    return [line.strip().strip('"').strip("'") for line in value.splitlines() if line.strip()]


def validate_inputs(paths: list[str]) -> tuple[list[dict], list[str]]:
    resolved: list[dict] = []
    missing: list[str] = []
    for value in paths:
        path = Path(os.path.expanduser(value))
        if not path.is_absolute():
            missing.append(f"{value}（不是绝对路径）")
            continue
        if not path.exists():
            missing.append(f"{value}（不存在）")
            continue
        resolved.append({"path": str(path), "kind": "dir" if path.is_dir() else "file"})
    return resolved, missing


def _kill_tree(proc: subprocess.Popen) -> None:
    """超时后结束进程树：Windows 用 taskkill /T，POSIX 用进程组。"""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), 9)  # SIGKILL
        except (OSError, ProcessLookupError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def run_process(
    cmd: list[str],
    cwd: str | Path | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    log_path: str | Path | None = None,
    env_extra: dict[str, str] | None = None,
) -> dict:
    """跑子进程，捕获输出；输出只落日志，不直接进上下文。"""
    started = time.time()
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.Popen(
            [str(part) for part in cmd],
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            start_new_session=os.name != "nt",
        )
    except FileNotFoundError as exc:
        result = {
            "exit_code": None,
            "stdout": "",
            "stderr": f"命令不存在：{exc}",
            "timed_out": False,
            "spawn_error": True,
        }
        proc = None
    else:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            result = {
                "exit_code": proc.returncode,
                "stdout": stdout or "",
                "stderr": stderr or "",
                "timed_out": False,
            }
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""
            result = {
                "exit_code": None,
                "stdout": stdout or "",
                "stderr": stderr or "",
                "timed_out": True,
            }
    result["duration_ms"] = int((time.time() - started) * 1000)
    if log_path is not None:
        log = Path(log_path)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            f"# command: {json.dumps([str(p) for p in cmd], ensure_ascii=False)}\n"
            f"# exit_code: {result.get('exit_code')}\n"
            f"# timed_out: {result.get('timed_out')}\n"
            f"# duration_ms: {result['duration_ms']}\n\n"
            f"--- stdout ---\n{result.get('stdout', '')}\n"
            f"--- stderr ---\n{result.get('stderr', '')}\n",
            encoding="utf-8",
        )
    return result


def read_json(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def file_signature(path: str | Path) -> tuple[int, int] | None:
    """产物在本次子进程运行前的身份（mtime_ns, size）；不存在返回 None。

    适配器在跑上游前取一次、跑完再取一次：同一路径的身份未变，说明这次没有
    写出新产物，读到的是上一次留下的结果。用身份对比而不是「文件是否存在」，
    是为了让复用输出目录时失败也留下明确原因，而不是把旧结果标成新输入的 fact。
    """
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def is_fresh(path: str | Path, before: tuple[int, int] | None) -> bool:
    """文件存在且身份与运行前不同。"""
    current = file_signature(path)
    return current is not None and current != before


def write_json(path: str | Path, data: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def clip(text: object, limit: int) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return f"{value[:limit]}……（已截断，原文 {len(value)} 字符）"


def tail(text: object, limit: int = 800) -> str:
    value = str(text or "").strip()
    return value if len(value) <= limit else "……" + value[-limit:]


def new_call_id() -> str:
    return f"{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"


def default_out_dir(session_id: str = "") -> Path:
    """落到主检出的 traces/evidence/<session>/tool-runs/<call_id>/。"""
    repo = Path(__file__).resolve().parents[2]
    try:
        proc = subprocess.run(
            [sys.executable, str(repo / "scripts" / "shared_dir.py"), "traces"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
        if proc.returncode == 0 and lines:
            traces = Path(lines[-1])
        else:
            traces = repo / "traces"
    except (OSError, subprocess.SubprocessError):
        traces = repo / "traces"
    session = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (session_id or "manual"))
    return traces / "evidence" / session / "tool-runs" / new_call_id()


def required_input(analyzer: str) -> str:
    """从 registry 取这个分析器的最小输入形态，供失败时提示用户补料。"""
    try:
        from registry import find

        item = find(analyzer)
        return str(item.get("inputs") or "") if item else ""
    except Exception:
        return ""


def _data_needed(required: str, extra) -> list[str]:
    items: list[str] = []
    if required:
        items.append(required)
    for value in extra or []:
        text = str(value or "").strip()
        if text and text not in items:
            items.append(text)
    return items


def responder(result: dict) -> str:
    status = result.get("status", "failed")
    lines: list[str] = []
    if status in ("failed", "blocked"):
        lines.append(f"分析器调用未完成：{result.get('reason') or 'unknown'}")
        detail = result.get("detail") or result.get("summary") or ""
        if detail:
            lines.append(clip(detail, 500))
        data_needed = result.get("data_needed") or []
        if data_needed:
            lines.append("需要的数据：" + "；".join(str(item) for item in data_needed))
        lines.append("按 analyzer-dispatch 的退化规则回到原路径，本单不重试；不要把它记成「已排除」。")
        if result.get("result_file"):
            lines.append(f"结构化结果：{result['result_file']}")
        return "\n".join(lines)

    lines.append(
        "分析器：{name}｜版本：{version}｜状态：{status}｜耗时：{seconds:.1f} s".format(
            name=result.get("analyzer", "unknown"),
            version=result.get("analyzer_version", "unknown"),
            status=status,
            seconds=(result.get("duration_ms") or 0) / 1000.0,
        )
    )
    lines.append(result.get("summary") or "（分析器没有给摘要）")
    findings = result.get("findings") or []
    if findings:
        lines.append("关键发现：")
        for index, item in enumerate(findings[:5], 1):
            claim = item.get("claim") if isinstance(item, dict) else str(item)
            lines.append(f"{index}. {claim}")
        if len(findings) > 5:
            lines.append(f"（另有 {len(findings) - 5} 条发现，见 result.json）")
    missing = result.get("missing") or []
    if missing:
        lines.append("缺数据：" + "；".join(str(item) for item in missing))
    artifacts = result.get("artifacts") or []
    if artifacts:
        lines.append("报告与产物：" + "、".join(str(item) for item in artifacts))
    if result.get("result_file"):
        lines.append(f"结构化结果：{result['result_file']}")
    return "\n".join(lines)


def _base_result(analyzer: str, version: str, out_dir: Path) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "analyzer": analyzer,
        "analyzer_version": version,
        "status": "failed",
        "summary": "",
        "findings": [],
        "missing": [],
        "artifacts": [],
        "data_needed": [],
        "result_file": str(out_dir / "result.json"),
    }


def force_utf8() -> None:
    """Windows 控制台默认 cp1252，中文摘要会抛 UnicodeEncodeError。

    agent 读的是输出文本，统一成 UTF-8 比跟随终端代码页更可预测；
    reconfigure 不可用（老解释器、被替换的流）时保持原行为，不影响返回码。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def run_adapter(analyzer: str, version: str, analyze, description: str = "") -> int:
    """适配器统一入口：参数、开关、输入校验、计时、result.json、退出码。"""
    force_utf8()
    parser = argparse.ArgumentParser(description=description or f"{analyzer} 适配器")
    parser.add_argument("--inputs", required=True, help="本机绝对路径的 JSON 数组，或换行分隔的路径")
    parser.add_argument("--out-dir", default="", help="输出目录（默认主检出 traces/evidence/<session>/tool-runs/<call_id>）")
    parser.add_argument("--session-id", default="", help="当前诊断 session_id；只用于默认输出路径")
    parser.add_argument("--ab", default="", help="两组数据比对时标基准：A 或 B")
    parser.add_argument("--purpose", default="", help="这次要回答的问题，一句话")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"超时秒数（默认 {DEFAULT_TIMEOUT}）")
    args = parser.parse_args()

    enabled, source = analyzer_state()
    if not enabled:
        print(responder({
            "status": "blocked",
            "reason": "analyzer-disabled",
            "detail": f"分析器已关闭（{source}）。本机启用命令：{ENABLE_COMMAND}",
        }))
        return 3

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else default_out_dir(args.session_id)
    started = time.time()
    result = _base_result(analyzer, version, out_dir)
    required = required_input(analyzer)

    try:
        raw_inputs = parse_inputs(args.inputs)
    except AnalyzerError as exc:
        result.update(
            status=exc.status,
            reason=exc.reason,
            detail=exc.detail,
            data_needed=_data_needed(required, []),
        )
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            write_json(out_dir / "result.json", result)
        except OSError:
            pass
        print(responder(result))
        return 1

    if not raw_inputs:
        result.update(
            status="blocked",
            reason="no-input",
            detail="没有给绝对路径。",
            data_needed=_data_needed(required, []),
        )
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            write_json(out_dir / "result.json", result)
        except OSError:
            pass
        print(responder(result))
        return 1

    resolved, missing = validate_inputs(raw_inputs)
    if missing:
        result.update(
            status="blocked",
            reason="bad-input",
            detail="以下路径不能用，本次未执行分析：" + "；".join(missing),
            missing=missing,
            data_needed=_data_needed(required, []),
        )
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            write_json(out_dir / "result.json", result)
        except OSError:
            pass
        print(responder(result))
        return 1

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"输出目录不可用：{out_dir}（{exc}）", file=sys.stderr)
        return 1
    invocation = {
        "schema_version": SCHEMA_VERSION,
        "analyzer": analyzer,
        "analyzer_version": version,
        "call_id": out_dir.name,
        "session_id": "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (args.session_id or "manual")),
        "inputs": resolved,
        "ab": args.ab,
        "purpose": args.purpose,
        "timeout_seconds": args.timeout,
        "python": sys.executable,
        "enabled_by": source,
        "started_at": now_iso(),
    }
    write_json(out_dir / "invocation.json", invocation)

    payload = None
    try:
        payload = analyze(resolved, out_dir, args)
        if not isinstance(payload, dict):
            raise AnalyzerError("analyzer-failed", "适配器没有返回结果对象", status="failed")
        result.update(payload)
        if result.get("status") in ("blocked", "failed"):
            reason = str(result.get("reason") or "")
            result["data_needed"] = (
                _data_needed(required, result.get("missing") or [])
                if reason in ("no-input", "bad-input", "analyzer-failed")
                else []
            )
        elif result.get("status") == "partial":
            # 可选缺口只进 missing：data_needed 的语义是「不补就跑不下去」，
            # 把部分缺失写进这里会让 agent 去要一份本次分析并不需要的材料。
            result["data_needed"] = []
        else:
            result["data_needed"] = []
    except AnalyzerError as exc:
        result.update(
            status=exc.status,
            reason=exc.reason,
            detail=exc.detail,
            missing=exc.detail and [exc.detail] or [],
            data_needed=(
                _data_needed(required, [])
                if exc.reason in ("no-input", "bad-input", "analyzer-failed")
                else (["按 rank 或时间窗裁剪后的同一类数据（当前输入超过预算）"] if exc.reason == "timeout" else [])
            ),
        )
    except Exception as exc:  # 分析器崩溃不抛给调用方，落一条失败结果
        result.update(
            status="failed",
            reason="analyzer-crashed",
            detail=f"{type(exc).__name__}: {exc}; {tail(traceback.format_exc(), 600)}",
            data_needed=[],
        )

    result.setdefault("schema_version", SCHEMA_VERSION)
    result["analyzer"] = analyzer
    result["analyzer_version"] = payload.get("analyzer_version", version) if isinstance(payload, dict) else version
    result["duration_ms"] = int((time.time() - started) * 1000)
    result["result_file"] = str(out_dir / "result.json")
    result["inputs"] = resolved
    result["purpose"] = args.purpose
    result["ab"] = args.ab
    result["finished_at"] = now_iso()
    write_json(out_dir / "result.json", result)

    print(responder(result))
    print(f"RESULT_JSON={result['result_file']}")
    return 0 if result.get("status") in ("ok", "partial") else 1
