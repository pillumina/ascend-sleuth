#!/usr/bin/env python3
"""stage / pilot 的确定性冒烟 runner：只写证据文件，不读答案。

用途：没有真实诊断轨迹时，验证 stage/pilot 的接线（plan → run → judge → report）
能不能走通。它把 ``SLEUTH_INPUT`` 原样写进输出，不读 ``judge-input.json``，也不
声称诊断质量；用它的结论必须带 smoke/exploratory 标记，不得标 validated。

stage 与 pilot 的 runner 契约：读环境变量 ``SLEUTH_TRACE`` / ``SLEUTH_OUT``，
各写一个文件。stdout/stderr 不参与判定。
"""

import hashlib
import json
import os
from pathlib import Path


def main() -> int:
    trace = Path(os.environ["SLEUTH_TRACE"])
    out = Path(os.environ["SLEUTH_OUT"])
    payload = {
        "stage": os.environ.get("SLEUTH_STAGE") or "smoke",
        "sample": os.environ.get("SLEUTH_SAMPLE_ID") or "unknown",
        "arm": os.environ.get("SLEUTH_ARM") or "candidate",
        "runner": "scripts/smoke_runner.py",
        "smoke": True,
    }
    raw_input = os.environ.get("SLEUTH_INPUT") or "{}"
    try:
        input_doc = json.loads(raw_input)
    except json.JSONDecodeError:
        input_doc = {"raw": raw_input}
    payload["input_sha256"] = hashlib.sha256(
        json.dumps(input_doc, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    trace.parent.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text(
        "".join(f"{key}: {json.dumps(value, ensure_ascii=False)}\n"
                for key, value in payload.items()),
        encoding="utf-8",
    )
    out.write_text(
        "# 冒烟输出\n\n"
        "本文件由 scripts/smoke_runner.py 生成，只证明 runner 接线可跑；"
        "不包含诊断结论，不能作为质量证据。\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    raise SystemExit(main())
