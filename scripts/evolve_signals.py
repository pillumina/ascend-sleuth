#!/usr/bin/env python3
"""evolve_signals.py —— 演进信号记录：收尾观察的仓库内记录 + 导出成 issue/MR 文本

## 为什么需要

`signal-only` 部署不产 EV 卡；`maintainer` 也先把观察落成信号，再由分诊决定是否提升为
RSI。卡号按检出递增，两个仓各产各的必然重号。但"不产卡"不等于
"不记信号"：信号只留在会话里会随对话消散，只落在 exec-log 里又进不了版本库（那是
`.gitignore` 的运行时件，按克隆各一份，跨人不聚合）。两头都不构成交接。

本脚本把信号写成**主检出里的文件**：`proposals/signals/<部署>-<哈希>.yaml`，一条信号一个文件，
可 review、可 diff，由周批 PR 带上。上游维护者拿这批文件分诊；需要时再产卡；`export` 把它们
渲染成一段可粘贴的 issue / MR 描述。

## 为什么用内容哈希而不是序号

序号在本地递增，两个部署各产各的必然撞号（fork 不产卡的原因就是这个）。哈希取
`sha256(signal | target_component | evidence)` 的前 8 位：同样的信号重复出现得到同一个文件名，
天然去重，只把 `occurrences` 与 `last_seen` 往上加。不做模糊匹配——证据改写了就是另一条信号，
这比静默合并更诚实。

## 用法

    python3 scripts/evolve_signals.py add --signal T10 \
        --target skills/evolve-check/SKILL.md \
        --evidence "收尾口径与面板读法不一致" \
        --trajectory "products/VLLM-ASC-123(submitted)" \
        --suggested "让收尾原因串与面板解析同源"
    python3 scripts/evolve_signals.py list [--json]
    python3 scripts/evolve_signals.py export [--since 2026-10-01] [--title "..."] [--out issue.md]

退出码：0 正常；2 参数或文件写坏（信号文件解析失败）。
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

from exec_log_path import main_checkout
from _cli import main_entry

SIGNALS_REL = Path("proposals") / "signals"

_SAFE = re.compile(r"[^0-9A-Za-z._-]+")


def repo_root(start: Path = None) -> Path:
    """当前检出的 git 顶层（信号文件落哪个目录见 `signals_dir`）。"""
    start = Path(start or Path.cwd())
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                           text=True, cwd=str(start), encoding="utf-8", errors="replace")
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    except Exception:
        pass
    return Path(__file__).resolve().parents[1]


def deployment_of(root: Path) -> str:
    """部署标识：与指标侧同一口径（环境变量优先，其次主检出目录名）。"""
    try:
        from entry_activity import deployment
        return deployment(root)
    except Exception:
        return Path(main_checkout(Path(root)) or root).resolve().name


def signal_id(signal: str, target: str, evidence: str) -> str:
    key = "|".join((signal.strip(), target.strip(), evidence.strip()))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def signals_dir(root: Path, local: bool = False) -> Path:
    """信号落 **主检出**（同一克隆的共享侧），不是当前 worktree。

    信号不随修复 PR 入库，由周批统一收进它的 PR；写在当前检出会让主检出里跑出来的
    信号变成任何 worktree 都看不见的孤儿。`local=True` 读当前检出——PR 里校验本分支
    带的信号文件时用（主检出那一份可能已被 sweep 归档）。无 git 时退回 root。
    """
    return (Path(root) if local else Path(main_checkout(Path(root)) or root)) / SIGNALS_REL


def pending(root: Path) -> list:
    """主检出里还没进 git 的信号文件（按文件名排序）；周批要收的就是这些。"""
    main = Path(main_checkout(Path(root)) or root)
    d = signals_dir(root)
    if not d.is_dir():
        return []
    try:
        r = subprocess.run(["git", "-C", str(main), "ls-files", "--", str(SIGNALS_REL)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        tracked = {Path(x).name for x in r.stdout.splitlines() if x.strip()} if r.returncode == 0 else set()
    except Exception:
        tracked = set()
    return [p for p in sorted(d.glob("*.yaml")) if p.name not in tracked]


def sweep(root: Path, into: Path) -> list:
    """把主检出里未入库的信号复制进 `into` 的 `proposals/signals/`，原件移进 `.swept/`。

    移走原件是必须的：留在主检出会在周批 PR 合入时被 git 拦下
    （untracked working tree files would be overwritten by merge），且 pending 永不空。
    `.swept/` 是 gitignored 的本地归档，PR 被丢弃时可手工取回。
    """
    src_dir = signals_dir(root)
    dst = Path(into) / SIGNALS_REL
    if dst.resolve() == src_dir.resolve():
        return []          # 目标就是主检出本身：没有可收的
    archive = src_dir / ".swept"
    written = []
    for p in pending(root):
        dst.mkdir(parents=True, exist_ok=True)
        target = dst / p.name
        if not target.exists() or target.read_bytes() != p.read_bytes():
            target.write_bytes(p.read_bytes())
            written.append(target)
        archive.mkdir(parents=True, exist_ok=True)
        p.replace(archive / p.name)
    return written


def load(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict) or not doc.get("id"):
        raise ValueError(f"{path} 不是信号文件（缺 id）")
    return doc


def add(root: Path, *, signal: str, target: str, evidence: str, trajectory,
        suggested: str = "", source: str = "evolve-check", session: str = "",
        signal_text: str = "") -> dict:
    """写一条信号；同一 (signal, target, evidence) 重复出现只累加次数。"""
    d = signals_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    dep = deployment_of(root)
    sid = signal_id(signal, target, evidence)
    path = d / f"{_SAFE.sub('-', dep)}-{sid}.yaml"
    now = _now()
    if path.is_file():
        doc = load(path)
        doc["occurrences"] = int(doc.get("occurrences") or 1) + 1
        doc["last_seen"] = now
        if trajectory:
            for t in trajectory:
                if t not in (doc.get("trajectory") or []):
                    doc.setdefault("trajectory", []).append(t)
    else:
        doc = {
            "id": sid,
            "status": "new",
            "signal": signal,
            "signal_text": signal_text,
            "target_component": target,
            "evidence": evidence,
            "suggested_action": suggested,
            "source_skill": source,
            "session": session,
            "deployment": dep,
            "first_seen": now,
            "last_seen": now,
            "occurrences": 1,
            "trajectory": list(trajectory or []),
        }
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"path": path, "doc": doc}


def collect(root: Path, local: bool = False):
    d = signals_dir(root, local)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.yaml")):
        try:
            out.append((p, load(p)))
        except Exception as e:  # 坏文件不静默丢：调用方要看得见
            raise ValueError(f"{p} 解析失败：{e}") from e
    return out


STATUSES = ("new", "triaged", "promoted", "dropped")


def find(root: Path, key: str, local: bool = False):
    """按文件名、id 或路径找一个信号文件（找不到返回 None）。"""
    key = str(key).strip()
    d = signals_dir(root, local)
    if not d.is_dir():
        return None
    for p in sorted(d.glob("*.yaml")):
        if key in (p.name, p.stem, p.stem.split("-")[-1]) or key == str(p):
            return p
        try:
            if str(load(p).get("id")) == key:
                return p
        except Exception:
            continue
    return None


def mark(root: Path, key: str, status: str, note: str = "") -> Path:
    """推进一条信号的生命周期（new → triaged → promoted / dropped）。"""
    if status not in STATUSES:
        raise ValueError(f"status 必须是 {list(STATUSES)} 之一")
    p = find(root, key)
    if p is None:
        raise ValueError(f"找不到信号：{key}")
    doc = load(p)
    doc["status"] = status
    if note:
        doc["status_note"] = note
    doc["status_at"] = _now()
    p.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def render_md(items, title: str = "") -> str:
    if not items:
        return ""
    head = title or f"演进信号批次：{items[0][1].get('deployment', '')}，{len(items)} 条"
    lines = [f"# {head}", "",
             "来源：`proposals/signals/`（收尾观察的仓库内记录，一条信号一个文件）。",
             "产卡与验证由上游维护者执行；本批只提供信号、证据与出处。", ""]
    for i, (_, doc) in enumerate(items, 1):
        lines.append(f"## {i}. [{doc.get('signal') or '—'}] {doc.get('signal_text') or ''}".rstrip())
        lines.append("")
        lines.append(f"- 组件：`{doc.get('target_component') or '—'}`")
        lines.append(f"- 证据：{doc.get('evidence') or '—'}")
        if doc.get("suggested_action"):
            lines.append(f"- 建议：{doc['suggested_action']}")
        traj = doc.get("trajectory") or []
        if traj:
            lines.append("- 出处：" + "；".join(f"`{t}`" for t in traj))
        lines.append(f"- 状态：{doc.get('status') or 'new'}；记录：{doc.get('occurrences', 1)} 次，首次 {doc.get('first_seen', '—')}，"
                     f"最近 {doc.get('last_seen', '—')}，来源 skill `{doc.get('source_skill', '—')}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="演进信号记录：写、列、导出")
    ap.add_argument("--root", type=Path, default=None, help="仓库根（默认当前检出顶层）")
    ap.add_argument("--local", action="store_true",
                    help="读写当前检出的 proposals/signals（PR 自检用；默认读写主检出）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="写一条信号（同内容重复写只累加次数）")
    a.add_argument("--signal", required=True, help="信号编号或自由文本（如 T10）")
    a.add_argument("--signal-text", default="", help="信号的中文含义")
    a.add_argument("--target", required=True, help="要改的组件（skill 路径 / 脚本名 / 组件名）")
    a.add_argument("--evidence", required=True, help="一句话证据（不含客户原文）")
    a.add_argument("--trajectory", action="append", default=[], help="出处：产出 id / trace / replay 结果，可重复")
    a.add_argument("--suggested", default="", help="建议动作（一句话）")
    a.add_argument("--source", default="evolve-check", help="来源 skill")
    a.add_argument("--session", default="", help="会话 id（如有）")

    m = sub.add_parser("mark", help="推进信号生命周期（new → triaged → promoted / dropped）")
    m.add_argument("key", help="文件名、id 或路径")
    m.add_argument("--status", required=True, choices=list(STATUSES), help="目标状态")
    m.add_argument("--note", default="", help="一句话说明（为什么丢 / 为什么提升）")

    sub.add_parser("list", help="列出记录里的信号")
    sub.add_parser("pending", help="列出主检出里还没进 git 的信号（周批收件清单）")
    sw = sub.add_parser("sweep", help="把主检出里未入库的信号复制进本检出（周批提交用）")
    sw.add_argument("--into", type=Path, default=Path("."), help="复制到哪个检出（默认当前检出）")
    sub.add_parser("export", help="导出成可粘贴的 issue / MR 描述")

    for name in ("list", "export"):
        p = sub.choices[name]
        p.add_argument("--json", action="store_true", help="机器读")

    e = sub.choices["export"]
    e.add_argument("--since", default="", help="只要 first_seen >= 该日期（YYYY-MM-DD）")
    e.add_argument("--title", default="", help="覆盖标题")
    e.add_argument("--out", type=Path, default=None, help="写入文件（默认打到 stdout）")
    e.add_argument("--status", nargs="*", default=None,
                   help=f"只要这些状态（默认除 dropped）：{' '.join(STATUSES)}")

    args = ap.parse_args(argv)
    root = (args.root or repo_root()).resolve()

    if args.cmd == "add":
        r = add(root, signal=args.signal, target=args.target, evidence=args.evidence,
                trajectory=args.trajectory, suggested=args.suggested, source=args.source,
                session=args.session, signal_text=args.signal_text, local=args.local)
        print(f"{r['path']}（{r['doc']['occurrences']} 次）")
        return 0

    if args.cmd == "mark":
        try:
            p = mark(root, args.key, args.status, args.note)
        except ValueError as e:
            print(f"✗ {e}", file=sys.stderr)
            return 2
        print(f"{p.name} → {args.status}")
        return 0

    if args.cmd == "pending":
        files = pending(root)
        for p in files:
            print(p)
        if not files:
            print(f"无未入库信号（{signals_dir(root)}）")
        return 0

    if args.cmd == "sweep":
        if (Path(args.into).resolve() / SIGNALS_REL).resolve() == signals_dir(root).resolve():
            print("目标是主检出本身，未收")
            return 0
        copied = sweep(root, args.into)
        for p in copied:
            print(p)
        print(f"收进 {len(copied)} 条（目标 {Path(args.into).resolve()}）")
        if copied:
            print(f"原件移进 {signals_dir(root) / '.swept'}")
        return 0

    try:
        items = collect(root, args.local)
    except ValueError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2

    if args.cmd == "list":
        if args.json:
            print(json.dumps([d for _, d in items], ensure_ascii=False, indent=2))
        elif not items:
            print(f"无信号记录（{signals_dir(root)}）")
        else:
            for p, d in items:
                print(f"{p.name}  [{d.get('status') or 'new'}] {d.get('signal') or '—'}  "
                      f"{d.get('occurrences', 1)} 次  {d.get('target_component')}")
        return 0

    # export
    keep = args.status if args.status is not None else [x for x in STATUSES if x != "dropped"]
    items = [(p, d) for p, d in items if (d.get("status") or "new") in keep]
    if args.since:
        items = [(p, d) for p, d in items if str(d.get("first_seen", ""))[:10] >= args.since]
    items.sort(key=lambda pd: (-int(pd[1].get("occurrences") or 1), str(pd[1].get("last_seen", ""))),
               reverse=False)
    if not items:
        print("无信号可导出", file=sys.stderr)
        return 0
    body = render_md(items, args.title)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(body, encoding="utf-8")
        print(f"已写入 {args.out}（{len(items)} 条）")
    else:
        print(body, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_entry(main))
