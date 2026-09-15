#!/usr/bin/env python3
"""import_trace.py —— 在**接收侧**接手一份交接包，把它落成 `traces/` 里的一单。

配套 `export_trace.py`（产出侧）。这个脚本只做机械动作——校验、落位、改名、比对知识库版本、
打印一屏交接简报；**恢复现场与继续定位是 `/skill:resume-diagnosis` 的事**。分工的理由是
原则里的老账：机械规则交给确定性脚本（失败可观测、可归因），语义判断交给 agent。
所以这里**不**试图读懂这次诊断，只保证"该在的东西都在、不在的东西被点名"。

为什么不让接收侧直接 `/diagnose <包>`：那会把这单当**新问题**重新收集与路由，得到的是一份
与上家不同的现场——状态本来就在包里，不该重新猜。

三种输入都能接（对应产出侧的两个投影）：
  <包目录>            —— 解压后的树，等价于 zip 解开
  handoff-<sid>.zip   —— 解压到临时目录再落位
  handoff-<sid>.md    —— 单文件纯文本包（走只认文本的通道时用）；证据原文只含内联进来的部分，
                         没内联的文件会被列为"缺"，**不会**被当成"包里没有证据"

同名冲突：目标 `traces/<sid>.yaml` 已存在时不覆盖、也不自动合并（两台机器为同一个问题各开一单
是常态，要不要合并是语义判断）。落成 `<sid>-imported-<n>`，trace 内部的 session_id、证据路径、
report_file 一起改写，并如实打印改了什么。

用法：
  python3 scripts/import_trace.py <包 | zip | md> [--dry-run] [--json] [--no-rename]
  python3 scripts/import_trace.py <包> --traces-root <目录>     # 指定落位处（跨机演练/自检用）

退出码：0 = 已落位（含"重复导入，未重复落位"）；2 = 包不合法/读不出；3 = 落位写盘失败；
        4 = 同名冲突且指定了 --no-rename。
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from _stdio import pin_utf8_stdio
from _yaml import load_text
from exec_log_path import resolve_traces, main_checkout
from kb_rev import kb_rev

SCHEMA_PREFIX = "ascend-sleuth-handoff/"
MD_HEAD = "<!-- ascend-sleuth-handoff v1 -->"
FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n\s*```\s*$", re.S)
EVIDENCE_RE = re.compile(
    r'<!-- BEGIN EVIDENCE path="([^"]+)"(?: bytes="(\d+)")? -->\s*\n(.*?)\n\s*<!-- END EVIDENCE -->',
    re.S)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def human_bytes(n) -> str:
    if n is None:
        return "—"
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024 or unit == "GB":
            return f"{f:.0f} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} GB"


def snippet(s, n=160):
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def strip_fence(body: str) -> str:
    """去掉 ```` ```lang ```` 围栏，只留正文（md 投影里每块都带围栏，便于人读）。"""
    m = FENCE_RE.match(body.strip("\n"))
    return m.group(1) if m else body


def die(msg, code=2, as_json=False, result=None):
    if as_json:
        doc = {"ok": False, "error": msg}
        if result:
            doc.update(result)
        print(json.dumps(doc, ensure_ascii=False))
    else:
        print(f"import_trace: {msg}", file=sys.stderr)
        print("✗ 未落位", file=sys.stderr)
    return code


# ---------------------------------------------------------------- 三种输入的读取

def read_md_package(path: Path, stage: Path, problems: list, truncated: list = None):
    """把单文件 md 包摊成 stage 目录，并合成一份 manifest（它本来就内嵌在 md 里）。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    if MD_HEAD not in text:
        problems.append("这不是交接包 md（缺标记 " + MD_HEAD + "）")
        return None
    man_block = re.search(re.escape("<!-- BEGIN MANIFEST -->") + r"(.*?)"
                          + re.escape("<!-- END MANIFEST -->"), text, re.S)
    trace_block = re.search(re.escape("<!-- BEGIN TRACE -->") + r"(.*?)"
                            + re.escape("<!-- END TRACE -->"), text, re.S)
    report_block = re.search(re.escape("<!-- BEGIN REPORT -->") + r"(.*?)"
                             + re.escape("<!-- END REPORT -->"), text, re.S)
    if not man_block or not trace_block:
        problems.append("md 包缺 MANIFEST 或 TRACE 区块（文件被截断？通道改写过内容？）")
        return None
    try:
        manifest = load_text(strip_fence(man_block.group(1)))
    except Exception as e:
        problems.append(f"md 包里的交接单解析失败：{e}")
        return None
    if not isinstance(manifest, dict):
        problems.append("md 包里的交接单不是 YAML 映射")
        return None

    sid = str(manifest.get("session_id") or "").strip()
    if not sid:
        problems.append("交接单缺 session_id")
        return None
    (stage / f"{sid}.yaml").write_text(strip_fence(trace_block.group(1)) + "\n", encoding="utf-8")
    if report_block:
        rep = str((manifest.get("contents") or {}).get("report_file") or f"{sid}.report.md")
        rp = stage / rep
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(report_block.group(1).strip("\n") + "\n", encoding="utf-8")
    for m in EVIDENCE_RE.finditer(text):
        rel, declared, body = m.group(1), m.group(2), m.group(3)
        dst = stage / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        content = strip_fence(body)
        dst.write_text(content + "\n", encoding="utf-8")
        # 实到字节明显少于声明字节 = 通道把内容截了（邮件正文有长度上限，这是文本通道的主要风险）。
        # 截断的证据比没有证据更危险：它看起来是齐的。留出 ±64 字节余量给围栏剥壳与换行归一。
        if declared and truncated is not None:
            got = len(content.encode("utf-8")) + 1
            if got + 64 < int(declared):
                truncated.append({"path": rel, "declared_bytes": int(declared), "got_bytes": got,
                                  "reason": "证据原文疑似被通道截断（实到明显少于声明）——"
                                            "别按完整证据用，重新索取或改走 zip 通道"})
    (stage / "handoff").mkdir(exist_ok=True)
    (stage / "handoff" / f"{sid}.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return manifest


def stage_package(src: Path, stage: Path, problems: list, truncated: list = None):
    """zip → 解压到 stage；目录 → 直接用；md → 摊平。返回 manifest 或 None。"""
    if src.is_dir():
        return load_manifest(src, problems)
    if src.suffix.lower() == ".md":
        return read_md_package(src, stage, problems, truncated)
    if src.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(src) as z:
                for info in z.infolist():
                    name = info.filename
                    # 防目录穿越（zip 是外来输入，别信它的名字）
                    if name.startswith("/") or ".." in Path(name).parts:
                        problems.append(f"zip 内有可疑路径，已跳过：{name}")
                        continue
                    z.extract(info, stage)
        except (zipfile.BadZipFile, OSError) as e:
            problems.append(f"zip 解压失败：{e}")
            return None
        return load_manifest(stage, problems)
    problems.append(f"不认识的输入：{src}（要包目录 / .zip / .md）")
    return None


def load_manifest(base: Path, problems: list):
    d = base / "handoff"
    if not d.is_dir():
        problems.append("包内没有 handoff/ 目录——这不是交接包（`export_trace.py` 的产物）")
        return None
    cands = sorted(d.glob("*.yaml"))
    if not cands:
        problems.append("handoff/ 下没有交接单（*.yaml）")
        return None
    for c in cands:
        try:
            doc = load_text(c.read_text(encoding="utf-8"))
        except Exception as e:
            problems.append(f"交接单 {c.name} 解析失败：{e}")
            continue
        if isinstance(doc, dict) and str(doc.get("schema") or "").startswith(SCHEMA_PREFIX):
            return doc
    problems.append(f"handoff/ 下的 YAML 都不是交接单（缺 schema: {SCHEMA_PREFIX}*）："
                    + "、".join(c.name for c in cands))
    return None


# ---------------------------------------------------------------- 校验与落位

def not_inlined_reason(manifest: dict, rel: str) -> str:
    """缺件原因：体积没内联（要 zip）还是传输丢件（要对包）。

    区分它们的理由：前者是**设计如此**（md 投影有内联上限），后者是包坏了。混成一句话，
    接手方会去追一个本来就没打算带的文件。
    """
    proj = manifest.get("projection") if isinstance(manifest.get("projection"), dict) else {}
    for row in proj.get("md_not_inlined") or []:
        if isinstance(row, dict) and str(row.get("path")) == rel:
            return ("单文件 md 投影未内联（" + str(row.get("reason") or "体积上限")
                    + "）——需要原文请索取 zip 包")
    return "交接单列了但包里没有（传输丢件或包不完整）"


def validate(base: Path, manifest: dict, problems: list, missing: list):
    """返回 (trace_rel, trace_text, doc)；不通过返回 None。缺失类问题进 `missing`（不致命）。"""
    sid = str(manifest.get("session_id") or "").strip()
    tpath = base / f"{sid}.yaml"
    if not tpath.is_file():
        problems.append(f"包内缺 trace 本体 {sid}.yaml")
        return None
    trace_text = tpath.read_text(encoding="utf-8")
    try:
        doc = load_text(trace_text)
    except Exception as e:
        problems.append(f"{sid}.yaml 解析失败：{e}")
        return None
    if not isinstance(doc, dict):
        problems.append(f"{sid}.yaml 顶层不是 YAML 映射")
        return None
    inner = str(doc.get("session_id") or "").strip()
    if inner and inner != sid:
        problems.append(f"包内不一致：交接单说 {sid}，trace 说 {inner}（包坏了，拒绝落位）")
        return None

    contents = manifest.get("contents") if isinstance(manifest.get("contents"), dict) else {}
    listed = contents.get("files") if isinstance(contents.get("files"), list) else []
    for f in listed:
        if not isinstance(f, dict):
            continue
        rel, kind = str(f.get("path") or ""), str(f.get("kind") or "")
        # 交接单与 README 是元数据件：md 投影用自身页眉承载它们的效果，不算缺件
        if kind in ("manifest", "readme") or not rel:
            continue
        if not (base / rel).is_file():
            missing.append({"path": rel, "kind": kind, "reason": not_inlined_reason(manifest, rel)})
    # trace 引用过、但包里没有的证据：**这条最重要**——不说，接手方会以为现场是全的
    seen = {m["path"] for m in missing}
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
            n = str(f or "").replace("\\", "/")
            m = re.search(r"(?:^|/)traces/(.+)$", n)
            rel = m.group(1) if m else n.lstrip("./")
            if rel and rel not in seen and not (base / rel).is_file():
                seen.add(rel)
                missing.append({"path": rel, "kind": "evidence",
                                "reason": "trace 引用了它，但包内清单里也没有（上家就没打进包）"
                                          "——接手前先向上家索取原件"})
    return doc


def free_sid(traces_root: Path, sid: str):
    """同名时的改名目标：`<sid>-imported-<n>`（n 从 1 起，取第一个空位）。"""
    if not (traces_root / f"{sid}.yaml").exists():
        return sid
    n = 1
    while (traces_root / f"{sid}-imported-{n}.yaml").exists():
        n += 1
    return f"{sid}-imported-{n}"


def find_duplicate(traces_root: Path, manifest: dict):
    """同一份导出是否已经落过位（按 exported_at + 源 session_id 认，不看文件名）。

    为什么值得判：跨网时同一份包可能被发两次（邮件重发、摆渡重传）。第二次再落一份就成了
    traces/ 里两单一样的东西——那是给误诊归因和指标添噪声，不是"多留个备份"。
    """
    exported_at = str(manifest.get("exported_at") or "")
    src_sid = str(manifest.get("session_id") or "")
    if not exported_at:
        return None
    d = traces_root / "handoff"
    if not d.is_dir():
        return None
    for p in sorted(d.glob("*.yaml")):
        try:
            doc = load_text(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        imp = doc.get("imported") if isinstance(doc.get("imported"), dict) else {}
        # 落位后 origin.kb_rev 等会变，但 exported_at 与源 session_id 不变——用它当指纹
        if str(imp.get("source_exported_at") or "") == exported_at \
                and str(imp.get("source_session_id") or "") == src_sid:
            return p.stem
    return None


def apply_import(base: Path, traces_root: Path, manifest: dict, doc, target_sid: str, sid: str):
    """把包内容落进 traces/（含改名改写）。返回落位清单。失败抛 OSError。"""
    renamed = target_sid != sid
    written = []
    # 接收侧可能是**全新检出**：traces/ 是 gitignore 的运行时件，第一次接手时它还不存在。
    # 不建这一层，最常见的那个场景（新机器上的第一单）会以一句 No such file or directory 收场。
    traces_root.mkdir(parents=True, exist_ok=True)
    trace_text = (base / f"{sid}.yaml").read_text(encoding="utf-8")
    if renamed:
        # 一次替换搞定 session_id、evidence.files、report_file 与正文里对本案的称呼；
        # 单遍 re.sub 不会二次命中（新名字含旧名字做前缀，但正则只在原文上扫一遍）。
        trace_text = re.sub(re.escape(sid), target_sid, trace_text)
    (traces_root / f"{target_sid}.yaml").write_text(trace_text, encoding="utf-8")
    written.append(f"{target_sid}.yaml")

    contents = manifest.get("contents") if isinstance(manifest.get("contents"), dict) else {}
    report_rel = str(contents.get("report_file") or "")
    if report_rel and (base / report_rel).is_file():
        new_report = f"{target_sid}.report.md"
        (traces_root / new_report).write_text(
            (base / report_rel).read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        written.append(new_report)
        # trace 里的 report_file 已随改名一并改写；若原名不含 sid（自定义名），这里补正
        t = (traces_root / f"{target_sid}.yaml").read_text(encoding="utf-8")
        t = re.sub(r'(?m)^(report_file:).*$', f'\\1 "{new_report}"', t, count=1)
        (traces_root / f"{target_sid}.yaml").write_text(t, encoding="utf-8")

    src_ev = base / "evidence" / sid
    if src_ev.is_dir():
        dst_ev = traces_root / "evidence" / target_sid
        for p in sorted(src_ev.rglob("*")):
            if p.is_file():
                rel = p.relative_to(src_ev)
                (dst_ev / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, dst_ev / rel)
                written.append((Path("evidence") / target_sid / rel).as_posix())

    # 交接单落进 traces/handoff/<sid>.yaml：留着它，接收侧（agent 与面板）才看得出
    # "这一单是外来包接手来的、来源主机与知识库版本是什么"。附 imported 块做溯源。
    rev_now, _dirty, _src = kb_rev(traces_root.parent)
    manifest = dict(manifest)
    manifest["imported"] = {
        "imported_at": now_iso(),
        "into": str(traces_root),
        "renamed_from": sid if renamed else None,
        "kb_rev_at_import": rev_now,
        "kb_rev_match": None if str(manifest.get("origin", {}).get("kb_rev") or "") in ("", "unknown")
                        else str(manifest["origin"]["kb_rev"]) == rev_now,
        "source_exported_at": str(manifest.get("exported_at") or ""),
        "source_session_id": sid,
        "source_host": str((manifest.get("origin") or {}).get("host") or ""),
    }
    hdir = traces_root / "handoff"
    hdir.mkdir(parents=True, exist_ok=True)
    (hdir / f"{target_sid}.yaml").write_text(
        "# 交接单（外来包导入后留档，由 import_trace.py 写；来源见 imported 块）\n"
        + yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    written.append(f"handoff/{target_sid}.yaml")
    readme = base / "handoff" / f"{sid}.README.txt"
    if readme.is_file():
        (hdir / f"{target_sid}.README.txt").write_text(
            readme.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        written.append(f"handoff/{target_sid}.README.txt")
    return manifest, written


def main() -> int:
    ap = argparse.ArgumentParser(description="在接收侧接手一份交接包（落成 traces/ 里的一单）")
    ap.add_argument("package", help="包目录 / handoff-<sid>.zip / handoff-<sid>.md")
    ap.add_argument("--traces-root", default=None, help="落位到哪个 traces/（默认：主检出那一份）")
    ap.add_argument("--root", default=None, help="仓库根目录（默认：本脚本上两级）")
    ap.add_argument("--dry-run", action="store_true", help="只校验与打印，不落位")
    ap.add_argument("--no-rename", action="store_true", help="同名时不改名（直接失败，交人决定）")
    ap.add_argument("--force", action="store_true", help="同一份导出已落过位时仍然再落一份")
    ap.add_argument("--json", action="store_true", help="只吐 JSON（面板/自检用）")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    traces_root = Path(args.traces_root).resolve() if args.traces_root else resolve_traces(root)
    src = Path(args.package)
    if not src.exists():
        return die(f"找不到包：{src}", 2, args.json)

    problems, missing, truncated = [], [], []
    tmp = None
    try:
        if src.is_dir():
            base = src
        else:
            tmp = Path(tempfile.mkdtemp(prefix="handoff-import-"))
            base = tmp
        manifest = stage_package(src, base, problems, truncated)
        if manifest is None:
            return die("；".join(problems), 2, args.json, {"problems": problems})
        if not str(manifest.get("schema") or "").startswith(SCHEMA_PREFIX):
            return die(f"不支持的交接单版本：{manifest.get('schema')}（本脚本认 {SCHEMA_PREFIX}*）",
                       2, args.json)

        got = validate(base, manifest, problems, missing)
        if got is None:
            return die("；".join(problems), 2, args.json, {"problems": problems})
        doc = got
        sid = str(manifest["session_id"])

        dup = None if args.force else find_duplicate(traces_root, manifest)
        target = sid
        replaced = False
        if (traces_root / f"{sid}.yaml").exists():
            if args.no_rename:
                return die(f"{traces_root} 下已有 {sid}.yaml（--no-rename：交你决定要不要合并）",
                           4, args.json, {"session_id": sid, "traces_root": str(traces_root)})
            target = free_sid(traces_root, sid)
            replaced = True

        # 版本与源码：接手方真正要判的两件事
        cur_rev, _dirty, _s = kb_rev(traces_root.parent)
        origin_rev = str((manifest.get("origin") or {}).get("kb_rev") or "unknown")
        if origin_rev == "unknown":
            kb_state, kb_note = "unknown", "上家没有记录知识库版本——候选集与 case id 无法比对，遇到不一致按本机库为准"
        elif origin_rev == cur_rev:
            kb_state, kb_note = "match", f"与上家一致（{cur_rev}）"
        else:
            kb_state, kb_note = "mismatch", (
                f"与上家不一致（上家 {origin_rev} / 本机 {cur_rev}）——同一条 case 的 id 可能不存在、"
                f"候选排序可能不同、甚至那条 case 当时还没沉淀；接手时以本机知识库为准，"
                f"发现候选集与 trace 记的对不上就如实说明，别把差异当成上家写错")
        src_rows = []
        cache_root = main_checkout(traces_root.parent) or traces_root.parent
        for s in manifest.get("src_refs") or []:
            if not isinstance(s, dict):
                continue
            cached = (cache_root / "src-code" / str(s.get("org")) / str(s.get("repo"))
                      / str(s.get("ref"))).is_dir()
            src_rows.append({"org": s.get("org"), "repo": s.get("repo"), "ref": s.get("ref"),
                             "files": len(s.get("files") or []), "cached_locally": cached})

        result = {
            "ok": True,
            "session_id": target,
            "renamed_from": sid if replaced else None,
            "duplicate_of": dup,
            "dry_run": bool(args.dry_run),
            "traces_root": str(traces_root),
            "intent": manifest.get("intent"),
            "origin": manifest.get("origin") or {},
            "session": manifest.get("session") or {},
            "needs": manifest.get("needs") or [],
            "redaction": manifest.get("redaction") or {},
            "kb_rev_state": kb_state,
            "kb_rev_note": kb_note,
            "src_refs": src_rows,
            "missing": missing,
            "truncated": truncated,
            "omitted": (manifest.get("contents") or {}).get("omitted") or [],
            "md_not_inlined": ((manifest.get("projection") or {}).get("md_not_inlined") or []),
            "warnings": manifest.get("warnings") or [],
            "written": [],
        }

        if dup and not args.dry_run:
            result["note"] = f"同一份导出已落过位（{dup}）——未重复落位；要再落一份加 --force"
            if args.json:
                print(json.dumps(result, ensure_ascii=False))
            else:
                print(f"这份包已经接手过了：traces/{dup}.yaml（同一 exported_at 与源 session）。")
                print("未重复落位——重复落位会在 traces/ 里留下两单一模一样的记录，给误诊归因添噪声。")
                print(f"确实要再落一份：python3 scripts/import_trace.py {src} --force")
            return 0

        if not args.dry_run:
            try:
                manifest2, written = apply_import(base, traces_root, manifest, doc, target, sid)
            except OSError as e:
                return die(f"落位失败（{traces_root}）：{e}", 3, args.json, result)
            result["written"] = written
            result["manifest"] = str(traces_root / "handoff" / f"{target}.yaml")
            result["imported"] = manifest2.get("imported")

        if args.json:
            print(json.dumps(result, ensure_ascii=False))
            return 0

        # ---------------- 一屏交接简报 ----------------
        ses = result["session"]
        intent_label = {"continue": "继续定位", "verify": "复核结论", "escalate": "转上游"}
        print(f"已接手：{target}" + (f"（原 {sid}，本机已有同名单 → 改名落位）" if replaced else "")
              + ("　[dry-run：只校验，未落位]" if args.dry_run else ""))
        print(f"  来源      {result['origin'].get('host', '?')}"
              f" · 导出 {str(manifest.get('exported_at'))[:19]}"
              f" · 意图 {intent_label.get(str(manifest.get('intent')), manifest.get('intent'))}")
        print(f"  这单      {snippet(ses.get('summary') or '（无 summary）', 120)}")
        print(f"  停在哪    status={ses.get('status')} · step={ses.get('current_step')}"
              f" · 命中 case={ses.get('active_case')}"
              f" · 已排除 {len(ses.get('excluded_cases') or [])} 个"
              f" · 框架={ses.get('detected_framework') or '未记'}"
              f" · 类别={ses.get('detected_category') or '未记'}")
        print(f"  知识库    {kb_note}")
        for s in src_rows:
            mark = "本地已有" if s["cached_locally"] else "本地没有"
            print(f"  源码      {s['org']}/{s['repo']}@{s['ref']}（{s['files']} 个文件被引用，{mark}）"
                  + ("" if s["cached_locally"] else
                     f" → python3 scripts/src_fetch.py {s['org']}/{s['repo']} --ref {s['ref']}"))
        if result["needs"]:
            print("  要什么（上家留下的缺口，接手先问这几条）：")
            for i, s in enumerate(result["needs"], 1):
                print(f"    {i}. {s}")
        if result["missing"]:
            print(f"  ⚠ 包内缺 {len(result['missing'])} 个被引用的文件（**现场不完整**，别当成证据已齐）：")
            for m in result["missing"][:10]:
                print(f"    - {m['path']} —— {m['reason']}")
            if len(result["missing"]) > 10:
                print(f"    …另有 {len(result['missing']) - 10} 个，见 --json 的 missing 字段")
        if result["truncated"]:
            print(f"  ⚠ {len(result['truncated'])} 个证据原文疑似被通道截断（**别按完整证据用**）：")
            for t in result["truncated"]:
                print(f"    - {t['path']}：声明 {human_bytes(t['declared_bytes'])}，实到 {human_bytes(t['got_bytes'])}")
        if result["omitted"]:
            print(f"  · 产出侧另有 {len(result['omitted'])} 个证据文件因体积上限未纳入（需另行索取）")
        if result["redaction"].get("state") == "raw-evidence":
            print("  · 包内含原始现场证据（交接单 redaction.state=raw-evidence）——"
                  "继续在两台机器间转手前按你们的数据通道规则处理")
        for w in result["warnings"]:
            print(f"  · {w}")
        if not args.dry_run:
            print(f"\n已落位到 {traces_root}：" + "、".join(result["written"][:6])
                  + (f" 等 {len(result['written'])} 项" if len(result["written"]) > 6 else ""))
            print("接着做：")
            print(f"  /skill:resume-diagnosis {target}")
            if replaced:
                print(f"  本机原本还有一单同名的 {sid}（面板上两单都在）——"
                      f"它们是不是同一个问题、要不要合并，交你判断；脚本不自动合并。")
        return 0
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
