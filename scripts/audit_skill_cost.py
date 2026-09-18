#!/usr/bin/env python3
# audit_skill_cost.py —— skill 上下文成本的确定性审计（常驻 / 按需 / 重复面）
#
# 为什么有它：skill 的成本此前只在两处被"手工算过"——skill-review 的静态审计是**内联
# heredoc**（每次重算、无趋势、易抄错），而"改了 skill 之后常驻/正文变多重了"这个问题
# 没有第三处能回答。本脚本把同一套量具固定下来：任何一次 skill 改动之后跑一次，前后可比。
#
# 量的三层（与机制文档的分层一致）：
#   ① 常驻面：每个会话开始时注入的字节——CLAUDE.md + AGENTS.md + 各 skill frontmatter 的
#      description。**只有没标 `disable-model-invocation: true` 的 skill 才被注入**，
#      所以这个标记是常驻成本的一个闸门，脚本如实分档列。
#   ② 按需面：SKILL.md 正文 + 该 skill 自己的 references/（触发后才读）。
#   ③ 重复面：同一行文本出现在 ≥2 个 skill 里的情况（跨 skill 复制的规则块）——它让
#      改一处漏三处，也让每次加载都多付一遍。
#
# 口径（诚实标注）：字节数是实测；"≈tok" 一列用 bytes/3.4 折算，与索引/EV 卡的既有口径
#   一致，**是估算不是计费**——只要真正的账单，用 `scripts/session_cost.mjs` 从 DSH 会话
#   日志里取提供方 usage。换算尺子本身有两套说法（bytes/3.4 与 len/2.6），本脚本只用前者
#   并把它写在输出里；混用两把尺会让两次审计的数字不可比。
#
# --check（固定面棘轮）：比对上 `metrics/gates.yaml` 的 `token_budget.baseline`，三态退出码
#   （与 metrics_health.py / ev_measure.py 同形）：
#     0  两项都在基线内（且都评过）——本期确实没涨
#     1  有一项超基线——固定面涨了，按报告的差值处置
#     2  判据没被评估（gates.yaml 缺 token_budget 节 / 解析失败）——**结论不可用**
#   为什么要有 2：「没涨」与「没被检查」必须是两件事。本仓已有一次假绿教训——判据读到坏配置
#   时报了 clean。棘轮只回答"比上次记录时涨了没有"，不回答"这个数是否合理"。
#
# 用法：
#   python3 scripts/audit_skill_cost.py [--root .] [--skill <name>] [--dups] [--json]
#   python3 scripts/audit_skill_cost.py --check [--gates metrics/gates.yaml]   # 棘轮三态

import argparse
import glob
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

BYTES_PER_TOKEN = 3.4          # 与索引/EV 卡一致的口径（估算）
DUP_MIN_CHARS = 30             # 计入"重复行"的最小长度（避免表格分隔线与短标签）
NOISE = re.compile(r"^[\s|:\-`>*#]+$")
# 强制词密度与输出必填段数：skill-review 的 A 静态审计用它看"规则是否密到挤占注意力"。
# 放在脚本里而不是让它每次手抄一段 heredoc——同一把尺、可对照趋势。
MODAL = re.compile(r"必须|禁止|不得|一律|始终|绝不")
OUTPUT_SEGMENT = re.compile(r"^\d+\.\s+\*\*", re.M)


def tok(size):
    return round(size / BYTES_PER_TOKEN)


def read_text(path):
    return Path(path).read_text(encoding="utf-8")


def frontmatter(text):
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    return m.group(1) if m else ""


def description_bytes(fm):
    """frontmatter 里 description 的字节数；解析失败退化为按行抓取（如实计 0）。"""
    try:
        doc = yaml.safe_load(fm) or {}
    except Exception:
        doc = {}
    desc = doc.get("description")
    if isinstance(desc, str):
        return len(desc.encode("utf-8")), desc
    # 退化：从 description: 起到下一个顶层键
    m = re.search(r"^description:\s*(.*?)(?=^[a-zA-Z_-]+:|\Z)", fm, re.S | re.M)
    frag = (m.group(1) if m else "").strip()
    return len(frag.encode("utf-8")), frag


def skill_rows(root):
    rows = []
    for skill_md in sorted(glob.glob(str(root / "skills" / "*" / "SKILL.md"))):
        text = read_text(skill_md)
        fm = frontmatter(text)
        try:
            meta = yaml.safe_load(fm) or {}
        except Exception:
            meta = {}
        name = meta.get("name") or Path(skill_md).parent.name
        desc_b, _ = description_bytes(fm)
        total_b = len(text.encode("utf-8"))
        refs = sorted(glob.glob(str(Path(skill_md).parent / "references" / "*")))
        ref_bytes = sum(Path(p).stat().st_size for p in refs if Path(p).is_file())
        # 强制词密度 / 输出必填段数按 SKILL.md 正文 + 本地 references 一起算（触发后两者都会进上下文）
        corpus = text + "".join(read_text(p) for p in refs if Path(p).is_file())
        modal = len(MODAL.findall(corpus))
        corpus_tok = max(1, tok(len(corpus.encode("utf-8"))))
        rows.append({
            "skill": name,
            "resident": not bool(meta.get("disable-model-invocation")),
            "desc_bytes": desc_b,
            "body_bytes": max(0, total_b - len(fm.encode("utf-8"))),
            "total_bytes": total_b,
            "refs": len(refs),
            "ref_bytes": ref_bytes,
            "modal": modal,
            "modal_per_ktok": round(1000 * modal / corpus_tok, 1),
            "output_segments": len(OUTPUT_SEGMENT.findall(corpus)),
            "path": str(Path(skill_md).relative_to(root)).replace("\\", "/"),
        })
    return rows


def resident_total(root, rows):
    parts = []
    for rel in ("CLAUDE.md", "AGENTS.md"):
        p = root / rel
        if p.exists():
            parts.append((rel, p.stat().st_size))
    for r in rows:
        if r["resident"]:
            parts.append((f"skills/{r['skill']}/SKILL.md description", r["desc_bytes"]))
    return parts


def duplicate_lines(root, rows, min_chars=DUP_MIN_CHARS):
    """同一行文本出现在 ≥2 个 skill 里的情况（跨 skill 复制的规则块）。"""
    index = defaultdict(set)
    size = {}
    owner = defaultdict(set)
    for r in rows:
        for rel in [r["path"]] + sorted(
            str(Path(p).relative_to(root)).replace("\\", "/")
            for p in glob.glob(str(root / "skills" / r["skill"] / "references" / "*"))
            if Path(p).is_file()
        ):
            path = root / rel
            if not path.is_file():
                continue
            text = read_text(path)
            # frontmatter 的键行不算"规则块重复"（disable-model-invocation 之类出现在
            # 多个 skill 是机制本身，不是复制粘贴的规则）
            body = re.sub(r"^---\r?\n.*?\r?\n---\r?\n", "", text, count=1, flags=re.S)
            for raw in body.split("\n"):
                line = re.sub(r"\s+", " ", raw).strip()
                if len(line) < min_chars or NOISE.match(line):
                    continue
                index[line].add(rel)
                size[line] = max(size.get(line, 0), len(raw.encode("utf-8")))
                owner[line].add(r["skill"])
    groups = []
    for line, files in index.items():
        skills = owner[line]
        if len(skills) >= 2:
            groups.append({
                "line": line, "skills": sorted(skills), "files": sorted(files),
                "bytes_per_copy": size[line],
                "redundant_bytes": size[line] * (len(files) - 1),
            })
    groups.sort(key=lambda g: -g["redundant_bytes"])
    return groups


def load_token_budget(gates_path):
    """读 gates.yaml 的 token_budget 节。返回 (budget, why)：budget 为 None 时 why 说明原因。"""
    try:
        doc = yaml.safe_load(read_text(gates_path)) or {}
    except FileNotFoundError:
        return None, f"读不到 {gates_path}"
    except Exception as e:
        return None, f"{gates_path} 解析失败：{e}"
    budget = doc.get("token_budget")
    if not isinstance(budget, dict) or not isinstance(budget.get("baseline"), dict):
        return None, f"{gates_path} 里没有 token_budget.baseline 节"
    return budget, ""


def run_check(root, measured, gates_path):
    """固定面棘轮三态。measured = {'resident_total_bytes':…, 'skill_body_total_bytes':…}"""
    budget, why = load_token_budget(gates_path)
    print("=== 固定面棘轮（基线：gates.yaml 的 token_budget.baseline）===")
    if budget is None:
        print(f"  判据没有被评估：{why}")
        print("  结论不可用——「没涨」与「没被检查」是两件事。")
        return 2
    base = budget["baseline"]
    ratio = float(budget.get("tolerance_ratio", 1.0))
    labels = {
        "resident_total_bytes": "常驻合计（每个会话都付）",
        "skill_body_total_bytes": "按需正文合计（触发才读）",
    }
    printed = []
    violated = []
    unevaluated = []
    for key, label in labels.items():
        if key not in base:
            unevaluated.append(f"{label}：基线缺 {key}")
            continue
        cur, b = measured[key], int(base[key])
        limit = b * ratio
        over = cur - limit
        mark = "✓" if cur <= limit else "✗"
        print(f"  {mark} {label:<22} {cur:>9,} B ≈{tok(cur):>7} tok   基线 {b:,}  "
              f"容差 {ratio:.2f}  {'超 ' + format(round(over), ',') + ' B ≈' + format(tok(over), ',') + ' tok' if over > 0 else ''}")
        printed.append(cur <= limit)
        if over > 0:
            violated.append(f"{label} 超基线 {round(over):,} B ≈{tok(over):,} tok")
    total = len(printed) + len(unevaluated)
    print(f"  判据覆盖面 {len(printed)}/{total} 条已评估"
          + (f"；未评估：{'；'.join(unevaluated)}" if unevaluated else ""))
    if unevaluated:
        return 2
    if violated:
        print("  处置：固定面只允许变小（棘轮）。")
        print(f"  要放行这次放大：改 {gates_path} 的 token_budget.baseline（连 recorded_at 一起）并在 PR 里写明理由。")
        print("  先看能不能省回去：--dups 看重复面；常驻项里 skill 的 description 与根指令各占多少见上面清单。")
        return 1
    print(f"  基线记录于 {base.get('recorded_at', '—')}；棘轮只回答「比那次涨了没有」。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="skill 上下文成本审计（常驻 / 按需 / 重复面）")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--skill", default="", help="只看某个 skill（重复面仍按全库算）")
    ap.add_argument("--dups", action="store_true", help="列出重复行明细")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="固定面棘轮：比对上 gates.yaml 的 token_budget.baseline（三态退出码）")
    ap.add_argument("--gates", type=Path, default=None, help="判据数据文件（默认 <root>/metrics/gates.yaml）")
    args = ap.parse_args()
    root = args.root.resolve()

    rows = skill_rows(root)
    if args.skill:
        rows = [r for r in rows if r["skill"] == args.skill]
        if not rows:
            print(f"没有这个 skill: {args.skill}")
            sys.exit(1)
    all_rows = skill_rows(root)
    parts = resident_total(root, all_rows)
    dups = duplicate_lines(root, all_rows)

    if args.check:
        measured = {
            "resident_total_bytes": sum(b for _, b in parts),
            "skill_body_total_bytes": sum(r["body_bytes"] for r in all_rows),
        }
        gates_path = args.gates or (root / "metrics" / "gates.yaml")
        sys.exit(run_check(root, measured, gates_path))

    if args.json:
        print(json.dumps({
            "bytes_per_token": BYTES_PER_TOKEN,
            "resident": [{"what": w, "bytes": b, "tok": tok(b)} for w, b in parts],
            "resident_total_bytes": sum(b for _, b in parts),
            "skills": rows,
            "duplicate_groups": dups,
        }, ensure_ascii=False, indent=1))
        return

    print("=== ① 常驻面（每个会话注入一次；与「这次用不用得上」无关）===")
    for what, b in parts:
        mark = "" if what in ("CLAUDE.md", "AGENTS.md") else "  (未标 disable-model-invocation 才注入)"
        print(f"  {what:<52} {b:>7} B  ≈{tok(b):>6} tok{mark}")
    total = sum(b for _, b in parts)
    print(f"  {'常驻合计':<52} {total:>7} B  ≈{tok(total):>6} tok")

    print("\n=== ② 按需面（触发后才读；强制词密度与输出段数按 SKILL.md + 本地 references 算）===")
    print(f"  {'skill':<20}{'常驻?':>6}{'desc':>8}{'正文':>9}{'本地 refs':>18}{'≈tok':>8}{'强制词/ktok':>13}{'输出段':>8}")
    for r in rows:
        print(f"  {r['skill']:<20}{('是' if r['resident'] else '否'):>6}"
              f"{r['desc_bytes']:>8}{r['body_bytes']:>9}"
              f"{str(r['refs']) + ' 文件/' + str(r['ref_bytes']) + 'B':>18}"
              f"{tok(r['body_bytes'] + r['ref_bytes']):>8}{r['modal_per_ktok']:>13}{r['output_segments']:>8}")
    body = sum(r["body_bytes"] for r in rows)
    print(f"  {'合计':<20}{'':>6}{'':>8}{body:>9}{'':>18}{tok(body + sum(r['ref_bytes'] for r in rows)):>8}")

    print(f"\n=== ③ 重复面（同一行出现在 ≥2 个 skill；≥{DUP_MIN_CHARS} 字符）===")
    if not dups:
        print("  无跨 skill 重复行")
    else:
        print(f"  {len(dups)} 组，冗余合计 {sum(g['redundant_bytes'] for g in dups)} B "
              f"≈{tok(sum(g['redundant_bytes'] for g in dups))} tok（= 每次加载多付的一份）")
        for g in dups[:8]:
            print(f"    {g['redundant_bytes']:>5} B × {len(g['files'])} 份  [{', '.join(g['skills'])}]"
                  f"  {g['line'][:70]}")
        if args.dups:
            print("\n  --- 全部重复行 ---")
            for g in dups:
                print(f"\n  {g['redundant_bytes']} B  ×{len(g['files'])}  {' / '.join(g['files'])}")
                print(f"    {g['line']}")

    print(f"\n口径：字节数为实测；≈tok = 字节/{BYTES_PER_TOKEN}（估算，与索引/EV 卡同尺）。"
          f"\n要真实账单（提供方 usage）用 scripts/session_cost.mjs；两处口径不要混用。")


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
