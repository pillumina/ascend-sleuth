#!/usr/bin/env python3
"""trace_state.py —— 诊断状态投影（面板与 CLI 共用的一份）

`_trace_state.project()` 的薄命令行封装；面板 host 调它拿到每单的派生量、可用动作与
能力位，Python 读端直接 import `_trace_state`，不各自实现判据。

用法：

  python3 scripts/trace_state.py --json                 # 全部 session 的投影
  python3 scripts/trace_state.py --session <session_id> --json
  python3 scripts/trace_state.py --check                # 词表自洽（CI 用，不读 traces）
  python3 scripts/trace_state.py --json --can-write     # 面板传能力位（host 判断后传入）

退出码：0 = 成功；2 = 词表自洽检查失败；3 = traces 目录读不到。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trace_state import SCHEME, check_vocab, load_vocab, project  # noqa: E402
from exec_log_path import resolve_traces  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="诊断状态投影")
    ap.add_argument("--root", default=None, help="仓库根（默认脚本上一级；读 trace-status.yaml 与 knowledge/）")
    ap.add_argument("--traces", default=None, help="traces 目录（默认由主检出解析）")
    ap.add_argument("--session", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--can-write", action="store_true")
    ap.add_argument("--write-root", default="")
    ap.add_argument("--no-root", action="store_true", help="解析不到主检出（canWrite=false, E_NO_ROOT）")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parents[1]
    if args.check:
        vocab = load_vocab(root)
        errs = check_vocab(vocab)
        if errs:
            print("词表自洽检查失败：")
            for e in errs:
                print("  - " + e)
            return 2
        print(f"词表自洽：{len(vocab['statuses'])} 个状态、{len(vocab['endings'])} 种收尾方式、"
              f"{len(vocab['transitions'])} 个动作")
        return 0

    traces = Path(args.traces) if args.traces else resolve_traces(root)
    if not traces.is_dir():
        if args.json:
            print(json.dumps({"ok": False, "code": "E_TRACES_NOT_FOUND",
                              "message": f"traces 目录不存在：{traces}"}, ensure_ascii=False))
        else:
            print(f"traces 目录不存在：{traces}", file=sys.stderr)
        return 3
    reason_code = "" if args.can_write else ("E_NO_ROOT" if args.no_root else "E_PERM")
    caps = {"canWrite": bool(args.can_write), "writeRoot": args.write_root,
            "reasonCode": reason_code,
            "reason": "" if args.can_write else ("解析不到主检出" if args.no_root else "当前会话没有写权限")}
    data = project(traces, root, caps, only=args.session)
    data["schemeVersion"] = SCHEME
    if args.json:
        print(json.dumps(data, ensure_ascii=False))
    else:
        for s in data["sessions"]:
            print(f"{s['sessionId']}\t{s['status']}\t{','.join(s['actions'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
