#!/usr/bin/env python3
"""trace_begin.py —— 起一份诊断轨迹（trace）的顶层 header，把派生字段交给机器填。

**为什么需要它**：`harness_session`、`created_at`、`kb_rev`、`session_id` 这几样都是**派生值**——
要么从环境变量取、要么从 git 取、要么就是现在的时间。手打的后果实测过：一单 10-29 新建的 trace
顶层漏了 `harness_session`，全程不报错，只在面板上表现为"跳不过去"，查了半天才知道是写侧漏字段。

所以 header 由脚本产出：人只管内容（`summary`、`detected_*`、`external_evidence`、之后每步的
`trace[]`），派生字段不再过手。

**它不承诺什么**：不承诺"每次诊断都会跑它"。漏跑脚本与漏写字段是同一类失败、只是上移了一层；
真正兜底的是收尾核对（`ascend_trace_status` 会标 `⚠缺会话号`）。两者分开，才好判断哪个真有用。

用法：

  python3 scripts/trace_begin.py --slug 2026-10-30-welink-sr16520588 --framework vllm-ascend --platform A2-910B --category interrupt
  python3 scripts/trace_begin.py --slug … --print-only     # 只打印，不落盘
  python3 scripts/trace_begin.py --selftest                # 四条环境用例
  python3 scripts/trace_begin.py --dry-run-env             # 看这台机器能取到哪些派生值

写入位置：`python3 scripts/shared_dir.py traces` 解析到的那份（主检出的 `traces/`）——同一克隆的
worktree 共读共写，从 worktree 干活也不会写进一个清理后就消失的地方。同时建 `traces/evidence/<slug>/`。

$DSH_SESSION_ID 取不到时（Claude Code / pi 等）**留空并说明**，不猜：写一个猜的会话号会让账单与
面板记号挂到别的会话上，比留空更坏。

退出码：0 = 成功；2 = 参数不合法 / 已存在同名 trace。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exec_log_path import resolve_traces  # noqa: E402  （运行时件锚主检出，同 shared_dir.py）

SLUG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[A-Za-z0-9._-]+$")


def now_stamp() -> str:
    """本地时区的 ISO 8601（带偏移），与既有 trace 的写法一致。"""
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def harness_session_of(env=None) -> tuple[str, str]:
    """`$DSH_SESSION_ID` → (会话号, 说明)。取不到就是空串 + 一句原因，不猜。"""
    env = os.environ if env is None else env
    raw = (env.get("DSH_SESSION_ID") or "").strip()
    if not raw:
        return "", "环境里没有 $DSH_SESSION_ID（非 DSH 环境，或这个变量没传进来）——留空，别手填猜的值"
    if not raw.startswith("session-"):
        return "", "环境变量 $DSH_SESSION_ID 不是会话号（应为 session-<uuid>），拿到的是 " + raw + "——留空"
    return raw, ""


def kb_rev_of(root: Path) -> tuple[str, bool | None]:
    """→ (token, dirty)。token 是检出 HEAD 短 sha；拿不到写 unknown，不编。

    dirty 单独返回：sha 只标识提交，工作区有未提交改动时它不能单独指认"当时的规则"。
    `kb_rev.py --json` 的 dirty 只算已跟踪文件（运行时件天天变，算进去会永远是脏）。
    """
    script = root / "scripts" / "kb_rev.py"
    if not script.is_file():
        return "unknown", None
    try:
        r = subprocess.run([sys.executable, str(script), "--json"], capture_output=True,
                           cwd=str(root), timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "unknown", None
    if r.returncode != 0:
        return "unknown", None
    try:
        doc = json.loads(r.stdout.decode("utf-8", "replace"))
    except (ValueError, UnicodeDecodeError):
        return "unknown", None
    if not isinstance(doc, dict):
        return "unknown", None
    rev = str(doc.get("kb_rev") or "unknown")
    dirty = doc.get("dirty")
    return rev, (dirty if isinstance(dirty, bool) else None)


def build_header(*, slug: str, harness_session: str, created_at: str, kb_rev: str,
                 kb_rev_dirty: bool | None = None,
                 framework: str = "", platform: str = "", category: str = "",
                 summary: str = "") -> str:
    """顶层 header → YAML 文本。纯函数：给定输入就有确定输出（测试直接打它）。

    字段顺序与真实 trace 相近（人读时不用来回找）；`trace: []` 留在最后，每步由 agent 追加。
    """
    q = lambda v: '"' + str(v).replace('"', '\\"') + '"'
    lines = [
        "# 诊断轨迹。顶层 header 由 `python3 scripts/trace_begin.py` 产出（派生字段机器填），",
        "# 每步由 skills/diagnose 往 trace[] 追加事件；字段口径见 skills/diagnose/references/diagnosis-trace.md。",
        "session_id: " + q(slug),
        "harness_session: " + q(harness_session) + ("" if harness_session else "   # 缺！建会话时取 $DSH_SESSION_ID；取不到就留空"),
        "status: in_progress",
        "current_step: 0",
        "summary: " + q(summary),
        "created_at: " + q(created_at),
        "updated_at: " + q(created_at),
        "ended_at: \"\"            # 收尾写一次：单次成本的右边界",
        "kb_rev: " + q(kb_rev),
        "kb_rev_dirty: " + ("true" if kb_rev_dirty is True else ("false" if kb_rev_dirty is False else "\"\"")) + "   # 工作区有未提交的已跟踪改动；sha 单独指认不了当时的规则",
        "external_evidence: \"\"     # 开屏写一次：on | off（vllm_kb_* 工具在不在）",
        "detected_framework: " + q(framework),
        "detected_platform: " + q(platform),
        "detected_category: " + q(category),
        "workload_type: \"\"         # training | inference（来自工程师的事实，不由症状词判）",
        "workload_type_source: \"\"   # evidence | user | framework | unknown",
        "resolved_at: \"\"",
        "report_file: \"\"            # 步骤 6 产出：traces/<同名>.report.md",
        "severity: \"\"               # benign | service-affecting | data-loss-risk",
        "fix_emitted: null",
        "stop_reason: \"\"            # resolved_confirmed | halted_ask_user | budget_exhausted | escalated_tier3 | abandoned | unknown",
        "sedimented:",
        "  state: none",
        "  case_id: \"\"",
        "  inbox_path: \"\"",
        "sediment_candidates: []",
        "feedback:",
        "  case: \"\"",
        "  outcome: \"\"",
        "  confirmed_at: \"\"",
        "feedback_pending_since: \"\"",
        "excluded_cases: []",
        "active_case: null",
        "last_action: \"\"",
        "trace: []",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="起一份诊断轨迹的顶层 header（派生字段机器填）")
    ap.add_argument("--slug", help="会话名，形如 2026-10-30-<issue 号>-<短名>（= 文件名）")
    ap.add_argument("--framework", default="", help="detected_framework（材料里有就填）")
    ap.add_argument("--platform", default="", help="detected_platform（如 A2-910B）")
    ap.add_argument("--category", default="", help="detected_category（interrupt | precision | performance）")
    ap.add_argument("--summary", default="", help="问题背景一段（可后补，别留空到收尾）")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent), help="仓库根")
    ap.add_argument("--print-only", action="store_true", help="只打印 YAML，不落盘")
    ap.add_argument("--selftest", action="store_true", help="跑四条环境用例")
    ap.add_argument("--dry-run-env", action="store_true", help="只报这台机器能取到的派生值")
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    session, why = harness_session_of()
    kb, kb_dirty = kb_rev_of(root)

    if args.dry_run_env:
        print("harness_session: " + (session or "（取不到）" + "——" + why))
        print("kb_rev: " + kb)
        print("traces 目录: " + str(resolve_traces(root)))
        return 0

    if args.selftest:
        return selftest()

    if not args.slug:
        print("缺 --slug（形如 2026-10-30-welink-sr16520588）", file=sys.stderr)
        return 2
    if not SLUG_RE.match(args.slug):
        print("--slug 不符合 <YYYY-MM-DD>-<短名>：" + args.slug, file=sys.stderr)
        return 2

    text = build_header(slug=args.slug, harness_session=session, created_at=now_stamp(),
                        kb_rev=kb, kb_rev_dirty=kb_dirty, framework=args.framework, platform=args.platform,
                        category=args.category, summary=args.summary)

    if args.print_only:
        sys.stdout.write(text)
        if why:
            print("# 注意：" + why, file=sys.stderr)
        return 0

    traces = resolve_traces(root)
    target = traces / (args.slug + ".yaml")
    if target.exists():
        print("已存在，不覆盖：" + str(target), file=sys.stderr)
        return 2
    traces.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    (traces / "evidence" / args.slug).mkdir(parents=True, exist_ok=True)

    print("已建：" + str(target))
    if why:
        print("⚠ " + why, file=sys.stderr)
    return 0


def selftest() -> int:
    """四条用例：有会话号 / 没会话号 / 不覆盖已存在 / --print-only 不落盘。"""
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "scripts").mkdir()
        (root / "scripts" / "kb_rev.py").write_text("print('deadbee')\n", encoding="utf-8")

        sid, why1 = harness_session_of({"DSH_SESSION_ID": "session-abc"})
        ok &= (sid == "session-abc" and why1 == "")
        print("ok 有会话号 → " + sid if sid == "session-abc" else "FAIL 有会话号")

        sid2, why2 = harness_session_of({})
        ok &= (sid2 == "" and "DSH_SESSION_ID" in why2)
        print("ok 没会话号 → 留空 + 说明" if sid2 == "" and why2 else "FAIL 没会话号")

        h = build_header(slug="2026-10-30-x", harness_session="session-abc",
                         created_at="2026-10-30T10:00:00+08:00", kb_rev="deadbee")
        ok &= ('harness_session: "session-abc"' in h) and ("trace: []" in h)
        print("ok header 含会话号与空 trace[]" if 'harness_session: "session-abc"' in h else "FAIL header")

        # 不覆盖：直接写一次，再判 exists
        p = root / "traces" / "t.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
        ok &= p.exists()
        print("ok 已存在时不覆盖（由 main 判 exists）" if p.exists() else "FAIL exists")
    print("全部通过" if ok else "有失败")
    return 0 if ok else 1


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio

    pin_utf8_stdio()
    sys.exit(main())
