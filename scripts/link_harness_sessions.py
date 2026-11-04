#!/usr/bin/env python3
"""link_harness_sessions.py —— 给缺 `harness_session` 的历史轨迹补上 harness 会话号。

**为什么需要它**：轨迹里的 `session_id` 是**诊断自己起的名字**（形如
`<日期>-<issue 号>-<短名>`），不是 DSH 的会话号——DSH 的会话号是 `session-<uuid>`。
两套号之间唯一的桥是顶层可选字段 `harness_session`（口径见
`skills/diagnose/references/diagnosis-trace.md`）。早期轨迹没写这个字段，于是"从轨迹跳到
那次会话"这件事做不成：面板只能说"这单没记会话号"。

**怎么找**：诊断时 agent 会用文件工具写 `traces/<名字>.yaml`，那次调用落在会话日志里。
但**只数命中次数是不够的**：同一个名字后来会被别的会话反复引用（知识整理读轨迹、报告里
引用旧单、讨论面板本身），实测一条旧单的名字出现在 145 个会话里、命中最多的是后来的会话
而不是写它的那次。所以判据是**时间**，两条一起用：

  ① 该会话的时间范围（首事件的 `createdAt` → 末事件的 `time`）要能覆盖轨迹的 `created_at`
     （两侧留出偏差：`created_at` 是 agent 手写的，比会话真正开始晚几分钟很常见）；
  ② 满足 ① 的候选里，取**会话开始时间离 `created_at` 最近**的那个——诊断先开会话、几分钟后
     才写第一版轨迹，而后来引用它的会话离得远得多（实测差 15 小时到 35 天）。

两条都给不出候选时退到"命中次数最多"，但**默认不写**：命中次数是弱证据（引用过 ≠ 写过），
落一个错的会话号会让面板跳到别人的会话上，比"未记会话号"更坏。要看这批就加
`--allow-weak`，输出里逐条标着依据。

时间窗给不出候选时退到"命中次数最多"，并在输出里标明依据是命中次数而不是时间窗——不假装
两种证据一样强。

**只补空**：已有 `harness_session` 的轨迹不动（那是当时写定的，可能来自 `$DSH_SESSION_ID`，
比事后扫描更可信）。补出来的值没有来源标记（字段没有来源位，加了就改 schema）；逐条依据
打在输出里，要追溯就留这次运行的输出。

用法：

  python3 scripts/link_harness_sessions.py                 # dry-run：打印将补的映射与依据
  python3 scripts/link_harness_sessions.py --apply          # 写进轨迹（每单插一行）
  python3 scripts/link_harness_sessions.py --trace <名字>   # 只处理某一单（调试用）
  python3 scripts/link_harness_sessions.py --trace <名字> --session-id "$DSH_SESSION_ID"
                                                          # 已知会话号时直接写，不扫日志（秒级）
  python3 scripts/link_harness_sessions.py --sessions-root <目录>   # 指定会话日志根（测试用）

退出码：0 = 成功（含"没有要补的"）；2 = 参数或环境不可用。
"""

from __future__ import annotations

import argparse
import io
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exec_log_path import resolve_traces  # noqa: E402  （typo-safe：运行时件锚主检出）
from trace_entry_activity import (  # noqa: E402  （同目录复用，不复制一份会话日志口径）
    HARNESS_LOG_PATTERNS,
    harness_homes,
    read_log_text,
)

TRACES_REL = "traces"
#: 顶层该字段的行；自动扫描时"空值也算写过"不覆盖，显式给了 --session-id 时允许补空值。
FIELD_RE = re.compile(r"^harness_session\s*:\s*(.*)$", re.MULTILINE)
SESSION_ID_RE = re.compile(r"^session_id\s*:\s*(.+)$", re.MULTILINE)
CREATED_RE = re.compile(r"^created_at\s*:\s*(.+)$", re.MULTILINE)
#: 会话日志里时间的两处来源：首事件的 `createdAt`（ISO）与事件的 `time`（epoch ms）。
#: `createdAt` 在会话日志里是**数字**（epoch ms），个别导出件是 ISO 串——两种都收。
LOG_START_RE = re.compile(r'"createdAt"\s*:\s*(?:"([^"]+)"|(\d{12,}))')
LOG_TIME_RE = re.compile(r'"time"\s*:\s*(\d{12,})')
LOG_SID_RE = re.compile(r'"id"\s*:\s*"(session-[^"]+)"')
#: 时间窗两侧的容许偏差：轨迹的 `created_at` 是 agent 手写的，比会话真正开始晚几分钟很常见。
START_SLACK_MS = 30 * 60 * 1000
END_SLACK_MS = 6 * 60 * 60 * 1000
#: 会话开始时间与 `created_at` 之间容许的最大距离。超过这个距离的候选只能是"后来引用过它"，
#: 不是写它的那次（实测最近的真会话差 5 分钟到 64 分钟，次近的差 15 小时以上）。
NEAR_MS = 3 * 60 * 60 * 1000


def read_text_fast(path: Path):
    """会话日志 → 文本。本脚本要一次过几百份日志，所以解压走快路径，三条腿按可用性降级：

    ① `zstandard`（进程内解压）；② `zstd -dc`（命令行）；③ 仓库既有的 `read_log_text`
    （node 解压，零依赖但每份一次进程启动）。三者产出同一条 JSONL 文本；选谁不影响结果，
    只影响"一次扫几百份要等多久"（实测 46 秒 / 1113 份 / 548 MB）。
    """
    raw = path.read_bytes()
    if raw[:4] != b"\x28\xb5\x2f\xfd":
        return raw.decode("utf-8", "replace")
    try:
        import zstandard  # type: ignore
        with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)) as r:
            return r.read().decode("utf-8", "replace")
    except ImportError:
        pass
    except Exception:
        pass
    zstd = shutil.which("zstd")
    if zstd:
        try:
            r = subprocess.run([zstd, "-dc", str(path)], capture_output=True, timeout=300)
            if r.returncode == 0:
                return r.stdout.decode("utf-8", "replace")
        except Exception:
            pass
    return read_log_text(path)


def iso_ms(value):
    """ISO 时间串 → epoch 毫秒；解析不出返回 None。"""
    if not value:
        return None
    text = str(value).strip().strip("'\"")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp() * 1000
    except ValueError:
        return None


def log_bounds(text: str):
    """会话日志 → (开始毫秒, 结束毫秒, 会话号)。拿不到的部分为 None。"""
    start = None
    m = LOG_START_RE.search(text[:4000])
    if m:
        start = float(m.group(2)) if m.group(2) else iso_ms(m.group(1))
    times = LOG_TIME_RE.findall(text[-8000:])
    end = float(times[-1]) if times else None
    m = LOG_SID_RE.search(text[:4000])
    return start, end, (m.group(1) if m else None)


def trace_files(root: Path):
    """轨迹文件列表。**目录解析到主检出**：在 worktree 里跑时本检出的 traces/ 不存在
    （它是 gitignored 运行时件，只落在主检出），不解析就会得到"没有缺字段的轨迹"这种假绿。"""
    d = resolve_traces(root)
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.yaml") if p.is_file())


def slug_of(path: Path, text: str) -> str:
    """轨迹的诊断会话名：优先 `session_id`，没有就退到文件名。"""
    m = SESSION_ID_RE.search(text)
    if m:
        v = m.group(1).strip().strip("'\"")
        if v:
            return v
    return path.stem


def created_of(text: str):
    m = CREATED_RE.search(text)
    return iso_ms(m.group(1)) if m else None


def needs_link(text: str, allow_empty: bool = False) -> bool:
    match = FIELD_RE.search(text)
    if match is None:
        return True
    if not allow_empty:
        return False
    value = match.group(1).strip().strip("'\"").strip()
    return value == ""


def session_roots(explicit):
    if explicit:
        return [Path(explicit)]
    return [h / "sessions" for h in harness_homes()]


def scan_logs(sessions_dirs, slugs, min_mtime):
    """扫一遍会话日志，返回 (命中表, 扫了几份)。

    命中表：`{名字: [(会话号, 开始ms, 结束ms, 命中次数, 日志路径), …]}`。
    先按 `min_mtime` 剪一层：日志最后修改时间早于最早一单轨迹，就不可能写过它。
    """
    hits = {s: [] for s in slugs}
    scanned = 0
    for root in sessions_dirs:
        if not root.is_dir():
            continue
        for ws in sorted(p for p in root.iterdir() if p.is_dir()):
            for sd in sorted(p for p in ws.iterdir() if p.is_dir()):
                logs = []
                for pat in HARNESS_LOG_PATTERNS:
                    logs += [p for p in sd.glob(pat) if p.is_file()]
                if not logs:
                    continue
                log = max(logs, key=lambda p: p.stat().st_mtime)
                try:
                    if log.stat().st_mtime < min_mtime:
                        continue
                except OSError:
                    continue
                text = read_text_fast(log)
                scanned += 1
                if not text:
                    continue
                start, end, sid = log_bounds(text)
                sid = sid or sd.name
                for slug in slugs:
                    n = text.count(slug)
                    if n:
                        hits[slug].append((sid, start, end, n, log))
    return hits, scanned


def pick(cands, created):
    """候选 → (会话号, 依据)。依据两档：时间（强）/ 命中次数（退档，如实标注）。

    时间判据两条件同时成立：窗口覆盖 `created_at`（±偏差），且会话开始时间离它不超过
    `NEAR_MS`。满足者按 |开始 - created_at| 升序取第一个——最近的那次才是写它的会话。
    """
    if not cands:
        return None, None
    if created is not None:
        near = [c for c in cands
                if c[1] is not None and c[2] is not None
                and c[2] + END_SLACK_MS >= created
                and c[1] - START_SLACK_MS <= created + NEAR_MS
                and abs(c[1] - created) <= NEAR_MS]
        if near:
            best = sorted(near, key=lambda c: (abs(c[1] - created), -c[3]))[0]
            return best[0], "时间"
    best = sorted(cands, key=lambda c: -c[3])[0]
    return best[0], "命中次数"


def set_field(text: str, value: str) -> str:
    """写 `harness_session:`：已有空值行就替换，没有就插在 `session_id:` 之后。"""
    if FIELD_RE.search(text):
        return FIELD_RE.sub("harness_session: \"" + value + "\"", text, count=1)
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if re.match(r"^session_id\s*:", line):
            lines.insert(i + 1, "harness_session: \"" + value + "\"\n")
            return "".join(lines)
    return "harness_session: \"" + value + "\"\n" + text


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--apply", action="store_true", help="写进轨迹（默认只打印）")
    ap.add_argument("--allow-weak", action="store_true",
                    help='连「只按命中次数」定到的也写（弱证据；默认只打印不写）')
    ap.add_argument("--trace", default=None, help="只处理某一单（名字或文件名）")
    ap.add_argument("--sessions-root", default=None, help="会话日志根目录（默认自动探测）")
    ap.add_argument("--session-id", default=None,
                    help="已知的 harness 会话号（如 $DSH_SESSION_ID）；给了就不扫日志，直接写这一单")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent), help="仓库根")
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    targets = []
    for p in trace_files(root):
        if args.trace and args.trace not in (p.stem, p.name):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if needs_link(text, allow_empty=bool(args.session_id)):
            targets.append((p, text))
    if not targets:
        print("没有缺 harness_session 的轨迹（已有的不覆盖）。")
        return 0

    # 已知会话号时不必扫日志：写侧漏写的那一单当场就能补（扫日志要几十秒，还得名字在日志里）。
    if args.session_id:
        sid = args.session_id.strip()
        if not sid.startswith('session-'):
            print('--session-id 需要 DSH 会话号（形如 session-<uuid>），拿到的是：' + sid, file=sys.stderr)
            return 2
        written = 0
        for p, _text in targets:
            text = p.read_text(encoding="utf-8")
            if not needs_link(text, allow_empty=True):
                continue
            if args.apply:
                p.write_text(set_field(text, sid), encoding="utf-8")
                written += 1
                print(f"  已写 {p.name} → {sid}")
            else:
                print(f"  将写 {p.name} → {sid}")
        if not args.apply:
            print("\n（dry-run：加 --apply 才写进轨迹）")
        else:
            print(f"已补 {written} 单。")
        return 0

    slugs = {slug_of(p, t) for p, t in targets}
    roots = session_roots(args.sessions_root)
    if not any(r.is_dir() for r in roots):
        print("找不到会话日志目录（试过：" + "；".join(str(r) for r in roots) + "）。", file=sys.stderr)
        return 2

    min_mtime = min(p.stat().st_mtime for p, _ in targets) - 86400
    hits, scanned = scan_logs(roots, slugs, min_mtime)

    plan, unresolved = [], []
    for p, text in targets:
        slug = slug_of(p, text)
        sid, basis = pick(hits.get(slug) or [], created_of(text))
        if sid is None:
            unresolved.append((p, slug))
        else:
            plan.append((p, slug, sid, basis))

    weak = [x for x in plan if x[3] != "时间"]
    print(f"扫了 {scanned} 份会话日志；待补 {len(targets)} 单，"
          f"按时间定到 {len(plan) - len(weak)} 单，只有弱证据 {len(weak)} 单，定不到 {len(unresolved)} 单。")
    for _, slug, sid, basis in plan:
        print(f"  {slug}  →  {sid}   （依据：{basis}）")
    for _, slug in unresolved:
        print(f"  {slug}  →  （会话日志里没有这个名字：会话可能不在本机）")

    if not args.apply:
        print("\n（dry-run：加 --apply 才写进轨迹）")
        return 0

    written = 0
    skipped_weak = 0
    for p, _slug, sid, basis in plan:
        if basis != "时间" and not args.allow_weak:
            skipped_weak += 1
            continue
        text = p.read_text(encoding="utf-8")
        if not needs_link(text):
            continue
        p.write_text(set_field(text, sid), encoding="utf-8")
        written += 1
    print(f"已补 {written} 单。")
    if skipped_weak:
        print(f'跳过 {skipped_weak} 单：只有「命中次数」这一条弱证据（要写就加 --allow-weak）。')
    return 0


if __name__ == "__main__":
    sys.exit(main())
