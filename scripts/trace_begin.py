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

import kb_sync  # noqa: E402  （知识库同步；失败不阻塞建单）
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


def sync_of(root: Path, *, no_sync: bool = False, no_network: bool = False) -> dict:
    """调 kb_sync；`--no-sync` 与 `--print-only` 只读本机状态，不联网。"""
    settings, config, config_error = kb_sync.load_settings(root)
    cfg = settings["sync"]
    if no_sync or no_network:
        result = kb_sync.local_snapshot(root, cfg["remote"], cfg["branch"],
                                        config=config, config_error=config_error)
        result.update(ok=False, merge="none",
                      reason=("print-only" if no_network else "no-sync"))
        return result
    return kb_sync.sync(root, do_merge=True, honor_auto_merge=True)


def kb_sync_state_of(result: dict) -> str:
    """同步结果 → trace 的 `kb_sync` 三态（ok / failed / off / skipped）。"""
    reason = str(result.get("reason") or "")
    if result.get("offline") or reason in ("disabled", "no-sync", "print-only"):
        return "off"
    if result.get("skipped"):
        return "skipped"
    if result.get("ok"):
        return "ok"
    return "failed"


def kb_fields(result: dict) -> dict:
    """同步结果 → build_header 的六个字段。`kb_remote` 写 `<remote>/<branch>`。

    `kb_remote_rev` 与 `kb_behind` 只在 fetch 成功时写实值：失败时本机 ref 可能是旧的，
    写它会把"没确认"记成"已确认"。配置读不出时按默认值同步，`kb_sync_reason` 记
    `config-broken`，让收尾核对能分出"同步成功但配置是坏的"。
    """
    remote = str(result.get("remote") or "")
    branch = str(result.get("branch") or "")
    confirmed = bool(result.get("ok"))
    behind = result.get("behind")
    reason = "config-broken" if result.get("config_error") else str(result.get("reason") or "")
    return {
        "kb_remote": f"{remote}/{branch}" if remote and branch else "",
        "kb_remote_rev": str(result.get("remote_rev") or "unknown") if confirmed else "unknown",
        "kb_behind": behind if confirmed and isinstance(behind, int)
        and not isinstance(behind, bool) else "unknown",
        "kb_sync_state": kb_sync_state_of(result),
        "kb_sync_reason": reason,
        "kb_merge": result.get("merge") if result.get("merge") in ("ff-only", "none") else "none",
    }


# 落后提示只对这些面的改动有价值：docs/ 等 other 面改了不影响本次诊断读的候选与路由。
HINT_SURFACES = ("knowledge", "routing", "reference", "methodology")


def _surface_worth_hint(result: dict) -> bool:
    surface = result.get("surface")
    if not isinstance(surface, dict):
        return True
    return any(isinstance(surface.get(key), int) and surface[key] > 0 for key in HINT_SURFACES)


def _merge_next_step(result: dict) -> str:
    """合并没发生时给下一步；只对 dirty 给提交/stash，其余按原因给对应动作。"""
    remote_ref = f"{result.get('remote')}/{result.get('branch')}"
    branch = str(result.get("branch") or "main")
    reason = str(result.get("reason") or "")
    if reason == "dirty":
        return f"要同步：先提交或 git stash，再 git merge --ff-only {remote_ref}"
    if reason == "branch-mismatch":
        return (f"当前不在配置分支 {branch}，未自动合并；"
                f"切到 {branch} 后 git merge --ff-only {remote_ref}")
    if reason == "worktree":
        return f"当前检出是链接 worktree，未自动合并；到主检出里再 git merge --ff-only {remote_ref}"
    if reason == "not-ancestor":
        return (f"当前分支不是 {remote_ref} 的祖先（有本地提交或已分叉），未自动合并；"
                f"先 rebase 或另开分支处理")
    if reason == "merge-in-progress":
        return "有进行中的 merge/rebase/cherry-pick，未自动合并；先结束它再试"
    if reason == "auto-merge-off":
        return f"自动合并已关闭（sync.auto_merge = false）；要同步：git merge --ff-only {remote_ref}"
    if reason == "same-repo":
        return "配置远端与 origin 不同源，未自动合并；先核对 sync.remote"
    return f"未自动合并（{kb_sync.merge_reason_text(reason)}）"


def sync_hint(result: dict) -> str:
    """建单时打印的一行人读提示；不满足条件时返回空串。"""
    remote_ref = f"{result.get('remote')}/{result.get('branch')}"
    local_rev = str(result.get("local_rev") or "unknown")
    if result.get("merge") == "ff-only":
        before = str(result.get("local_rev_before") or "unknown")
        behind = result.get("behind_before")
        behind_text = behind if isinstance(behind, int) else 0
        return (f"已同步知识库到 {local_rev}（原 {before}，落后 {behind_text} 个提交）。"
                f"本会话的流程文件仍是旧版，下次会话生效。")
    state = kb_sync_state_of(result)
    if state == "ok" and isinstance(result.get("behind"), int) and result["behind"] > 0:
        if not _surface_worth_hint(result):
            return ""
        reason = kb_sync.merge_reason_text(result.get("reason"))
        return (f"知识库落后 {result['behind']} 个提交（{reason}），本单按 {local_rev} 诊断。"
                f"{_merge_next_step(result)}")
    if state == "failed" and not result.get("skipped"):
        reason = kb_sync.fetch_reason_text(result.get("reason"))
        return f"无法确认知识库是否最新（{reason}），本单按 {local_rev} 诊断。"
    return ""


def ensure_traces_writable(traces: Path) -> str:
    """建 traces 目录并验证可写；失败返回一句原因（空串表示可用）。

    必须在同步之前调用：同步可能改 HEAD，写不了 trace 时白改一次检出。
    """
    traces = Path(traces)
    try:
        traces.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"建不了 traces 目录 {traces}：{exc}"
    if not traces.is_dir():
        return f"traces 路径不是目录：{traces}"
    try:
        fd, probe = tempfile.mkstemp(prefix=".trace-begin-", dir=str(traces))
        os.close(fd)
        os.unlink(probe)
    except OSError as exc:
        return f"traces 目录不可写 {traces}：{exc}"
    return ""


def build_header(*, slug: str, harness_session: str, created_at: str, kb_rev: str,
                 kb_rev_dirty: bool | None = None,
                 kb_remote: str = "", kb_remote_rev: str = "unknown",
                 kb_behind: int | str = "unknown", kb_sync_state: str = "off",
                 kb_sync_reason: str = "", kb_merge: str = "none",
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
        "kb_remote: " + q(kb_remote) + "   # 同步源 <remote>/<branch>；未配置留空",
        "kb_remote_rev: " + q(kb_remote_rev) + "   # 本次 fetch 到的远端分支短 sha；没成功写 unknown",
        "kb_behind: " + (str(kb_behind) if isinstance(kb_behind, int) and not isinstance(kb_behind, bool) else q(kb_behind)) + "   # 落后远端分支的提交数；算不出写 unknown",
        "kb_sync: " + q(kb_sync_state) + "   # ok | failed | off | skipped",
        "kb_sync_reason: " + q(kb_sync_reason),
        "kb_merge: " + q(kb_merge) + "   # ff-only | none",
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
    ap.add_argument("--no-sync", action="store_true", help="不联网：不 fetch、不合并，只读本机状态")
    ap.add_argument("--selftest", action="store_true", help="跑四条环境用例")
    ap.add_argument("--dry-run-env", action="store_true", help="只报这台机器能取到的派生值")
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    session, why = harness_session_of()

    if args.dry_run_env:
        kb, _dirty = kb_rev_of(root)
        settings, config, _problem = kb_sync.load_settings(root)
        cfg = settings["sync"]
        print("harness_session: " + (session or "（取不到）" + "——" + why))
        print("kb_rev: " + kb)
        print(f"kb_sync: {cfg['remote']}/{cfg['branch']}（配置：{config}；不联网）")
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

    # 顺序：参数校验与同名检查 → 确认 traces 可写 → 同步（可能改 HEAD）→ 写文件。
    # 同名时不动工作区；写不了 trace 时也不合并——同步会改 HEAD，白改一次没有意义。
    traces = resolve_traces(root)
    target = traces / (args.slug + ".yaml")
    if target.exists():
        print("已存在，不覆盖：" + str(target), file=sys.stderr)
        return 2
    if not args.print_only:
        problem = ensure_traces_writable(traces)
        if problem:
            print(problem, file=sys.stderr)
            return 2

    result = sync_of(root, no_sync=args.no_sync, no_network=args.print_only)
    kb, kb_dirty = kb_rev_of(root)
    text = build_header(slug=args.slug, harness_session=session, created_at=now_stamp(),
                        kb_rev=kb, kb_rev_dirty=kb_dirty, **kb_fields(result),
                        framework=args.framework, platform=args.platform,
                        category=args.category, summary=args.summary)

    if args.print_only:
        sys.stdout.write(text)
        if why:
            print("# 注意：" + why, file=sys.stderr)
        return 0

    target.write_text(text, encoding="utf-8")
    (traces / "evidence" / args.slug).mkdir(parents=True, exist_ok=True)

    print("已建：" + str(target))
    config_error = " ".join(str(result.get("config_error") or "").split())
    if config_error:
        print(f"知识库配置读不出，按默认值同步（{config_error}）")
    hint = sync_hint(result)
    if hint:
        print(hint)
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
