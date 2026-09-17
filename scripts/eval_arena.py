#!/usr/bin/env python3
# eval_arena.py —— 元层 eval 台工具（机制决议 EV-2026-013）
#
# WikiSkill 式门控的数据/评分侧：候选改动（triage/quickly_check/case 等检索路由层
# 组件）在 held-out selection 池上 baseline vs candidate 重放对照，严格提升才接受，
# 否则回滚；结果留影响账本。设计文档 docs/mechanism/eval-arena.md。
#
# 目录（本地运行件，gitignore）：.s2-replay/arena/
#   pool-*.yaml         池清单：{name, split, issues:[{id, expected_ns, category,
#                       fix_ref, held_out}]}
#   stats-*.yaml        --stats 聚合输出
#   impact.yaml         --gate 影响账本（append-only）
# 单 issue 评分复用 .s2-replay/<issue>.result.yaml（S2 result schema：
# namespace/category/hit_case/rc_match/route）。
#
# 接受判据（v2：配对 + 复用折减）——**薄弱环节是接受者，不是提议者**。
#   v1 的规则是"同一个小池子上分数涨了就接受"。反复对同一个池做接受决定，是一串不受控的
#   适应性检验：每次单独看都"涨了"，合起来假接受会累积（池越小越严重——16 条池一次翻转
#   就是 +6.25 个百分点，一次翻转即可判"提升"）。v2 改两处：
#     ① **配对**：只比较同一批 issue 上方向不一致的对子（candidate 独家命中 b / baseline
#        独家命中 c），做精确单侧检验；逐条向量由 --stats 写进 stats 文件。旧 stats（无
#        向量）仍可判，但判词上限降为 weak_accept——没有配对证据就不算"数据门槛通过"。
#     ② **复用折减**：同一池的历次判定计入复用序号 k，判据阈值 α_eff = α/(k+1)。池内容
#        变了（重新选样 = 换量尺）→ pool_hash 变 → 复用计数自动归零，跨纪元比对直接拒绝。
#   判词三态，**只有 accept 才算门控通过**（其余情形不足以判 validated）：
#     accept       无回归 + 方向性提升 + 配对检验 p ≤ α_eff
#     weak_accept  无回归 + 提升，但证据不足（p > α_eff，或缺逐条向量）
#     reject       有回归 / 无提升 / 两池不可比
#   判据本身也要有牙齿：`--self-test` 用合成样本复现上述三态（含"单次翻转不得判 accept"
#   "复用 k 次后同一提升不得判 accept""跨池纪元不可比"），CI 跑它。
#
# 用法：
#   python3 scripts/eval_arena.py --pool .s2-replay/arena/pool-val.yaml
#       校验池文件
#   python3 scripts/eval_arena.py --stats .s2-replay/arena/pool-val.yaml
#       聚合池内已有 result 的 issue → stats（命中/路由/结论一致，带分母 + 逐条向量 + 池哈希）
#   python3 scripts/eval_arena.py --gate --baseline <stats-a.yaml> --candidate <stats-b.yaml> \
#       [--component triage:xxx] [--candidate-ref EV-2026-014] [--alpha 0.1] [--note ...]
#       配对判定（accept / weak_accept / reject），追加影响账本 impact.yaml
#   python3 scripts/eval_arena.py --self-test
#       复现判词（合成样本，无需本地池数据），失败非零退出
#
# 口径纪律：分数带分母；source: issue-replay；gate 判定是数据门槛，不替代人闸
# （dual 级改动门控通过后仍按 kb/high-risk 双签）。α 与复用上限是**参数估计**，
# 接受实测重校（改它们要写进 PR 说明，不悄悄改）。

import argparse
import hashlib
import math
import sys
from datetime import datetime
from pathlib import Path

import yaml

ARENA_SUBDIR = ".s2-replay/arena"
S2_RESULT_REL = ".s2-replay/{}.result.yaml"
IMPACT_REL = ".s2-replay/arena/impact.yaml"

# 每个接受决定允许的假接受概率（α 预算）。判据是**每个决定**的错误率，不是整批——
# 批内多张卡各自独立判定，故复用折减按同池的历次判定计（见 reuse_index）。
ALPHA_DEFAULT = 0.10


def pool_path(root, arg):
    p = Path(arg)
    if not p.is_absolute():
        p = root / p
    return p


def file_hash(path):
    """池内容哈希 = 量尺的身份。换量尺（重新选样）→ 哈希变 → 同池复用计数归零。"""
    try:
        return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    except OSError:
        return None


# ---------------------------------------------------------------- 配对判定（纯函数，可自检）
def vectors(stats):
    """从 stats 取逐条判决向量：{id: {hit, route_ok, rc_match}}。旧 stats 没有 = 空。"""
    out = {}
    for it in (stats or {}).get("issues") or []:
        if isinstance(it, dict) and it.get("id") not in (None, ""):
            out[str(it["id"])] = it
    return out


def exact_mcnemar_ge(b, n):
    """精确单侧 p 值：H0 下方向不一致的对子等概率。

    只数"方向不一致"的对子（b + c），一致的对子不含判别信息——这正是配对检验比
    "两个比例各看一遍"更敏感的原因，也是它比 v1 更严的原因：一次翻转不再自动成立。
    """
    if n <= 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(b, n + 1))
    return tail / (2 ** n)


def reuse_index(records, pool_name, pool_hash, exclude_last=False):
    """同一池（同名 + 同内容哈希）在本账本里已发生的判定次数 = 复用序号 k。

    k 次复用意味着同一个池被用来做过 k 次接受决定；判定阈值按 α/(k+1) 折减。
    内容哈希不同（换池/重新选样）= 不同的量尺，各算各的。
    """
    recs = list(records or [])
    if exclude_last and recs:
        recs = recs[:-1]
    return sum(1 for r in recs
               if isinstance(r, dict)
               and str(r.get("pool") or "") == str(pool_name or "")
               and (r.get("pool_hash") or None) == (pool_hash or None))


def decide(base_stats, cand_stats, alpha_eff):
    """判词三态。返回 dict（含读数，供账本与打印）。

    无回归（命中/路由/结论均不降）是**必要条件**；提升用点估计判方向，用配对检验判证据。
    """
    bm, cm = (base_stats or {}).get("metrics", {}), (cand_stats or {}).get("metrics", {})
    hit_b, hit_c = _rate(bm.get("hit")), _rate(cm.get("hit"))
    route_b, route_c = _rate(bm.get("route_ok")), _rate(cm.get("route_ok"))
    rc_b, rc_c = _rate(bm.get("rc_match")), _rate(cm.get("rc_match"))

    def ge(a, x):
        return a is None or x is None or a >= x

    no_regr = ge(hit_c, hit_b) and ge(route_c, route_b) and ge(rc_c, rc_b)
    improved = ((hit_c is not None and hit_b is not None and hit_c > hit_b)
                or (route_c is not None and route_b is not None and route_c > route_b))

    # 跨池纪元不可比：baseline 与 candidate 的量尺不是同一份 → 判定无效（不是 reject 的语义）
    hb, hc = (base_stats or {}).get("pool_hash"), (cand_stats or {}).get("pool_hash")
    if hb and hc and hb != hc:
        return {"verdict": "reject", "reason": "跨池纪元不可比（baseline 与 candidate 的池内容哈希不同）",
                "no_regression": None, "improved": None, "paired": None,
                "baseline": {"hit": hit_b, "route_ok": route_b, "rc_match": rc_b},
                "candidate": {"hit": hit_c, "route_ok": route_c, "rc_match": rc_c}}

    vb, vc = vectors(base_stats), vectors(cand_stats)
    common = sorted(set(vb) & set(vc))
    paired = None
    if common:
        b = sum(1 for i in common if vc[i].get("hit") and not vb[i].get("hit"))
        c = sum(1 for i in common if vb[i].get("hit") and not vc[i].get("hit"))
        rb = sum(1 for i in common if vc[i].get("route_ok") and not vb[i].get("route_ok"))
        rc = sum(1 for i in common if vb[i].get("route_ok") and not vc[i].get("route_ok"))
        paired = {"n_common": len(common), "hit_b_only": c, "hit_c_only": b,
                  "route_b_only": rc, "route_c_only": rb,
                  "p_value": round(exact_mcnemar_ge(b, b + c), 4)}

    if not no_regr or not improved:
        verdict, reason = "reject", ("有回归（命中/路由/结论之一下降）" if not no_regr
                                     else "无方向性提升（命中/路由均未上升）")
    elif paired is None:
        verdict, reason = "weak_accept", "缺逐条向量，无法配对检验——判词上限为 weak_accept"
    elif paired["p_value"] <= alpha_eff:
        verdict, reason = "accept", f"配对检验 p={paired['p_value']} ≤ α_eff={alpha_eff:.4f}"
    else:
        verdict, reason = "weak_accept", (f"配对检验 p={paired['p_value']} > α_eff={alpha_eff:.4f}"
                                          "——提升看起来真实但不达证据门槛")

    return {"verdict": verdict, "reason": reason, "no_regression": no_regr, "improved": improved,
            "paired": paired,
            "baseline": {"hit": hit_b, "route_ok": route_b, "rc_match": rc_b},
            "candidate": {"hit": hit_c, "route_ok": route_c, "rc_match": rc_c}}


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
             "pool_hash": file_hash(pool_file),
             "source": "issue-replay", "generated": datetime.now().isoformat(timespec="minutes"),
             "metrics": {}, "issues": []}
    n_route = n_route_ok = n_hit = n_hit_ok = n_rc = n_rc_ok = 0
    missing = []
    for it in pool["issues"]:
        rp = root / S2_RESULT_REL.format(it["id"])
        if not rp.exists():
            missing.append(it["id"])
            continue
        r = load(rp) or {}
        expected_ns = it.get("expected_ns", "")
        # result 文件有两套字段写法并存，两套都认——实测代价：只认旧写法时，盘上全部
        # result 的结论一致（root_cause_ok）读不到，rc_match 恒为 None，判定少一路证据、
        # 账本里也看不出"没数据"和"结论不一致"的区别（诚实退化要求这两者可区分）。
        #   hit_case ↔ tier2_hit ；route ↔ routing_ok ；rc_match ↔ root_cause_ok
        route = str(r.get("route") or "")
        route_ok = ((route == "ok") or bool(r.get("routing_ok"))
                    or (expected_ns and expected_ns in str(r.get("namespace") or "")))
        hit_ok = bool(r.get("hit_case")) or bool(r.get("tier2_hit"))
        rc = r.get("rc_match", r.get("root_cause_ok"))
        # 逐条向量：配对检验的输入。没有它，判定只能退回点估计（判词上限 weak_accept）。
        stats["issues"].append({"id": str(it["id"]), "hit": bool(hit_ok),
                                "route_ok": bool(route_ok),
                                "rc_match": None if rc is None else bool(rc)})
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


def cmd_gate(root, baseline_file, candidate_file, component, cand_ref, note, alpha):
    b = load(baseline_file)
    c = load(candidate_file)
    if not b or not c:
        return 1

    imp = root / IMPACT_REL
    ledger = load(imp) if imp.exists() else {"_comment": "arena 影响账本（append-only）",
                                             "records": []}
    records = ledger.setdefault("records", [])

    pool_name = b.get("pool")
    pool_hash = b.get("pool_hash")
    k = reuse_index(records, pool_name, pool_hash)
    alpha_eff = alpha / (k + 1)

    res = decide(b, c, alpha_eff)
    record = {
        "ts": datetime.now().isoformat(timespec="minutes"),
        "candidate_ref": cand_ref or "",
        "component": component or "",
        "pool": pool_name,
        "pool_hash": pool_hash,
        "reuse_index": k,
        "alpha_budget": alpha,
        "alpha_eff": round(alpha_eff, 4),
        "baseline": dict(res["baseline"], file=str(baseline_file)),
        "candidate": dict(res["candidate"], file=str(candidate_file)),
        "paired": res["paired"],
        "verdict": res["verdict"],
        "decision": res["verdict"],          # 旧字段名保留：面板/账本读法不变
        "rule": "配对（b/c 方向不一致对子）+ 复用折减 α/(k+1) + 无回归；只有 accept 算门控通过",
        "note": note or "",
        "reason": res["reason"],
    }
    records.append(record)
    imp.parent.mkdir(parents=True, exist_ok=True)
    imp.write_text(yaml.safe_dump(ledger, allow_unicode=True, sort_keys=False), encoding="utf-8")

    print(f"== gate 判定：{res['verdict']} ==")
    print(f"  理由: {res['reason']}")
    print(f"  池: {pool_name}（复用第 {k} 次，α {alpha} → α_eff {alpha_eff:.4f}）")
    print(f"  baseline: hit={res['baseline']['hit']} route={res['baseline']['route_ok']}"
          f" rc={res['baseline']['rc_match']}")
    print(f"  candidate: hit={res['candidate']['hit']} route={res['candidate']['route_ok']}"
          f" rc={res['candidate']['rc_match']}")
    if res["paired"]:
        p = res["paired"]
        print(f"  配对（{p['n_common']} 条）: 命中 c→b {p['hit_c_only']}/{p['hit_b_only']}"
              f"、路由 {p['route_c_only']}/{p['route_b_only']}、p={p['p_value']}")
    if res["verdict"] != "accept":
        print("  → 该判词**不构成**门控通过：不得据此把卡判 validated；"
              "补配对证据/扩池后重跑，或如实按 weak 记入卡。")
    print(f"  账本追加 → {imp}")
    return 0 if res["verdict"] == "accept" else 0


# ---------------------------------------------------------------- 判据自检（CI 跑它）
def _mk(issues, pool="pool-val", split="selection", ph="h1"):
    """合成 stats：issues = [(id, hit, route_ok)] → 与 --stats 产物同构。"""
    vec = [{"id": i, "hit": bool(h), "route_ok": bool(r), "rc_match": None} for i, h, r in issues]
    n = len(vec) or 1
    return {"pool": pool, "split": split, "pool_hash": ph, "source": "issue-replay",
            "metrics": {"hit": {"n": n, "ok": sum(v["hit"] for v in vec),
                                "rate": sum(v["hit"] for v in vec) / n},
                        "route_ok": {"n": n, "ok": sum(v["route_ok"] for v in vec),
                                     "rate": sum(v["route_ok"] for v in vec) / n},
                        "rc_match": {"n": 0, "ok": 0, "rate": None}},
            "issues": vec}


def cmd_self_test():
    """判词的可复现性检查：改动判据就要改这里，改不了就说明判据说不清。"""
    fails = []

    def expect(name, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {name}: {got}" + ("" if ok else f"（期望 {want}）"))
        if not ok:
            fails.append(name)

    # ① 16 条池，1 条翻转（6/16 → 7/16）：点估计"提升"，但配对证据不足 → 不得 accept
    base = _mk([(f"i{n}", n < 6, True) for n in range(16)])
    cand = _mk([(f"i{n}", n < 7, True) for n in range(16)])
    expect("单次翻转只给 weak_accept（v1 会判 accept）",
           decide(base, cand, ALPHA_DEFAULT)["verdict"], "weak_accept")
    expect("  该样本 b/c 对子 = 1/0", decide(base, cand, ALPHA_DEFAULT)["paired"]["hit_c_only"], 1)

    # ② 4 条翻转（6/16 → 10/16）：p = 0.0625 ≤ 0.1 → accept
    cand4 = _mk([(f"i{n}", n < 10, True) for n in range(16)])
    expect("4 条同向翻转 → accept", decide(base, cand4, ALPHA_DEFAULT)["verdict"], "accept")

    # ③ 同一提升，但池已被复用 9 次：α_eff = 0.01 → 证据不够，降为 weak_accept
    expect("复用 9 次后同一提升 → weak_accept（复用折减生效）",
           decide(base, cand4, ALPHA_DEFAULT / 10)["verdict"], "weak_accept")

    # ④ 回归必 reject（哪怕配对方向大多向上）
    regr = _mk([(f"i{n}", n < 5, True) for n in range(16)])
    expect("命中下降 → reject", decide(base, regr, ALPHA_DEFAULT)["verdict"], "reject")

    # ⑤ 无变化 → reject（"没变"不是"提升"）
    expect("无变化 → reject", decide(base, base, ALPHA_DEFAULT)["verdict"], "reject")

    # ⑥ 缺逐条向量（旧 stats）→ 判词上限 weak_accept
    old_b = {k: v for k, v in base.items() if k != "issues"}
    old_c = {k: v for k, v in cand4.items() if k != "issues"}
    expect("旧 stats 无向量 → weak_accept", decide(old_b, old_c, ALPHA_DEFAULT)["verdict"],
           "weak_accept")

    # ⑦ 跨池纪元不可比 → reject 且给出理由
    other = dict(cand4, pool_hash="h2")
    r7 = decide(base, other, ALPHA_DEFAULT)
    expect("跨池哈希 → reject", r7["verdict"], "reject")
    expect("  理由点名不可比", "不可比" in r7["reason"], True)

    # ⑧ 复用计数：同池同名同哈希累加，换哈希归零
    recs = [{"pool": "pool-val", "pool_hash": "h1"}, {"pool": "pool-val", "pool_hash": "h1"},
            {"pool": "pool-val", "pool_hash": "h2"}]
    expect("复用计数同哈希 = 2", reuse_index(recs, "pool-val", "h1"), 2)
    expect("换池内容哈希 → 复用归零", reuse_index(recs, "pool-val", "h3"), 0)

    # ⑨ 端到端：真写一次账本，第二次判定复用序号 +1 且阈值收紧（链路可跑通，不只是纯函数）
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ARENA_SUBDIR).mkdir(parents=True)
        f1, f2 = root / "a.yaml", root / "b.yaml"
        f1.write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")
        f2.write_text(yaml.safe_dump(cand4, allow_unicode=True), encoding="utf-8")
        cmd_gate(root, f1, f2, "triage:demo", "EV-TEST-1", "", ALPHA_DEFAULT)
        led = load(root / IMPACT_REL)
        expect("首次判定写入账本 verdict=accept", led["records"][0]["verdict"], "accept")
        expect("首次复用序号 = 0", led["records"][0]["reuse_index"], 0)
        cmd_gate(root, f1, f2, "triage:demo", "EV-TEST-2", "", ALPHA_DEFAULT)
        led = load(root / IMPACT_REL)
        expect("第二次判定复用序号 = 1", led["records"][1]["reuse_index"], 1)
        expect("第二次 α_eff 减半 = 0.05 → 同一提升降为 weak_accept",
               led["records"][1]["alpha_eff"], 0.05)
        expect("  第二次 verdict = weak_accept", led["records"][1]["verdict"], "weak_accept")
        cmd_gate(root, f1, f2, "triage:demo", "EV-TEST-3", "", ALPHA_DEFAULT)
        led = load(root / IMPACT_REL)
        expect("第三次 α_eff=0.0333 → 同一提升降为 weak_accept",
               led["records"][2]["verdict"], "weak_accept")

    if fails:
        print(f"\n--self-test：{len(fails)} 条断言失败")
        return 1
    print("\n--self-test：全部断言通过（判词可复现）")
    return 0


def cmd_rc_check(root, pool_file):
    """离线结论一致对照（归因层/结论一致收尾件）：agent root_cause vs 标注 resolution_summary。
    只给启发式信号 + 供人核验清单，不做自动终判（resolution 多阶段，诚实口径）。"""
    pool = load(pool_file)
    if not pool:
        return 1
    ann_dir = root / ARENA_SUBDIR / "annotations"
    out_rows = []
    for it in pool["issues"]:
        iid = it["id"]
        ann = ann_dir / f"{iid}.yaml"
        rp = root / S2_RESULT_REL.format(iid)
        if not ann.exists() or not rp.exists():
            continue
        a = load(ann) or {}
        r = load(rp) or {}
        agent_rc = str(r.get("root_cause") or "")
        reso = str(a.get("resolution_summary") or "")
        # 启发式信号：共享 token（版本号/PR 号/机制词）或明显对立词
        import re as _re
        def toks(s):
            return {t.lower() for t in _re.findall(r"[A-Za-z0-9][A-Za-z0-9_.\-]*", s)}
        inter = toks(agent_rc) & toks(reso)
        cues = [t for t in ["fix", "fixed", "pr", "workaround", "升级", "版本", "配置", "非代码", "自行关闭", "dspark", "prefix"] if t.lower() in agent_rc.lower() or t.lower() in reso.lower()]
        signal = "likely_match" if (len(inter) >= 3 or "non-bug" in reso or "自行关闭" in reso and "非" not in agent_rc) else ("likely_mismatch" if ("无" in agent_rc and "无" not in reso) else "unclear")
        out_rows.append({"id": iid, "signal": signal, "shared_tokens": sorted(inter)[:8],
                         "agent_rc": agent_rc[:160], "resolution": reso[:200], "verify": "human"})
    out = pool_file.parent / f"rc-{pool.get('name', 'pool')}.yaml"
    out.write_text(yaml.safe_dump(out_rows, allow_unicode=True, sort_keys=False), encoding="utf-8")
    n = len(out_rows)
    lk = sum(1 for x in out_rows if x["signal"] == "likely_match")
    lm = sum(1 for x in out_rows if x["signal"] == "likely_mismatch")
    print(f"== rc 离线对照：{n} 条（启发式信号，需人工核验；写入 {out}）==")
    print(f"  likely_match {lk} / likely_mismatch {lm} / unclear {n - lk - lm}")
    for x in out_rows:
        print(f"  #{x['id']} [{x['signal']}] agent: {x['agent_rc'][:70]}")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="元层 eval 台工具（EV-2026-013；docs/mechanism/eval-arena.md）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pool", metavar="YAML", help="校验池文件")
    g.add_argument("--stats", metavar="YAML", help="聚合池内 result → stats")
    g.add_argument("--rc-check", metavar="YAML", help="结论一致离线对照（agent rc vs 标注 resolution）")
    g.add_argument("--gate", action="store_true", help="baseline vs candidate 门控判定（配对 + 复用折减）")
    g.add_argument("--self-test", dest="self_test", action="store_true",
                   help="复现判词（合成样本；CI 跑它）")
    ap.add_argument("--baseline", default="", help="--gate: baseline stats yaml")
    ap.add_argument("--candidate", default="", help="--gate: candidate stats yaml")
    ap.add_argument("--component", default="", help="--gate: 目标组件（如 triage:xxx）")
    ap.add_argument("--candidate-ref", default="", help="--gate: EV 卡/PR 引用")
    ap.add_argument("--note", default="", help="--gate: 备注")
    ap.add_argument("--alpha", type=float, default=ALPHA_DEFAULT,
                    help=f"--gate: 每个接受决定的假接受预算（默认 {ALPHA_DEFAULT}）")
    ap.add_argument("--root", default=".", help="仓库根目录（默认当前目录）")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if args.pool:
        return cmd_pool(root, pool_path(root, args.pool))
    if args.stats:
        return cmd_stats(root, pool_path(root, args.stats))
    if args.rc_check:
        return cmd_rc_check(root, pool_path(root, args.rc_check))
    if args.self_test:
        return cmd_self_test()
    if not args.baseline or not args.candidate:
        # 明确退化：无池/无 stats 时不要静默拿空路径去读（会把仓库根当文件读，报"Is a directory"）
        print("eval_arena: --gate 需要 --baseline <stats.yaml> 与 --candidate <stats.yaml>。\n"
              "  还没有数据时：先按 docs/mechanism/eval-arena.md §2 建池（.s2-replay/arena/pool-*.yaml），\n"
              "  跑 replay 出 .s2-replay/<issue>.result.yaml，再各跑一次 --stats 得到两侧 stats。\n"
              "  只验证判据本身用 --self-test（不需要任何本地数据）。", file=sys.stderr)
        return 2
    return cmd_gate(root, pool_path(root, args.baseline), pool_path(root, args.candidate),
                    args.component, args.candidate_ref, args.note, args.alpha)


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
