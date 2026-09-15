#!/usr/bin/env python3
"""export_trace.py —— 把一次诊断打包成「跨机交接包」（handoff package）。

## 为什么需要

诊断常常一台机器上做一半、更多材料在另一台机器上（典型：外网机器上路由与验证做完，
真正的大日志在内网）。原来的做法是把报告邮件发过去、内网重新起一单——能work，因为报告把
现场写得够全；但那条链路依赖"上家把该写的都写进了人读报告"，而机器需要的东西（当前步、
已排除的候选、等什么材料）在人读文本里读不回来。

## 包内布局 = `traces/` 的子集（**这条是硬约束，不是风格**）

    <sid>.yaml
    <sid>.report.md            （有则带）
    evidence/<sid>/**          （有则带）
    handoff/<sid>.yaml         ← 交接单（机器可读）
    handoff/<sid>.README.txt   ← 给人看的一页说明

于是"导入"退化成"解压落位"：`resume-diagnosis`、诊断面板、`trace_metrics.py` 全都零改动
就能看见这一单（它们只认这个布局；`traces/` 的 glob 是非递归的，所以 `handoff/`、`evidence/`
不会被误读成会话）。反过来说，**发明新布局就得改四处读取端**——那正是要避免的。

## 两个投影，同一份内容

* `.zip`  —— 含证据原件，走文件通道；收件侧解压即落位。
* `.md`   —— 单文件纯文本：简报 + 交接单 + trace 全文 + 报告全文 + 体积允许的证据原文。
  走只认文本的通道（邮件正文、IM、只放行文本的摆渡），不需要压缩包能过去。
  两者都由同一份源生成，不漂移；`.md` 里**显式列出没带进来的东西**（体积超限的、未内联的），
  否则接手方会以为证据全在——那是假装，不是交接。

用法：
  python3 scripts/export_trace.py <session_id> [--intent continue|verify|escalate] [--note "…"]
  python3 scripts/export_trace.py <session_id> --json          # 面板用（只吐 JSON）
  python3 scripts/export_trace.py --list                       # 列出可导出的会话

退出码：0 = 产出成功；2 = 找不到会话 / 参数不合法；3 = 写盘失败。
"""
import argparse
import errno
import json
import re
import socket
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from _stdio import pin_utf8_stdio
from _yaml import load_text
from exec_log_path import resolve_traces, main_checkout
from kb_rev import kb_rev

SCHEMA = "ascend-sleuth-handoff/1"
INTENTS = ("continue", "verify", "escalate")
INTENT_LABEL = {"continue": "继续定位", "verify": "复核结论", "escalate": "转上游"}

# `.md` 投影的定界标记：用 HTML 注释而不是围栏，因为报告与 trace 正文里本来就有 ``` 围栏。
MD_HEAD = "<!-- ascend-sleuth-handoff v1 -->"
MD_BEGIN = {k: f"<!-- BEGIN {k} -->" for k in ("MANIFEST", "TRACE", "REPORT")}
MD_END = {k: f"<!-- END {k} -->" for k in ("MANIFEST", "TRACE", "REPORT")}

# 源码引用：`src-code/<org>/<repo>/<ref>/<文件>[:行]`（缓存布局见 CLAUDE.md「源码不落库」）
SRC_RE = re.compile(r"src-code/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)(/[^\s:;,)\]}\"']+)?")


def human_bytes(n) -> str:
    if n is None:
        return "—"          # 交接单自身的字节数是自指值（写出前不知道多大）→ 如实显示未知
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024 or unit == "GB":
            return f"{f:.0f} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} GB"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def rel_to_traces(path: Path, traces_root: Path) -> str:
    """包内路径 = 相对 `traces/` 的 POSIX 路径（与 zip 内 arcname 同一口径）。"""
    return path.relative_to(traces_root).as_posix()


def normalize_ref(raw: str) -> str:
    """把 trace 里对证据文件的引用归一成"相对 traces/"的包内路径。

    trace 里合法写法是 `traces/evidence/<sid>/x.txt`（相对仓库根），也可能被写成
    绝对路径或带 `./`；统一剥掉到 `traces/` 之后的部分，才能和包内清单对齐。
    """
    s = str(raw or "").strip().replace("\\", "/")
    if not s:
        return ""
    m = re.search(r"(?:^|/)traces/(.+)$", s)
    return m.group(1) if m else s.lstrip("./")


def collect_evidence(traces_root: Path, sid: str):
    """→ [(包内相对路径, 绝对路径, 字节数)]，按路径排序（顺序稳定，便于比对）。"""
    base = traces_root / "evidence" / sid
    if not base.is_dir():
        return []
    out = []
    for p in sorted(base.rglob("*")):
        if p.is_file():
            out.append((rel_to_traces(p, traces_root), p, p.stat().st_size))
    return out


def referenced_paths(doc: dict) -> list:
    """trace 的 user 事件里 `evidence.files` 提到过、但包里可能没有的路径（按出现顺序去重）。"""
    seen, out = set(), []
    for ev in doc.get("trace") or []:
        if not isinstance(ev, dict):
            continue
        evd = ev.get("evidence")
        if not isinstance(evd, dict):
            continue
        files = evd.get("files")
        if isinstance(files, str):
            files = [files]
        for f in files or []:
            n = normalize_ref(f)
            if n and n not in seen:
                seen.add(n)
                out.append(n)
    return out


def extract_src_refs(*texts) -> list:
    """从 trace / 报告正文里抽出 `src-code/<org>/<repo>/<ref>/…` 引用。

    为什么值得抽：源码缓存是**本地件**（`src-code/` 平铺在主检出，gitignore），
    另台机器上没有；而"读了哪个文件的哪一行"常常是这次结论的承重墙。抽出来给接手方两件事：
    该补哪个版本的源码（一条 `src_fetch.py` 命令），以及这次到底读了哪些文件。
    """
    by_key = {}
    for text in texts:
        for m in SRC_RE.finditer(text or ""):
            org, repo, ref, rest = m.group(1), m.group(2), m.group(3), m.group(4) or ""
            key = f"{org}/{repo}@{ref}"
            item = by_key.setdefault(key, {"org": org, "repo": repo, "ref": ref, "files": []})
            if rest:
                item["files"].append(f"{org}/{repo}/{ref}{rest}")
    for item in by_key.values():
        # 同一个文件被引多次（多行号）时去重，保持首次出现顺序
        item["files"] = list(dict.fromkeys(item["files"]))
    return sorted(by_key.values(), key=lambda x: (x["org"], x["repo"], x["ref"]))


def local_src_cache(traces_root: Path, item: dict):
    """本地是否已有该版本源码缓存（缓存根在主检出，不在 traces 下）。"""
    root = main_checkout(traces_root.parent) or traces_root.parent
    d = root / "src-code" / item["org"] / item["repo"] / item["ref"]
    return d.is_dir()


def derive_needs(doc: dict) -> list:
    """接手方"该先问什么" = 上家留下的缺口，取 `evidence.missing`（新的在前）+ `last_action`。

    这条是从 `resume-diagnosis` 已有的行为反推的：它对"没命中 case"那一路本来就是按
    `evidence.missing` 追问现场材料。交接单把它机器可读地固化下来，接手方第一屏就能问对问题，
    而不是从"请复述一下问题"重新开始。
    """
    out = []
    for ev in reversed(doc.get("trace") or []):
        if not isinstance(ev, dict):
            continue
        evd = ev.get("evidence")
        if isinstance(evd, dict) and evd.get("missing"):
            out.append(str(evd["missing"]).strip())
    if doc.get("last_action"):
        out.append(str(doc["last_action"]).strip())
    seen, uniq = set(), []
    for s in out:
        s = re.sub(r"\s+", " ", s)
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq[:6]


def derive_intent(doc: dict, cli_intent: str):
    """交接意图：默认按 status 推，CLI 可覆盖（面板上是一个显式选择）。"""
    if cli_intent:
        return cli_intent, "cli"
    status = str(doc.get("status") or "")
    if status == "escalated":
        return "escalate", "derived"
    if status in ("resolved", "archived"):
        return "verify", "derived"
    return "continue", "derived"


def build_manifest(doc, sid, traces_root, args, included, omitted, report_rel, current_rev, src_refs):
    notes = []
    redaction_state = "none"
    if any(f["kind"] == "evidence" for f in included):
        redaction_state = "raw-evidence"
        notes.append("包内含原始现场证据文件（日志/配置/导出产物原样）——外发前按你们的数据通道规则处理。")
    if args.redacted:
        redaction_state = "redacted"
    if args.redaction_notes:
        notes.append(str(args.redaction_notes))

    trace_rev = str(doc.get("kb_rev") or "").strip()
    rev = trace_rev or current_rev
    rev_source = "trace" if trace_rev else "current-checkout"
    return {
        "schema": SCHEMA,
        "session_id": sid,
        "exported_at": now_iso(),
        "origin": {
            "host": socket.gethostname(),
            "cwd": str(traces_root.parent),
            "kb_rev": rev,
            "kb_rev_source": rev_source,
            "kb_dirty": kb_rev(traces_root.parent)[1] if rev_source == "current-checkout" else None,
        },
        "intent": args.intent,
        "intent_source": args.intent_source,
        "intent_note": args.note or "",
        "session": {
            "status": doc.get("status") or "unknown",
            "current_step": doc.get("current_step"),
            "summary": doc.get("summary") or "",
            "detected_framework": doc.get("detected_framework") or "",
            "detected_platform": doc.get("detected_platform") or "",
            "detected_category": doc.get("detected_category") or "",
            "active_case": doc.get("active_case") if doc.get("active_case") is not None else None,
            "excluded_cases": list(doc.get("excluded_cases") or []),
            "created_at": doc.get("created_at") or "",
            "updated_at": doc.get("updated_at") or "",
        },
        "needs": derive_needs(doc),
        "contents": {
            "files": [{"path": f["path"], "bytes": f["bytes"], "kind": f["kind"]} for f in included],
            "total_bytes": sum(f["bytes"] for f in included if f["bytes"]),
            "omitted": omitted,
            "report_file": report_rel,
        },
        "src_refs": src_refs,
        "redaction": {"state": redaction_state, "notes": notes},
    }


README_TXT = """这是一份 ascend-sleuth 诊断会话的「交接包」——把一台上做到一半的诊断，交到另一台机器上继续。

包内布局就是接收侧 `traces/` 的子集（相对 traces/）：

  {sid}.yaml            本次诊断的 trace（状态 / 已排除候选 / 对话轨迹 / 证据引用）
  {report_line}
  evidence/{sid}/      证据原件
  handoff/{sid}.yaml   交接单（机器可读：来源主机、知识库版本、交接意图、待补材料、未纳入清单）

在**接收侧**（要接着定位的那台机器）执行：

  python3 scripts/import_trace.py <这个包 | 包内的 handoff-{sid}.md>

它会校验、落到 traces/ 下、比对知识库版本，并打印一屏"这单是什么、停在哪、要什么材料"。
之后按提示续接：`/skill:resume-diagnosis`。

注意：{omitted_line}
"""


def decide_inlining(evidence_entries, inline_limit, total_limit):
    """先决定"哪些证据原文进 md"，再生成 md——顺序反了的话，md 里内嵌的交接单
    会缺 `projection.md_not_inlined`（那份清单是生成 md 时才填的），于是接收侧把
    "本来就没打算带的文件"读成"传输丢件"，去追一个不存在的包。"""
    inline, skipped, total = [], [], 0
    for rel, path, size in evidence_entries:
        if inline_limit and size <= inline_limit and (not total_limit or total + size <= total_limit):
            inline.append((rel, path, size))
            total += size
            continue
        why = (f"超过内联上限（{human_bytes(size)}）" if inline_limit and size > inline_limit
               else f"累计内联已达上限（{human_bytes(total_limit)}）" if total_limit else "未内联")
        skipped.append({"path": rel, "reason": why})
    return inline, skipped


def md_projection(sid, manifest, trace_text, report_text, inline_entries, not_inlined):
    """单文件纯文本投影。返回 (markdown 文本, 读取失败的清单)。"""
    read_failed = []
    lines = [MD_HEAD, f"# 交接包 · {sid}", ""]
    lines += [
        f"- 交接意图：{INTENT_LABEL.get(manifest['intent'], manifest['intent'])}"
        f"（来源：{'命令行指定' if manifest['intent_source'] == 'cli' else '按 status 推导'}）",
        f"- 状态：{manifest['session']['status']} · 当前步 {manifest['session']['current_step']}"
        f" · 框架 {manifest['session']['detected_framework'] or '未记'}"
        f" · 类别 {manifest['session']['detected_category'] or '未记'}",
        f"- 来源：{manifest['origin']['host']} · 知识库版本 {manifest['origin']['kb_rev']}"
        f"（{manifest['origin']['kb_rev_source']}）",
        f"- 导出时间：{manifest['exported_at']}",
        "",
    ]
    if manifest["session"]["summary"]:
        lines += ["## 问题背景", "", str(manifest["session"]["summary"]).strip(), ""]
    if manifest["needs"]:
        lines += ["## 上家留下的待补材料（接手先问这几条）", ""]
        lines += [f"{i}. {s}" for i, s in enumerate(manifest["needs"], 1)] + [""]
    if manifest["intent_note"]:
        lines += ["## 交接说明（人手写）", "", str(manifest["intent_note"]).strip(), ""]
    lines += [
        "## 包内清单", "",
        f"共 {len(manifest['contents']['files'])} 个文件、{human_bytes(manifest['contents']['total_bytes'])}；"
        f"未纳入 {len(manifest['contents']['omitted'])} 个。",
        "",
    ]
    for f in manifest["contents"]["files"]:
        lines.append(f"- `{f['path']}`（{f['kind']}，{human_bytes(f['bytes'])}）")
    for f in manifest["contents"]["omitted"]:
        lines.append(f"- **未纳入** `{f['path']}`（{human_bytes(f['bytes'])}）—— {f['reason']}")
    lines += ["", "> 未纳入的文件不在本文件里，也不在 zip 之外；需要它们时向上家索取。", ""]
    if manifest["src_refs"]:
        lines += ["## 这次读了哪些源码（本地缓存，接收侧需自行取版本）", ""]
        for s in manifest["src_refs"]:
            cached = "（接收侧已有该版本缓存）" if s.get("cached_locally") else "（接收侧未见该版本缓存）"
            lines.append(f"- `{s['org']}/{s['repo']}@{s['ref']}`{cached}"
                         f"：{len(s['files'])} 个文件被引用")
        lines += ["", "取源码：`python3 scripts/src_fetch.py <org>/<repo> --ref <ref>`", ""]

    lines += [MD_BEGIN["MANIFEST"], "```yaml", yaml.safe_dump(
        manifest, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip(), "```",
        MD_END["MANIFEST"], ""]
    lines += [MD_BEGIN["TRACE"], "```yaml", trace_text.rstrip(), "```", MD_END["TRACE"], ""]
    if report_text:
        lines += [MD_BEGIN["REPORT"], report_text.rstrip(), MD_END["REPORT"], ""]

    lines += ["## 证据原文（体积允许的部分）", ""]
    for rel, path, size in inline_entries:
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            read_failed.append({"path": rel, "reason": f"读失败：{e}"})
            continue
        lines += [f'<!-- BEGIN EVIDENCE path="{rel}" bytes="{size}" -->', "```text",
                  body.rstrip(), "```", "<!-- END EVIDENCE -->", ""]
    for row in not_inlined:
        lines += [f"- `{row['path']}` 未内联：{row['reason']}"
                  f"—— 需要原文请索取 zip 包（`handoff-{sid}.zip`）", ""]
    return "\n".join(lines).rstrip() + "\n", read_failed


def list_sessions(traces_root: Path):
    out = []
    for p in sorted(traces_root.glob("*.yaml")):
        try:
            doc = load_text(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        out.append({
            "session_id": str(doc.get("session_id") or p.stem),
            "file": p.name,
            "status": str(doc.get("status") or "unknown"),
            "updated_at": str(doc.get("updated_at") or ""),
            "summary": re.sub(r"\s+", " ", str(doc.get("summary") or ""))[:80],
        })
    return out


def write_hint(e):
    """写盘失败时补一句方向。

    为什么值得单列：`[Errno 1] Operation not permitted` 在文件权限与 ACL 都正常时读起来毫无线索
    （实测：面板子进程被沙箱拒写，`ls -lOe` 查下来一切正常）。这类拒绝多半来自**跑脚本的子进程所处的
    沙箱**——写权限的根不是这个检出时，写进去就被拒。命令行直接跑通常不受此限，所以两句话就够读者分辨。
    """
    if getattr(e, "errno", None) in (errno.EPERM, errno.EACCES):
        return ("——写入被拒。文件权限/ACL 正常时多半是**沙箱**：跑这个脚本的子进程若在受限环境里，"
                "写权限的根可能不是本检出（面板侧要显式给沙箱策略；命令行直接跑不受此限）")
    return ""


def fail(msg, code=2, as_json=False):
    if as_json:
        print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    else:
        print(f"export_trace: {msg}", file=sys.stderr)
        print("✗ 未产出交接包", file=sys.stderr)
    return code


def main() -> int:
    ap = argparse.ArgumentParser(description="把一次诊断打包成跨机交接包（zip + 单文件 md）")
    ap.add_argument("session", nargs="?", help="session_id（或 traces/<session>.yaml 的路径）")
    ap.add_argument("--list", action="store_true", help="列出可导出的会话")
    ap.add_argument("--intent", choices=INTENTS, default=None,
                    help="交接意图（默认按 status 推导：进行中→继续定位、已转上游→转上游、已结→复核结论）")
    ap.add_argument("--note", default="", help="写进交接单的一句话（为什么要带出去、接手方优先看什么）")
    ap.add_argument("--out", default=None, help="产出目录（默认 <traces>/exports/）")
    ap.add_argument("--traces-root", default=None, help="traces 目录（默认：主检出那一份，见 shared_dir.py）")
    ap.add_argument("--root", default=None, help="仓库根目录（默认：本脚本上两级）")
    ap.add_argument("--max-file-mb", type=float, default=20.0, help="单个证据文件上限（超过则不纳入并如实列出）")
    ap.add_argument("--max-total-mb", type=float, default=200.0, help="证据总量上限（超过则不纳入并如实列出）")
    ap.add_argument("--include-all", action="store_true", help="忽略体积上限（自担通道风险）")
    ap.add_argument("--md-inline-kb", type=float, default=256.0, help="md 投影里单个证据文件的原文内联上限")
    ap.add_argument("--md-total-mb", type=float, default=8.0, help="md 投影里证据原文的内联总量上限")
    ap.add_argument("--redacted", action="store_true", help="声明包内证据已脱敏（交接单照写，不代替实际脱敏）")
    ap.add_argument("--redaction-notes", default="", help="脱敏说明")
    ap.add_argument("--no-zip", action="store_true")
    ap.add_argument("--no-md", action="store_true")
    ap.add_argument("--json", action="store_true", help="只吐 JSON（面板/脚本用）")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    traces_root = Path(args.traces_root).resolve() if args.traces_root else resolve_traces(root)

    if args.list:
        rows = list_sessions(traces_root)
        if args.json:
            print(json.dumps({"ok": True, "traces_root": str(traces_root), "sessions": rows},
                             ensure_ascii=False))
            return 0
        print(f"traces 目录：{traces_root}")
        if not rows:
            print("（没有可导出的会话）")
            return 0
        for r in rows:
            print(f"  {r['session_id']:<44} {r['status']:<12} {r['updated_at']}  {r['summary']}")
        return 0

    if not args.session:
        return fail("缺 session_id（`--list` 看可选会话）", 2, args.json)

    # 会话定位。两种入参：session_id，或一个 trace 文件路径（面板传的就是后者：
    # `traces/<条目名>.yaml`，相对工作目录）。
    #
    # 路径入参必须**两处都找**：相对路径先按进程 cwd 解析（面板就是这么调的：workdir = 检出），
    # 找不到再按 traces 根解析——`traces/x.yaml` 在 worktree 里跑时 cwd 下没有 traces/，
    # 而 traces 根那一份是共享的主检出。只认 cwd 会让这两种情况以 `x.yaml.yaml` 这种看不懂的
    # 报错收场（实测踩过）。
    # 警告攒在开头：报告读失败之类的早发现的问题也要能记进来（原先 warnings 在体积策略段才建，
    # 于是早先那一段只能干看着）
    warnings = []

    trace_arg = str(args.session)
    trace_path = None
    if trace_arg.endswith(".yaml"):
        p_arg = Path(trace_arg)
        cands = []
        if args.traces_root:
            # 显式给了 traces 根 → 它说了算：只认根下那一份，避免"读到的其实是另一个检出"
            cands.append(traces_root / p_arg.name)
        else:
            cands.append(p_arg.resolve() if p_arg.is_absolute() else (Path.cwd() / p_arg))
            cands.append(traces_root / p_arg.name)
        for c in cands:
            if c.is_file():
                trace_path = c
                break
        if trace_path is None:
            tried = "、".join(str(c) for c in cands)
            return fail(f"找不到这份 trace（试过：{tried}）", 2, args.json)
        if not args.traces_root:
            traces_root = trace_path.parent          # 没指定根时，以文件所在目录为准
        sid = trace_path.stem
    else:
        sid = trace_arg
        trace_path = traces_root / f"{sid}.yaml"
        if not trace_path.is_file():
            rows = list_sessions(traces_root)
            hint = "；".join(r["session_id"] for r in rows[:8]) or "（traces/ 里没有会话）"
            return fail(f"{traces_root} 下没有 {sid}.yaml。现有会话：{hint}", 2, args.json)

    try:
        trace_text = trace_path.read_text(encoding="utf-8")
        doc = load_text(trace_text)
    except Exception as e:
        return fail(f"读/解析 {trace_path.name} 失败：{e}", 2, args.json)
    if not isinstance(doc, dict):
        return fail(f"{trace_path.name} 不是 YAML 映射（顶层解析不出来）", 2, args.json)

    # session_id 才是这一单的身份；**文件名在历史单里可能与它不同**（面板读的也是文件名：
    # 它按 `traces/*.yaml` 的条目名传过来，而 trace 顶层的 session_id 是另一件事）。
    # 包内布局的契约是 `<session_id>.yaml`，所以以 session_id 为准，并把这次差异说出来——
    # 不说的话，接收侧会看到"包里的文件名与 trace 里的 session_id 不一致"这种无法判断的形态。
    sid_note = None
    file_sid = sid
    real_sid = str(doc.get("session_id") or "").strip()
    if real_sid and real_sid != sid:
        sid_note = (f"trace 顶层的 session_id 是 {real_sid}，与文件名 {sid}.yaml 不同——"
                    f"包按 session_id 命名（包内布局的契约是 <session_id>.yaml）")
        sid = real_sid

    # 报告：优先顶层 report_file，退到同名规则（与面板 reportFileOf 同一口径）
    report_rel, report_text, report_src = None, "", None
    rep_name = str(doc.get("report_file") or "").strip()
    if not rep_name:
        for ev in reversed(doc.get("trace") or []):
            if isinstance(ev, dict) and ev.get("report_file"):
                rep_name = str(ev["report_file"]).strip()
                break
    cand = []
    if rep_name:
        m = re.search(r"(?:^|/)traces/(.+)$", rep_name.replace("\\", "/"))
        cand.append((m.group(1) if m else rep_name.replace("\\", "/").lstrip("./"), "trace"))
    cand.append((f"{sid}.report.md", "name"))
    for name, src in cand:
        rp = traces_root / name
        if rp.is_file():
            try:
                report_text = rp.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                # 读不到就当"这次没带报告"：若把 report_rel 记下而正文为空，包内清单会写上一个
                # 根本没落盘的文件，接收侧于是报"清单里有、包里没有"——自相矛盾的包
                warnings.append(f"报告 {name} 读失败（{e}），本次未纳入交接包")
                continue
            report_rel, report_src = name, src
            break

    intent, intent_src = derive_intent(doc, args.intent)
    args.intent, args.intent_source = intent, intent_src

    # ---- 收集内容 + 体积策略 ----
    included, omitted = [], []

    # `rel` 可显式给：trace 本体的**源文件名可能与包内名不同**（见上面的 sid 归一），
    # 清单必须写包内名——写源路径会让接收侧把"改名"读成"丢件"（实测踩过）。
    def add(path: Path, kind: str, size: int, rel=None):
        included.append({"path": rel or rel_to_traces(path, traces_root), "bytes": size, "kind": kind})

    add(trace_path, "trace", trace_path.stat().st_size, rel=f"{sid}.yaml")
    if report_rel:
        rp = traces_root / report_rel
        add(rp, "report", rp.stat().st_size)
    elif rep_name:
        warnings.append(f"trace 记了报告 {rep_name}，但 traces/ 下找不到该文件——报告未纳入交接包")

    ev = collect_evidence(traces_root, sid)
    if file_sid != sid:
        # 证据目录按 session_id 命名（diagnose 的约定），但历史单也可能按文件名建——两个都收，
        # 宁可多带一个文件，也不要让接手方以为证据没打包过来
        ev = ev + [x for x in collect_evidence(traces_root, file_sid) if x[0] not in {y[0] for y in ev}]
    file_cap = None if args.include_all else int(args.max_file_mb * 1024 * 1024)
    total_cap = None if args.include_all else int(args.max_total_mb * 1024 * 1024)
    running = 0
    for rel, path, size in ev:
        if file_cap and size > file_cap:
            omitted.append({"path": rel, "bytes": size,
                            "reason": f"超过单文件上限 {human_bytes(file_cap)}"})
            continue
        if total_cap and running + size > total_cap:
            omitted.append({"path": rel, "bytes": size,
                            "reason": f"证据总量超过上限 {human_bytes(total_cap)}"})
            continue
        running += size
        add(path, "evidence", size)
    if sid_note:
        warnings.append(sid_note)
    if omitted:
        warnings.append(f"{len(omitted)} 个证据文件未纳入（体积上限）——接手方若要这些原文，"
                        f"需走 zip 之外的方式索取（交接单与 md 里都列了清单）")

    # ---- 源码引用 ----
    src_refs = extract_src_refs(trace_text, report_text)
    for s in src_refs:
        s["cached_locally"] = local_src_cache(traces_root, s)
    if src_refs and not all(s["cached_locally"] for s in src_refs):
        warnings.append(f"{sum(1 for s in src_refs if not s['cached_locally'])} 个源码版本在本地没有缓存——"
                        f"交接单里记了 repo+ref，接收侧用 src_fetch.py 取即可（内网不可达该源时如实说明）")

    current_rev = kb_rev(traces_root.parent)[0]
    if not str(doc.get("kb_rev") or "").strip():
        warnings.append("trace 缺 kb_rev 字段（会话开单时应写）——交接单按当前检出 HEAD 推断，"
                        "接收侧比对仅供参考")

    # ---- 产出目录 + 交接单 ----
    out_dir = Path(args.out).resolve() if args.out else (traces_root / "exports")
    tree = out_dir / sid
    try:
        tree.mkdir(parents=True, exist_ok=True)
        (tree / "handoff").mkdir(exist_ok=True)
    except OSError as e:
        return fail(f"无法创建产出目录 {tree}：{e}{write_hint(e)}", 3, args.json)

    manifest = build_manifest(doc, sid, traces_root, args, included, omitted, report_rel,
                              current_rev, src_refs)
    manifest_path = tree / "handoff" / f"{sid}.yaml"
    readme_path = tree / "handoff" / f"{sid}.README.txt"
    # 交接单自己也进 contents（接手方要能校验"这包里有什么"），但要先算 total 再加自己
    # 交接单自身的字节数是自指值（写它时还不知道多大）——如实标 null，不填一个会被后续校验
    # 判成"包坏了"的假数字；接收侧的完整性校验对这条不做字节比对。
    manifest["contents"]["files"].append(
        {"path": f"handoff/{sid}.yaml", "bytes": None, "kind": "manifest"})
    manifest["contents"]["files"].append(
        {"path": f"handoff/{sid}.README.txt", "bytes": 0, "kind": "readme"})
    manifest["warnings"] = warnings
    manifest["projection"] = {
        "zip": None if args.no_zip else f"handoff-{sid}.zip",
        "md": None if args.no_md else f"handoff-{sid}.md",
        "md_not_inlined": [],
    }

    # ---- 落盘：包内树 ----
    try:
        (tree / f"{sid}.yaml").write_text(trace_text, encoding="utf-8")
        if report_rel and report_text:
            # 报告名保持原名（接手侧按 report_file 找它）；同名不同后缀是契约
            (tree / report_rel).write_text(report_text, encoding="utf-8")
        for rel, path, size in ev:
            if any(f["path"] == rel for f in included):
                dst = tree / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(path.read_bytes())
        omitted_line = ("包内有 " + str(len(omitted)) + " 个证据文件因体积上限未纳入，清单见交接单的"
                        " contents.omitted。") if omitted else "包内证据按现场原件原样携带。"
        readme_path.write_text(README_TXT.format(
            sid=sid,
            report_line=f"{(report_rel or sid + '.report.md')}      人读定位报告" if report_rel
                        else "（本次没有产出人读报告）",
            omitted_line=omitted_line), encoding="utf-8")
        # 交接单最后写：这时 contents 才定稿（含 manifest/readme 两项与真实字节数）
        for f in manifest["contents"]["files"]:
            if f["kind"] == "readme":
                f["bytes"] = (tree / f["path"]).stat().st_size if (tree / f["path"]).exists() else 0
        m_text = ("# 交接单（export_trace.py 生成，导入侧 import_trace.py 读）\n"
                  "# 字段口径见 docs/handoff.md\n"
                  + yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False,
                                   default_flow_style=False))
        manifest_path.write_text(m_text, encoding="utf-8")
        manifest["contents"]["total_bytes"] = sum(
            f["bytes"] or 0 for f in manifest["contents"]["files"])
    except OSError as e:
        return fail(f"写交接包失败（{tree}）：{e}{write_hint(e)}", 3, args.json)

    # ---- 投影一：zip（解压即落位到 traces/）----
    zip_path = None
    if not args.no_zip:
        zip_path = out_dir / f"handoff-{sid}.zip"
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
                for p in sorted(tree.rglob("*")):
                    if p.is_file():
                        z.write(p, p.relative_to(tree).as_posix())
        except OSError as e:
            return fail(f"写 zip 失败（{zip_path}）：{e}{write_hint(e)}", 3, args.json)

    # ---- 投影二：单文件 md（走文本通道）----
    md_path, not_inlined = None, []
    if not args.no_md:
        md_path = out_dir / f"handoff-{sid}.md"
        inline_entries, md_skipped = decide_inlining(
            ev, int(args.md_inline_kb * 1024), int(args.md_total_mb * 1024 * 1024))
        # 先填进交接单，再生成 md：md 里内嵌的那份交接单要带上这份清单（见 decide_inlining 的说明）
        manifest["projection"]["md_not_inlined"] = md_skipped
        md_text, read_failed = md_projection(
            sid, manifest, trace_text, report_text, inline_entries, md_skipped)
        not_inlined = md_skipped + read_failed
        try:
            md_path.write_text(md_text, encoding="utf-8")
        except OSError as e:
            return fail(f"写 md 失败（{md_path}）：{e}{write_hint(e)}", 3, args.json)
        manifest["projection"]["md_not_inlined"] = not_inlined
        # 回写交接单里的投影事实（谁在哪个通道收到了哪份），一次导出只动自己这一份
        try:
            manifest_path.write_text(
                "# 交接单（export_trace.py 生成，导入侧 import_trace.py 读）\n"
                "# 字段口径见 docs/handoff.md\n"
                + yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False,
                                 default_flow_style=False), encoding="utf-8")
        except OSError:
            pass

    result = {
        "ok": True,
        "session_id": sid,
        "intent": manifest["intent"],
        "intent_source": manifest["intent_source"],
        "traces_root": str(traces_root),
        "dir": str(out_dir),
        "tree": str(tree),
        "manifest": str(manifest_path),
        "zip": str(zip_path) if zip_path else None,
        "zip_bytes": zip_path.stat().st_size if zip_path else 0,
        "md": str(md_path) if md_path else None,
        "md_bytes": md_path.stat().st_size if md_path else 0,
        "files": len(manifest["contents"]["files"]),
        "total_bytes": manifest["contents"]["total_bytes"],
        "omitted": omitted,
        "not_inlined": not_inlined,
        "src_refs": src_refs,
        "needs": manifest["needs"],
        "redaction": manifest["redaction"],
        "warnings": warnings,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0

    print(f"交接包已产出：{sid}（意图：{INTENT_LABEL.get(manifest['intent'])}"
          f"，{'命令行指定' if manifest['intent_source'] == 'cli' else '按 status 推导'}）")
    print(f"  包内树  {tree}")
    if zip_path:
        print(f"  zip     {zip_path}（{human_bytes(result['zip_bytes'])}）")
    if md_path:
        print(f"  md      {md_path}（{human_bytes(result['md_bytes'])}）")
    print(f"  内容    {result['files']} 个文件 / {human_bytes(result['total_bytes'])}"
          + (f"；未纳入 {len(omitted)} 个（体积上限）" if omitted else ""))
    if report_rel:
        print(f"  报告    {report_rel}（来源：{'trace 的 report_file' if report_src == 'trace' else '同名规则'}）")
    else:
        print("  报告    无（这单未产出人读报告）")
    if src_refs:
        miss = [s for s in src_refs if not s["cached_locally"]]
        print(f"  源码    {len(src_refs)} 个版本被引用"
              + (f"，其中 {len(miss)} 个接收侧需自行取" if miss else "（本地都有缓存）"))
    if manifest["needs"]:
        print("  待补材料（接手方先问这几条）：")
        for s in manifest["needs"]:
            print(f"    - {s}")
    if manifest["redaction"]["state"] == "raw-evidence":
        print("  ⚠ 包内含原始现场证据——外发前按你们的数据通道规则处理（面板/交接单里只标注，不代替脱敏）")
    for w in warnings:
        print(f"  · {w}")
    print("\n接收侧一条命令接手：")
    print(f"  python3 scripts/import_trace.py <{zip_path.name if zip_path else '包目录'}"
          f"{' 或 ' + md_path.name if md_path else ''}>")
    return 0


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
