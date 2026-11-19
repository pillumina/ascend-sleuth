"""确定性 benchmark：工具/检索类改动不走完整诊断。"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional


class BenchmarkError(ValueError):
    pass


def _run_one(argv: List[str], cwd: Path, runs: int, timeout: float) -> Dict[str, Any]:
    samples = []
    for _ in range(runs):
        started = time.monotonic()
        try:
            proc = subprocess.run(
                argv, cwd=str(cwd), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout, check=False,
            )
            sample = {
                "exit": proc.returncode,
                "ms": round((time.monotonic() - started) * 1000, 3),
                "stdout": proc.stdout[-500:],
                "stderr": proc.stderr[-500:],
            }
        except subprocess.TimeoutExpired:
            sample = {
                "exit": None,
                "ms": round((time.monotonic() - started) * 1000, 3),
                "stdout": "",
                "stderr": f"timeout after {timeout}s",
            }
        samples.append(sample)
    ok = all(sample["exit"] == 0 for sample in samples)
    return {
        "ok": ok,
        "runs": runs,
        "median_ms": round(median(s["ms"] for s in samples), 3),
        "samples": samples,
    }


def compare(baseline_root: Path, candidate_root: Path, argv: List[str],
            runs: int = 3, timeout: float = 120.0) -> Dict[str, Any]:
    if not isinstance(argv, list) or not argv or not all(
            isinstance(item, str) and item for item in argv):
        raise BenchmarkError("argv must be a non-empty list of non-empty strings")
    if not isinstance(runs, int) or isinstance(runs, bool) or runs < 1:
        raise BenchmarkError("runs must be a positive integer")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise BenchmarkError("timeout must be positive")
    baseline_root, candidate_root = Path(baseline_root), Path(candidate_root)
    for name, path in (("baseline", baseline_root), ("candidate", candidate_root)):
        if not path.is_dir():
            raise BenchmarkError(f"{name} root is not a directory: {path}")
    baseline = _run_one(argv, baseline_root, runs, float(timeout))
    candidate = _run_one(argv, candidate_root, runs, float(timeout))
    delta = candidate["median_ms"] - baseline["median_ms"]
    ratio = (candidate["median_ms"] / baseline["median_ms"]
             if baseline["median_ms"] > 0 else None)
    return {
        "argv": list(argv),
        "runs": runs,
        "baseline": baseline,
        "candidate": candidate,
        "delta_ms": round(delta, 3),
        "ratio": None if ratio is None else round(ratio, 4),
    }


def load_argv(raw: str) -> List[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"argv is not valid JSON: {exc}") from exc
    if not isinstance(value, list):
        raise BenchmarkError("argv must be a JSON list")
    return value
