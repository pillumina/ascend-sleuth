#!/usr/bin/env python3
"""check_handoff.py —— 交接包往返自检（合成夹具 + 本机真 trace 两段）。

守的是什么：`export_trace.py` ↔ `import_trace.py` 这条链上，**只有两类失败会静默**——
① 包看起来正常，但落位后接手方看到的一单与上家那单内容不同（路径/字段被改写错）；
② 元数据件（`handoff/` 下的交接单）被下游读取端误当成一单会话，或反过来漏掉。

两类都不报错，直到有人据此下结论。所以这里用**合成夹具**把每条路径都真跑一遍：
zip 通道、单文件 md 通道（含"未内联"与"传输丢件"两种缺件的区分）、同名改名、
同一份包重复落位、知识库版本一致/不一致、非法包拒收、`--no-rename` 拒收。
再加一段"本机真 trace"的端到端：有真 trace 就跑，没有（CI 检出里 traces/ 是 gitignore 的
运行时件）就如实打印跳过，不假装跑过。

用法：
  python3 scripts/check_handoff.py            # 全跑
  python3 scripts/check_handoff.py --fixtures-only
退出码：0 = 全绿；1 = 有断言失败。
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _stdio import pin_utf8_stdio
from _yaml import load_text
from exec_log_path import resolve_traces

REPO = Path(__file__).resolve().parent.parent
FAILS = []
PASSES = []


def check(label, ok, detail=""):
    if ok:
        PASSES.append(label)
        print(f"  ✓ {label}")
    else:
        FAILS.append(label)
        print(f"  ✗ {label}" + (f"\n      {detail}" if detail else ""))


def run(args, cwd=None):
    """跑一个脚本，返回 (exit_code, stdout, stderr)。

    `cwd` 用来复现"从别的目录跑"的调用形状（面板就是 workdir=检出）；脚本路径随之要绝对化，
    否则在别的工作目录下会找不到 scripts/xxx.py——那测的就成了"路径写对了没有"，不是被测行为。
    """
    argv = list(args)
    if argv and argv[0].startswith("scripts/"):
        argv[0] = str(REPO / argv[0])
    r = subprocess.run([sys.executable, *argv], cwd=str(cwd or REPO),
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def run_json(args, cwd=None):
    code, out, err = run(args, cwd)
    doc = None
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                doc = None
            break
    return code, doc, (out + err)


def git_init(path: Path, msg: str):
    """把一个目录变成 git 检出并取到 HEAD 短 sha（kb_rev 比对需要一个真检出）。"""
    path.mkdir(parents=True, exist_ok=True)
    env = {"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "f@x",
           "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "f@x"}
    import os
    env = {**os.environ, **env}
    for cmd in (["git", "init", "-q"],):
        subprocess.run(cmd, cwd=str(path), capture_output=True, env=env)
    (path / "README").write_text(msg, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(path), capture_output=True, env=env)
    subprocess.run(["git", "commit", "-qm", msg], cwd=str(path), capture_output=True, env=env)
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(path),
                       capture_output=True, text=True, env=env)
    return r.stdout.strip()


FIXTURE_TRACE = """# 合成夹具（check_handoff.py 生成；不含任何客户数据，可公开）
session_id: "{sid}"
status: in_progress
current_step: 4
summary: "合成夹具：验证交接包往返——zip 通道、单文件 md 通道、同名改名、版本比对"
created_at: "2026-01-01T10:00:00+08:00"
updated_at: "2026-01-01T10:30:00+08:00"
kb_rev: "{kb_rev}"
detected_framework: fixture-fw
detected_platform: A2-910B
detected_category: interrupt
report_file: "{sid}.report.md"
sediment_candidates: []
feedback: {{case: FIXTURE-CASE-001, outcome: pending, confirmed_at: ""}}
excluded_cases: [FIXTURE-CASE-002]
active_case: FIXTURE-CASE-001
last_action: "等现场补 plog 首报错段后继续"
trace:
  - role: user
    step: 1
    content: "合成夹具输入（验证 user 事件与证据引用一起过包）"
    evidence:
      inline: "synthetic signature: FIXTURE_ERR_0001 at fixture-step-4"
      files:
        - "traces/evidence/{sid}/log-tail.txt"
        - "traces/evidence/{sid}/big-plog.txt"
        - "traces/evidence/{sid}/never-packed.txt"
      missing: "缺 device 侧日志（夹具故意留的缺口）"
  - role: agent
    step: 2
    action: triage
    output: "路由到合成分支"
    reason: "夹具：只验证打包与接手链路，不做真实检索"
"""

FIXTURE_REPORT = """# 合成夹具报告

## 1. TL;DR
夹具报告，用于验证报告随包一起走、且 `report_file` 指向的文件确实落位。

## 2. 依据链
- 合成签名 `FIXTURE_ERR_0001`（已验证）
"""


def make_fixture_root(tmp: Path, sid: str, kb_rev: str, big=True):
    """造一台"上家机器"：traces/<sid>.yaml + report + evidence。"""
    root = tmp / f"src-{sid}"
    tr = root / "traces"
    ev = tr / "evidence" / sid
    ev.mkdir(parents=True, exist_ok=True)
    (tr / f"{sid}.yaml").write_text(
        FIXTURE_TRACE.format(sid=sid, kb_rev=kb_rev), encoding="utf-8")
    (tr / f"{sid}.report.md").write_text(FIXTURE_REPORT, encoding="utf-8")
    (ev / "log-tail.txt").write_text("FIXTURE_ERR_0001 tail\n" * 20, encoding="utf-8")
    if big:
        # 超过 md 内联上限（默认 256KB）→ 必须出现在 projection.md_not_inlined 里
        (ev / "big-plog.txt").write_text("FIXTURE_ERR_0001 repeated\n" * 20000, encoding="utf-8")
    return tr


def digest(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="交接包往返自检")
    ap.add_argument("--fixtures-only", action="store_true", help="跳过「本机真 trace」那一段")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="handoff-check-"))
    try:
        print("[交接包 · 合成夹具（两台「机器」都是临时目录）]")
        rev_a = git_init(tmp / "recv-a", "receiver A")
        rev_b = git_init(tmp / "recv-b", "receiver B")
        check("两台夹具机器的 HEAD 不同（版本比对才能判）", rev_a != rev_b, f"{rev_a} / {rev_b}")

        sid = "2026-01-01-fixture-handoff"
        src = make_fixture_root(tmp, sid, kb_rev=rev_a)
        out = tmp / "exports"

        # ---------- ① 导出 ----------
        code, doc, raw = run_json(["scripts/export_trace.py", sid, "--traces-root", str(src),
                                   "--out", str(out), "--intent", "continue",
                                   "--note", "夹具交接说明", "--json"])
        check("导出成功（exit 0）", code == 0 and doc and doc.get("ok"), raw.strip()[-400:])
        if not doc or not doc.get("ok"):
            return finish()
        check("zip 与 md 两个投影都产出", bool(doc.get("zip")) and bool(doc.get("md")))
        check("交接意图按命令行记下", doc.get("intent") == "continue"
              and doc.get("intent_source") == "cli")
        check("待补材料从 evidence.missing + last_action 投影（2 条）",
              len(doc.get("needs") or []) == 2, json.dumps(doc.get("needs"), ensure_ascii=False))
        check("含原始证据时如实标 raw-evidence",
              (doc.get("redaction") or {}).get("state") == "raw-evidence")
        check("未被引用的证据文件不进包", (doc.get("omitted") or []) == [])

        manifest_path = Path(doc["manifest"])
        man = load_text(manifest_path.read_text(encoding="utf-8"))
        check("交接单记了来源主机与知识库版本（取自 trace 的 kb_rev）",
              (man.get("origin") or {}).get("kb_rev") == rev_a
              and (man.get("origin") or {}).get("kb_rev_source") == "trace",
              json.dumps(man.get("origin"), ensure_ascii=False))
        kinds = {f["kind"] for f in man["contents"]["files"]}
        check("包内清单含 trace/report/evidence/manifest/readme",
              {"trace", "report", "evidence", "manifest", "readme"} <= kinds, str(kinds))
        check("md 未内联清单列出超限的那个证据文件（含原因）",
              any("big-plog.txt" in str(r.get("path"))
                  for r in (man.get("projection") or {}).get("md_not_inlined") or []),
              json.dumps((man.get("projection") or {}).get("md_not_inlined"), ensure_ascii=False))

        zip_path, md_path = Path(doc["zip"]), Path(doc["md"])
        recv_a, recv_b = tmp / "recv-a" / "traces", tmp / "recv-b" / "traces"
        recv_a.mkdir(parents=True, exist_ok=True)
        recv_b.mkdir(parents=True, exist_ok=True)

        # ---------- ② zip 通道：落位 + 内容保真 ----------
        code, doc2, raw = run_json(["scripts/import_trace.py", str(zip_path),
                                    "--traces-root", str(recv_a), "--json"])
        check("zip 接手成功（exit 0）", code == 0 and doc2 and doc2.get("ok"), raw.strip()[-400:])
        check("落位后 session_id 不变（无同名冲突）",
              doc2 and doc2.get("session_id") == sid and not doc2.get("renamed_from"))
        check("trace 逐字节保真（注释与排版不丢）",
              digest(src / f"{sid}.yaml") == digest(recv_a / f"{sid}.yaml"))
        check("报告与证据原件都落位且字节一致",
              (recv_a / f"{sid}.report.md").is_file()
              and digest(src / "evidence" / sid / "log-tail.txt")
              == digest(recv_a / "evidence" / sid / "log-tail.txt"))
        check("知识库版本一致时如实报 match（exit 状态非阻塞）",
              doc2 and doc2.get("kb_rev_state") == "match", json.dumps(doc2.get("kb_rev_note"), ensure_ascii=False))
        check("被引用但没打进包的证据被点名（不静默当成证据齐全）",
              any("never-packed.txt" in str(m.get("path")) for m in doc2.get("missing") or []),
              json.dumps(doc2.get("missing"), ensure_ascii=False))
        check("下游读取端只把 <sid>.yaml 当会话，handoff/ 不被当成一单",
              [p.name for p in recv_a.glob("*.yaml")] == [f"{sid}.yaml"],
              str([p.name for p in recv_a.glob("*.yaml")]))
        check("接管留档：handoff/<sid>.yaml 带 imported 溯源块",
              (recv_a / "handoff" / f"{sid}.yaml").is_file()
              and "imported:" in (recv_a / "handoff" / f"{sid}.yaml").read_text(encoding="utf-8"))

        # ---------- ③ 同一份包再来一次：不重复落位 ----------
        before = sorted(p.name for p in recv_a.rglob("*"))
        code, doc3, raw = run_json(["scripts/import_trace.py", str(zip_path),
                                    "--traces-root", str(recv_a), "--json"])
        check("同一份包重复接手：识别为重复、exit 0",
              code == 0 and doc3 and doc3.get("duplicate_of") == sid, raw.strip()[-300:])
        check("重复接手不在 traces/ 里留下第二份",
              sorted(p.name for p in recv_a.rglob("*")) == before)

        # ---------- ④ md 通道：缺件要分清"未内联"与"丢件" ----------
        code, doc4, raw = run_json(["scripts/import_trace.py", str(md_path),
                                    "--traces-root", str(recv_b), "--json"])
        check("单文件 md 接手成功（exit 0）", code == 0 and doc4 and doc4.get("ok"), raw.strip()[-400:])
        check("md 通道：trace 内容与上家一致",
              digest(src / f"{sid}.yaml") == digest(recv_b / f"{sid}.yaml"))
        miss = {str(m.get("path")): str(m.get("reason")) for m in doc4.get("missing") or []}
        big = [k for k in miss if "big-plog.txt" in k]
        never = [k for k in miss if "never-packed.txt" in k]
        check("md 通道：未内联的大文件缺件原因指向「内联上限」（不是丢件）",
              big and "内联上限" in miss[big[0]], json.dumps(miss, ensure_ascii=False))
        check("md 通道：上家本就没打进包的文件，缺件原因如实说是「没打进包」",
              never and "没打进包" in miss[never[0]], json.dumps(miss, ensure_ascii=False))
        check("md 通道：小文件证据原文落位",
              (recv_b / "evidence" / sid / "log-tail.txt").is_file())
        check("知识库版本不一致时如实报 mismatch 并说明后果",
              doc4.get("kb_rev_state") == "mismatch" and "候选" in str(doc4.get("kb_rev_note")),
              json.dumps(doc4.get("kb_rev_note"), ensure_ascii=False))

        # ---------- ⑤ 同名冲突：改名落位且内部引用一起改写 ----------
        import time
        time.sleep(1.1)   # exported_at 精确到秒：换一份新导出需要它不同
        code, doc5, raw = run_json(["scripts/export_trace.py", sid, "--traces-root", str(src),
                                    "--out", str(out), "--json"])
        check("二次导出成功（换一份 exported_at，构成「另一份包」）",
              code == 0 and doc5 and doc5.get("ok"), raw.strip()[-300:])
        code, doc6, raw = run_json(["scripts/import_trace.py", doc5["zip"],
                                    "--traces-root", str(recv_a), "--json"])
        new_sid = f"{sid}-imported-1"
        check("同名冲突：落成 <sid>-imported-1 而不是覆盖",
              code == 0 and doc6 and doc6.get("session_id") == new_sid
              and doc6.get("renamed_from") == sid, raw.strip()[-300:])
        t2 = load_text((recv_a / f"{new_sid}.yaml").read_text(encoding="utf-8"))
        check("改名后 trace 内部 session_id / 证据路径 / report_file 一起改写",
              t2.get("session_id") == new_sid
              and all(f"evidence/{new_sid}/" in f for f in t2["trace"][0]["evidence"]["files"])
              and t2.get("report_file") == f"{new_sid}.report.md",
              json.dumps({"sid": t2.get("session_id"), "rep": t2.get("report_file"),
                          "ev": t2["trace"][0]["evidence"]["files"]}, ensure_ascii=False))
        # evidence.files 是**相对仓库根**的路径（`traces/evidence/<sid>/…`，与面板 openEvidence 同一口径），
        # 所以按"仓库根"拼，不是按 traces/ 拼——拼错了这条断言会永远假绿。
        packed = [f for f in t2["trace"][0]["evidence"]["files"] if "never-packed" not in f]
        check("改名后证据目录跟着改名，且指向的文件真的在",
              len(packed) == 2 and all((recv_a.parent / f).is_file() for f in packed),
              json.dumps([(f, (recv_a.parent / f).is_file()) for f in packed], ensure_ascii=False))
        check("原单不受影响（两份都在）",
              (recv_a / f"{sid}.yaml").is_file() and (recv_a / f"{new_sid}.yaml").is_file())

        # ---------- ⑥ 全新机器（traces/ 还不存在）——最常见的那个场景 ----------
        recv_new = tmp / "recv-fresh" / "traces"    # 注意：不预先创建
        code, docN, raw = run_json(["scripts/import_trace.py", doc5["zip"],
                                    "--traces-root", str(recv_new), "--json"])
        check("全新机器（traces/ 不存在）也能落位——收 gitignore 的运行时件由脚本自己建",
              code == 0 and docN and docN.get("ok") and (recv_new / f"{sid}.yaml").is_file(),
              raw.strip()[-300:])

        # ---------- ⑦ 拒收路径 ----------
        code, _doc, _raw = run_json(["scripts/import_trace.py", doc5["zip"],
                                     "--traces-root", str(recv_a), "--no-rename", "--json"])
        check("--no-rename 遇同名冲突：拒绝落位（exit 4）", code == 4, f"exit={code}")
        junk = tmp / "junk"
        junk.mkdir(exist_ok=True)
        (junk / "random.txt").write_text("not a handoff package", encoding="utf-8")
        code, _doc, _raw = run_json(["scripts/import_trace.py", str(junk), "--json"])
        check("非法包（无 handoff/）拒收（exit 2）", code == 2, f"exit={code}")
        code, doc7, raw = run_json(["scripts/import_trace.py", doc5["zip"],
                                    "--traces-root", str(recv_b), "--dry-run", "--json"])
        check("--dry-run 只校验不落位",
              code == 0 and doc7 and doc7.get("dry_run")
              and not (recv_b / f"{new_sid}.yaml").exists())

        # ---------- ⑨ 面板那种调用形状：cwd = 检出、传相对路径、不给 traces 根 ----------
        # 面板就是把 `traces/<条目名>.yaml` 交给脚本的。只按进程 cwd 解析路径的实现在 worktree /
        # 别的目录下会以 `x.yaml.yaml` 收场（实测踩过），这条就是钉住"两处都找"。
        code, docQ, raw = run_json(["scripts/export_trace.py", f"traces/{sid}.yaml",
                                    "--out", str(tmp / "panel-out"), "--json"], cwd=str(src.parent))
        check("面板调用形状（相对路径 + cwd=检出 + 不给 traces 根）能导出",
              code == 0 and docQ and docQ.get("ok") and docQ.get("session_id") == sid,
              raw.strip()[-300:])
        code, _docR, _raw = run_json(["scripts/export_trace.py", "traces/does-not-exist.yaml", "--json"],
                                     cwd=str(src.parent))
        check("相对路径找不到时给出试过的位置（不是 x.yaml.yaml 这种看不懂的错）", code == 2, f"exit={code}")

        # ---------- ⑩ md 通道的截断检测 ----------
        # 文本通道（邮件正文、IM）有长度上限，被截断的证据比没有证据更危险：它看起来是齐的。
        # 这里把 md 里某条证据声明的字节数改大（模拟"声明了但没送达那么多"），落位要成功但要点名。
        md_orig = md_path.read_text(encoding="utf-8")
        import re as _re
        m_ev = _re.search(r'(<!-- BEGIN EVIDENCE path="[^"]*log-tail\.txt" bytes=")(\d+)(")', md_orig)
        check("md 投影里带上了每条证据的声明字节数（截断检测的前提）", bool(m_ev),
              md_orig[:120])
        if m_ev:
            md_cut = tmp / "handoff-truncated.md"
            md_cut.write_text(md_orig[:m_ev.start(2)] + str(int(m_ev.group(2)) + 100000)
                              + md_orig[m_ev.end(2):], encoding="utf-8")
            recv_cut = tmp / "recv-cut" / "traces"
            code, docT, raw = run_json(["scripts/import_trace.py", str(md_cut),
                                        "--traces-root", str(recv_cut), "--json"])
            trunc = [t.get("path") for t in (docT.get("truncated") or [])] if docT else []
            check("md 截断：仍落位（非致命），但要点名说它可能不完整",
                  code == 0 and any("log-tail.txt" in str(x) for x in trunc)
                  and (recv_cut / "evidence" / sid / "log-tail.txt").is_file(),
                  json.dumps(trunc, ensure_ascii=False) + raw.strip()[-200:])

        # ---------- ⑧ 文件名与 session_id 不同的历史单 ----------
        # 面板传过来的就是**文件名**（它按 traces/*.yaml 的条目名走），而 trace 顶层的 session_id
        # 是另一件事，两者在历史单里可能不同。若按文件名命名包，接收侧会看到"包里的文件名与 trace
        # 里的 session_id 不一致"，导出的清单还会把改名读成丢件（实测踩过一次）。
        odd_root = tmp / "odd" / "traces"
        odd_dir = odd_root / "evidence" / "mismatch-001"
        odd_dir.mkdir(parents=True, exist_ok=True)
        (odd_root / "odd-file-name.yaml").write_text(
            FIXTURE_TRACE.format(sid="mismatch-001", kb_rev=rev_a), encoding="utf-8")
        (odd_dir / "log-tail.txt").write_text("FIXTURE_ERR_0001 tail\n", encoding="utf-8")
        code, docO, raw = run_json(["scripts/export_trace.py", "odd-file-name",
                                    "--traces-root", str(odd_root), "--out", str(tmp / "odd" / "out"),
                                    "--json"])
        check("文件名与 session_id 不同：包按 session_id 命名，并把差异说出来",
              code == 0 and docO and docO.get("session_id") == "mismatch-001"
              and any("session_id" in w for w in (docO.get("warnings") or [])),
              json.dumps(docO.get("warnings") if docO else raw[-300:], ensure_ascii=False))
        recv_odd = tmp / "odd-recv" / "traces"
        code, docP, raw = run_json(["scripts/import_trace.py", docO["zip"],
                                    "--traces-root", str(recv_odd), "--json"])
        # 断言**只**盯"改名被误读成丢件"这一件事：这条夹具的 trace 有意引用了两个没打进包的文件，
        # 它们本就该出现在缺件清单里（那是诚实退化），不该一起断言成空
        odd_missing = [str(m.get("path")) for m in (docP.get("missing") or [])]
        check("文件名与 session_id 不同：落位后文件名归一到 session_id，且改名不被误读成丢件",
              code == 0 and (recv_odd / "mismatch-001.yaml").is_file()
              and not [m for m in odd_missing if m.endswith(".yaml")],
              json.dumps(odd_missing, ensure_ascii=False))

        # ---------- ⑫ 重复导出：撤掉的文件不能留在包里 ----------
        # 不清旧树的后果不只是"清单对不上"：上家撤掉的内容（比如发现贴错了要撤的证据）会继续随包
        # 发出去，而清单里不列它——等于把已经决定不发的内容又发了一遍。
        rx_sid = "reexport-001"
        rx = make_fixture_root(tmp, rx_sid, kb_rev=rev_a, big=True)
        rout = tmp / "rx-out"
        code, _d1, raw = run_json(["scripts/export_trace.py", rx_sid, "--traces-root", str(rx),
                                   "--out", str(rout), "--json"])
        check("重复导出：首次导出成功", code == 0)
        with __import__("zipfile").ZipFile(rout / f"handoff-{rx_sid}.zip") as z:
            before = sorted(n for n in z.namelist() if not n.endswith("/"))
        check("重复导出：首次包里含那个大证据文件", any("big-plog.txt" in n for n in before), str(before))
        # 上家撤掉它（源里删掉），再导一次
        (rx / "evidence" / rx_sid / "big-plog.txt").unlink()
        code, _d2, raw = run_json(["scripts/export_trace.py", rx_sid, "--traces-root", str(rx),
                                   "--out", str(rout), "--json"])
        check("重复导出：撤掉文件后再导成功", code == 0, raw.strip()[-300:])
        with __import__("zipfile").ZipFile(rout / f"handoff-{rx_sid}.zip") as z:
            after = sorted(n for n in z.namelist() if not n.endswith("/"))
        tree_now = sorted(str(x.relative_to(rout / rx_sid)).replace("\\", "/")
                          for x in (rout / rx_sid).rglob("*") if x.is_file())
        man_now = load_text((rout / rx_sid / "handoff" / f"{rx_sid}.yaml").read_text(encoding="utf-8"))
        listed_now = sorted(f["path"] for f in man_now["contents"]["files"])
        check("重复导出：撤掉的文件不再出现在 zip 里（否则等于把决定不发的内容又发一遍）",
              not any("big-plog.txt" in n for n in after), str(after))
        check("重复导出：清单 == 树 == zip（三方一致）",
              listed_now == tree_now == after, json.dumps({"listed": listed_now, "tree": tree_now, "zip": after}, ensure_ascii=False)[:400])
        # 拒绝清理来路不明的目录（--out 可以指到任何地方，不能对它 rmtree）
        foreign = tmp / "rx-foreign" / rx_sid
        foreign.mkdir(parents=True, exist_ok=True)
        (foreign / "keepme.txt").write_text("别删我", encoding="utf-8")
        code, _d3, _raw = run_json(["scripts/export_trace.py", rx_sid, "--traces-root", str(rx),
                                    "--out", str(tmp / "rx-foreign"), "--json"])
        check("重复导出：产出目录已存在但不像上次产出时拒收（不 rmtree 来路不明的目录）",
              code == 3 and (foreign / "keepme.txt").is_file(), f"exit={code}")

        # ---------- ⑦ 本机真 trace 的端到端 ----------
        if not args.fixtures_only:
            print("\n[交接包 · 本机真 trace（traces/ 是 gitignore 的运行时件，CI 检出里没有）]")
            traces_root = resolve_traces(REPO)
            real = sorted(traces_root.glob("*.yaml"))
            if not real:
                print(f"  — 跳过：{traces_root} 下没有 trace（CI 检出的常态，不是失败）")
            else:
                # 挑"事件最多"的那条，信息量最大的一份做端到端
                best, best_n = None, -1
                for p in real:
                    try:
                        d = load_text(p.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    n = len(d.get("trace") or []) if isinstance(d, dict) else -1
                    if n > best_n:
                        best, best_n = p, n
                rsid = str(load_text(best.read_text(encoding="utf-8")).get("session_id") or best.stem)
                rrecv = tmp / "real-recv" / "traces"
                rrecv.mkdir(parents=True, exist_ok=True)
                rout = tmp / "real-exports"
                code, doc8, raw = run_json(["scripts/export_trace.py", rsid, "--traces-root",
                                            str(traces_root), "--out", str(rout),
                                            "--intent", "continue", "--json"])
                check(f"真 trace 导出（{rsid}）", code == 0 and doc8 and doc8.get("ok"),
                      raw.strip()[-400:])
                if doc8 and doc8.get("ok"):
                    code, doc9, raw = run_json(["scripts/import_trace.py", doc8["zip"],
                                                "--traces-root", str(rrecv), "--json"])
                    src_doc = load_text((traces_root / f"{rsid}.yaml").read_text(encoding="utf-8"))
                    dst_doc = load_text((rrecv / f"{rsid}.yaml").read_text(encoding="utf-8"))
                    check("真 trace 接手后可读，且关键字段与上家逐个一致",
                          code == 0 and dst_doc.get("status") == src_doc.get("status")
                          and dst_doc.get("current_step") == src_doc.get("current_step")
                          and dst_doc.get("active_case") == src_doc.get("active_case")
                          and dst_doc.get("excluded_cases") == src_doc.get("excluded_cases")
                          and len(dst_doc.get("trace") or []) == len(src_doc.get("trace") or []),
                          raw.strip()[-300:])
                    ref_files = ((dst_doc.get("trace") or [{}])[0]
                                 .get("evidence", {}) or {}).get("files", []) or []
                    ok_files = all((rrecv.parent / f).is_file() for f in ref_files)
                    check(f"真 trace 接手后证据文件按 trace 里的相对路径可读（{len(ref_files)} 个）",
                          bool(ref_files) and ok_files,
                          json.dumps([(f, (rrecv.parent / f).is_file()) for f in ref_files],
                                     ensure_ascii=False))
                    check("真 trace 的 hash 与上家一致（除改名外不改内容）",
                          digest(traces_root / f"{rsid}.yaml") == digest(rrecv / f"{rsid}.yaml"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return finish()


def finish() -> int:
    """收尾：末行给一个**稳定的**判据串。

    为什么要稳定：这张检查是 `EV-2026-079` 的 `predicted_effect.measure`，`ev_measure.py --run`
    按 `expect_stdout` 机械判定。断言条数会随用例增减，所以判据串不能是数字（写死条数会让
    加一条断言就红），而是与 `panel_render_check.js` 同款的收尾语。
    """
    if FAILS:
        print(f"\n有 {len(FAILS)} 项失败（通过 {len(PASSES)}/{len(PASSES) + len(FAILS)}）：")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print(f"\n全部通过（{len(PASSES)} 项）")
    return 0


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
