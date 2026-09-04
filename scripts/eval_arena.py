#!/usr/bin/env python3
# eval_arena.py —— 元层 eval 台工具（机制决议 EV-2026-013）
#
# WikiSkill 式门控的数据/评分侧：候选改动（triage/quickly_check/case 等检索路由层
# 组件）在 held-out selection 池上 baseline vs candidate 重放对照，严格提升才接受，
# 否则回滚；结果留影响账本。设计文档 docs/evolution-eval-arena.md。
#
# 目录（本地运行件，gitignore）：.s2-replay/arena/
#   pool-*.yaml         池清单：{name, split, issues:[{id, expected_ns, category,
#                       fix_ref, held_out}]}
#   stats-*.yaml        --stats 聚合输出
#   impact.yaml         --gate 影响账本（append-only）
# 单 issue 评分复用 .s2-replay/<issue>.result.yaml（S2 result schema：
# namespace/category/hit_case/rc_match/route）。
#
# 用法：
#   python3 scripts/eval_arena.py --pool .s2-replay/arena/pool-val.yaml
#       校验池文件
#   python3 scripts/eval_arena.py --stats .s2-replay/arena/pool-val.yaml
#       聚合池内已有 result 的 issue → stats（命中/路由/结论一致，带分母）
#   python3 scripts/eval_arena.py --gate --baseline <stats-a.yaml> --candidate <stats-b.yaml> \
#       [--component triage:xxx] [--candidate-ref EV-2026-014] [--note ...]
#       对照判定（命中↑且路由/结论不↓，或路由↑且命中/结论不↓ → accept；否则 reject），
#       追加影响账本 impact.yaml
#
# 口径纪律：分数带分母；source: issue-replay；gate 判定是数据门槛，不替代人闸
# （dual 级改动门控通过后仍按 kb/high-risk 双签）。

import argparse
import sys
from datetime import datetime
from pathlib import Path

import yaml

ARENA_SUBDIR = ".s2-replay/arena"
S2_RESULT_REL = ".s2-replay/{}.result.yaml"


def pool_path(root, arg):
    p = Path(arg)
    if not p.is_absolute():
        p = root / p
    return p


def load(path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"读取失败 {path}: {e}", file=sys.stderr)
        return None


def cmd_pool(root, pool_file):
    pool = load(pool_file)
    if not isinstance(pool, dict) or not isinstance(pool.get("issues"), list):
        print("池文件结构错误：需 {name, split, issues:[{id, expected_ns, category, fix_ref, held_out}]}",
              file=sys.stderr)
        return 1
    required = {"id", "expected_ns", "fix_ref"}
    bad = []
    for it in pool["issues"]:
        miss = required - set(it)
        if miss:
            bad.append((it.get("id"), sorted(miss)))
    if bad:
        print("池校验失败：", bad, file=sys.stderr)
        return 1
    print(f"池 {pool.get('name')}（split={pool.get('split')}）: {len(pool['issues'])} 条，校验通过")
    return 0


def cmd_stats(root, pool_file):
    pool = load(pool_file)
    if not pool:
        return 1
    stats = {"pool": pool.get("name"), "split": pool.get("split"),
             "source": "issue-replay", "generated": datetime.now().isoformat(timespec="minutes"),
             "metrics": {}}
    n_route = n_route_ok = n_hit = n_hit_ok = n_rc = n_rc_ok = 0
    missing = []
    for it in pool["issues"]:
        rp = root / S2_RESULT_REL.format(it["id"])
        if not rp.exists():
            missing.append(it["id"])
            continue
        r = load(rp) or {}
        expected_ns = it.get("expected_ns", "")
        route = str(r.get("route") or "")
        route_ok = (route == "ok") or (expected_ns and expected_ns in str(r.get("namespace") or ""))
        hit_ok = bool(r.get("hit_case"))
        rc = r.get("rc_match")
        n_route += 1
        n_route_ok += int(route_ok)
        n_hit += 1
        n_hit_ok += int(hit_ok)
        if rc is not None:
            n_rc += 1
            n_rc_ok += int(bool(rc))
    stats["issues_total"] = len(pool["issues"])
    stats["issues_scored"] = n_hit
    stats["missing_results"] = missing
    stats["metrics"]["route_ok"] = {"n": n_route, "ok": n_route_ok,
                                    "rate": round(n_route_ok / n_route, 3) if n_route else None}
    stats["metrics"]["hit"] = {"n": n_hit, "ok": n_hit_ok,
                               "rate": round(n_hit_ok / n_hit, 3) if n_hit else None}
    stats["metrics"]["rc_match"] = {"n": n_rc, "ok": n_rc_ok,
                                    "rate": round(n_rc_ok / n_rc, 3) if n_rc else None}
    out = pool_file.parent / f"stats-{pool.get('name', 'pool')}.yaml"
    out.write_text(yaml.safe_dump(stats, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"== stats：{stats['issues_scored']}/{stats['issues_total']} 条已评分 ==")
    if missing:
        print(f"  缺 result（未跑）: {missing}")
    for k, m in stats["metrics"].items():
        print(f"  {k}: {m['ok']}/{m['n']}"
              + (f"（{m['rate']:.0%}）" if m["rate"] is not None else "（无样本）"))
    print(f"  写入 {out}")
    return 0


def _rate(m):
    return m.get("rate") if isinstance(m, dict) else None


def cmd_gate(root, baseline_file, candidate_file, component, cand_ref, note):
    b = load(baseline_file)
    c = load(candidate_file)
    if not b or not c:
        return 1
    bm, cm = b.get("metrics", {}), c.get("metrics", {})
    hit_b, hit_c = _rate(bm.get("hit")), _rate(cm.get("hit"))
    route_b, route_c = _rate(bm.get("route_ok")), _rate(cm.get("route_ok"))
    rc_b, rc_c = _rate(bm.get("rc_match")), _rate(cm.get("rc_match"))

    def ge(a, x):
        return a is None or x is None or a >= x

    hit_up = hit_c is not None and hit_b is not None and hit_c > hit_b
    route_up = route_c is not None and route_b is not None and route_c > route_b
    no_regr = ge(hit_c, hit_b) and ge(route_c, route_b) and ge(rc_c, rc_b)
    accept = no_regr and (hit_up or route_up)
    decision = "accept" if accept else "reject"
    record = {
        "ts": datetime.now().isoformat(timespec="minutes"),
        "candidate_ref": cand_ref or "",
        "component": component or "",
        "baseline": {"file": str(baseline_file),
                     "hit": _rate(bm.get("hit")), "route_ok": _rate(bm.get("route_ok")),
                     "rc_match": _rate(bm.get("rc_match"))},
        "candidate": {"file": str(candidate_file),
                      "hit": _rate(cm.get("hit")), "route_ok": _rate(cm.get("route_ok")),
                      "rc_match": _rate(cm.get("rc_match"))},
        "decision": decision,
        "rule": "golden 无回归（另跑） + val 命中/路由严格提升且其余不降",
        "note": note or "",
    }
    arena = root / ARENA_SUBDIR
    arena.mkdir(parents=True, exist_ok=True)
    imp = arena / "impact.yaml"
    entries = load(imp) if imp.exists() else {"_comment": "arena 影响账本（append-only，EV-2026-013）",
                                              "records": []}
    entries.setdefault("records", []).append(record)
    imp.write_text(yaml.safe_dump(entries, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"== gate 判定：{decision} ==")
    print(f"  baseline: hit={hit_b} route={route_b} rc={rc_b}")
    print(f"  candidate: hit={hit_c} route={route_c} rc={rc_c}")
    print(f"  账本追加 → {imp}")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="元层 eval 台工具（EV-2026-013；docs/evolution-eval-arena.md）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pool", metavar="YAML", help="校验池文件")
    g.add_argument("--stats", metavar="YAML", help="聚合池内 result → stats")
    g.add_argument("--gate", action="store_true", help="baseline vs candidate 门控判定")
    ap.add_argument("--baseline", default="", help="--gate: baseline stats yaml")
    ap.add_argument("--candidate", default="", help="--gate: candidate stats yaml")
    ap.add_argument("--component", default="", help="--gate: 目标组件（如 triage:xxx）")
    ap.add_argument("--candidate-ref", default="", help="--gate: EV 卡/PR 引用")
    ap.add_argument("--note", default="", help="--gate: 备注")
    ap.add_argument("--root", default=".", help="仓库根目录（默认当前目录）")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if args.pool:
        return cmd_pool(root, pool_path(root, args.pool))
    if args.stats:
        return cmd_stats(root, pool_path(root, args.stats))
    return cmd_gate(root, pool_path(root, args.baseline), pool_path(root, args.candidate),
                    args.component, args.candidate_ref, args.note)


if __name__ == "__main__":
    sys.exit(main())
