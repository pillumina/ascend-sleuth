#!/usr/bin/env python3
# metrics_health.py —— 指标闭环体检（新鲜度 / 越界 / 可解读性）
#
# 为什么需要（2026-09-10 审计实测）：
#   `docs/metrics.md` 的周批流程是"跑 trace_metrics → 人复核 → append → verify_metrics"。
#   实测按这个流程走一遍，**不会**被告知三类真问题：
#     ① 结构指标（容量/条数）已 10 天没进快照：快照 `case_total 52` vs 现实 **158**；
#        某格 `interrupt=85/30`（soft_cap 的 2.8 倍），而快照里那次还是 `36/30`；
#     ② 本期没有 live 快照（趋势断档，季度回顾读不到连续 live）；
#     ③ `feedback_capture` 全 0 → 命中率/误诊率**没有分母**，"0/3 = 零误诊"是假绿。
#   `verify_metrics.py` 只验结构（period 唯一 / 字段白名单 / 比例字段合法），
#   不判这三件事 —— 即"数据 → 判据 → 动作"这条腿上**没有检测器**，指标坏了只能靠人
#   季度回顾时想起来。本脚本补这条腿：判据一律读 `metrics/gates.yaml`（数据，不写死）。
#
# 退出码：默认 0（报告即真相）；`--check` 时有越界/陈旧/不可解读 → 非零。
#   **不进 CI**：安静的一周没有新快照是正常状态，硬门会假红；它服务于周批与季度回顾。
#
# 用法：
#   python3 scripts/metrics_health.py            # 人读体检
#   python3 scripts/metrics_health.py --check    # 有 ✗ 则非零（供 groom/回顾脚本判）
#   python3 scripts/metrics_health.py --json

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

import yaml

import metrics_snapshot as MS

# 本体检器**实现了哪些判据 dimension / readability rule**——写成集合，用来对照 `gates.yaml`
# 实际声明的条目。gates.yaml 里新增一条判据而这里没实现时，`--check` 报 2（不可判定），
# 而不是安静地"没有越界"（EV-2026-055 的教训：检测腿断了自己不会喊）。
IMPLEMENTED_GATE_DIMENSIONS = {"capacity_cell", "feedback_capture_total"}
IMPLEMENTED_READABILITY_RULES = {"total_gt_0", "any_gt_0", "source_nonzero"}
# `capacity_cells[].hard` 的兜底阈值：`cell_hard_cap` 闸门缺失时才用到（正常路径读 gates.yaml）
HARD_CAP_FALLBACK = 60


def load_yaml(path: Path, errors: list = None):
    """读 YAML；解析失败**记进 errors**，不静默当成空文档。

    原先这里 `except Exception: return {}` —— 于是 gates.yaml 一旦语法坏掉，
    判据变成 0 条、体检器报 "clean（判据全部评过）"：**检测器的配置读坏了它自己不会喊**，
    正是本卡要消灭的那类假绿（实测：一份被写坏缩进的 gates.yaml 让整轮体检全绿）。
    """
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        if errors is not None:
            errors.append(f"{path.name} 读取/解析失败（{type(e).__name__}: {e}）——判据不可读，"
                          f"本轮体检的\"无越界\"结论不成立")
        return {}


def age_days(recorded_at):
    if not recorded_at:
        return None
    try:
        return (date.today() - date.fromisoformat(str(recorded_at)[:10])).days
    except ValueError:
        return None


def op_holds(op: str, value, threshold) -> bool:
    if op == ">":
        return value > threshold
    if op == ">=":
        return value >= threshold
    if op == "<":
        return value < threshold
    if op == "<=":
        return value <= threshold
    if op == "==":
        return value == threshold
    return False


def latest_by(periods, pred):
    """取"最新"的一期：先比 recorded_at，**同日期时以列表位置为准**（timeline 是 append-only，
    后出现的更新）。实测踩过：两期 recorded_at 同为 2026-08-31，只比日期会挑中较早那期。"""
    cands = [(i, p) for i, p in enumerate(periods) if pred(p)]
    if not cands:
        return None
    return max(cands, key=lambda ip: (str(ip[1].get("recorded_at") or ""), ip[0]))[1]


def check_no_data(periods):
    """一层：数据底座本身有没有东西。"""
    out = []
    live = [p for p in periods if p.get("kind") == "live"]
    structural = [p for p in periods if "case_total" in (p.get("metrics") or {})]
    out.append(("ok" if live else "fail", "live 快照", f"{len(live)} 期" if live else "0 期 —— 趋势与季度回顾都无从谈起"))
    out.append(("ok" if structural else "fail", "结构快照（容量/条数）",
                f"{len(structural)} 期" if structural else "0 期 —— 容量治理没有趋势通道"))
    return out


def count_reference_entries(root: Path):
    """无子进程的 reference 词条计数（降级用）。

    口径**复用权威实现**（`verify_references.py` 里那个函数），不再自己写一份 rglob 规则——
    原先写重复规则时实测 127 vs 权威 130：error-code 词条有 `references/<type>/<family>/x.yaml`
    这一层嵌套，自己那份漏了。**降级值必须与权威值同口径**，否则"已标注口径"仍会误导读者；
    而避免漂移的办法不是"对齐两份规则"，是**只留一份**。
    """
    try:
        import verify_references as VR
        return VR.count_entries(root / "references")
    except Exception:
        # 连 import 都不成（脚本被裁剪）→ 如实返回"取不到"，不猜一个数
        return None


def collect_structural_safe(root: Path):
    """`MS.collect_structural` 的防御包装：**任何**异常都变成"这一块拿不到"，而不是崩掉整轮体检。

    为什么（2026-09-11 实测事故）：诊断面板在执行体检时，`collect_structural` 内部抛异常
    （该函数会用 `subprocess.run(capture_output=True)` 跑 verify_references.py——受限执行环境里
    子进程/管道可能被拒），异常直接冒到模块级 → 整个脚本 traceback、面板上只剩一截看不懂的报错，
    **连容量越界这种最要命的信号都一起没了**。体检器的职责是"能判的判、不能判的如实说"，
    不是"一个次要数字拿不到就整体不工作"。
    返回 (out, notes)：out 至少含 case_total / reference_total / capacity_by_ns / 口径标注。
    """
    notes = []
    out = {"case_total": None, "reference_total": None, "capacity_by_ns": {},
           "reference_source": None, "capacity_source": None}
    try:
        got, s_notes = MS.collect_structural(root)
        if isinstance(got, dict):
            out.update(got)
            # s_notes 如实记录结构侧拿不到的部分（索引缺失 / verify_references 跑不了），
            # 它们进 broken → 退出码 2。同一件事只报一次：这里不再另加"结构侧采集失败"。
            notes.extend(s_notes or [])
        else:
            notes.append(f"collect_structural 返回 {type(got).__name__}（预期 dict 元组）")
    except Exception as e:
        # 保持**单行**：这个字符串会进面板的错误行，多行会把版面撑爆
        msg = " ".join(str(e).split())
        # 这条文案会直接进面板的错误行（用户可见）——不写 Markdown 星号（会渲染成字面量）
        notes.append(f"结构侧采集失败（{type(e).__name__}: {msg[:200]}）——容量判据本轮未被评估")
    if out.get("reference_total") is None:
        fallback = count_reference_entries(root)
        if fallback is not None:
            out["reference_total"] = fallback
            out["reference_source"] = "降级计数（复用 verify_references 的计数实现，非权威校验通过）"
            notes.append("reference 词条数取不到权威校验值，已降级为同口径直接计数")
    return out, notes


# 面向用户的中文名：**命名空间与类别是框架侧的机器标识**（inference/vllm-ascend、interrupt），
# 直接端给读者等于让人读目录名。这里只做展示层翻译，不改任何数据与判据。
NS_LABEL = {
    "inference/vllm-ascend": "推理 · vllm-ascend",
    "inference/sglang": "推理 · sglang",
    "training/mindspeed-llm": "训练 · mindspeed-llm",
    "training/verl": "训练 · verl",
    "common": "通用",
}
CATEGORY_LABEL = {
    "interrupt": "中断类报错",
    "precision": "精度问题",
    "performance": "性能问题",
}


def ns_label(ns: str) -> str:
    return NS_LABEL.get(ns, ns)


def cat_label(cat: str) -> str:
    return CATEGORY_LABEL.get(cat, cat)


def main():
    ap = argparse.ArgumentParser(description="metrics 闭环体检")
    ap.add_argument("--check", action="store_true", help="有 ✗ 时退出码非零")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()
    root = args.root.resolve()

    load_errors = []       # 配置文件读不动的如实记录（进 broken，退出码 2）
    gates_doc = load_yaml(root / "metrics" / "gates.yaml", load_errors)
    gates = gates_doc.get("gates") or []
    fresh = gates_doc.get("freshness") or {}
    readability = gates_doc.get("readability") or []
    timeline = load_yaml(root / "metrics" / "timeline.yaml", load_errors)
    periods = timeline.get("periods") or []
    if not gates and (root / "metrics" / "gates.yaml").exists() and not load_errors:
        load_errors.append("gates.yaml 里没有任何闸门条目（文件存在但 gates 为空）——判据全部缺席")

    findings = []          # (level, 面, 文案, 动作)
    readability_state = {}  # metric 名 → {readable, why}；--json 契约给面板打标记用

    # findings 是 5 元组：(level 面 文案 动作 人话版)。
    # **为什么多一列**（2026-09 七轮，用户反馈）：面板原先直接把 `cell_soft_cap`、
    # `feedback_capture_floor`、`misdiagnosis_rate` 这些**代码里的名字**端给读者，
    # 句子也是对着实现说的（"(framework × category) 格子条数超 soft_cap"）。判据的**身份**
    # 住在这一侧，所以"人话版"也必须由这一侧提供——面板只渲染，不做启发式翻译。
    # 技术文案保留：它进 CLI 报告与展开后的证据行，维护者仍拿得到判据名。
    findings = []          # (level, 面, 技术文案, 动作, 人话版)
    readability_state = {}  # metric 名 → {readable, why, label}；--json 契约给面板打标记用

    # —— ① 数据底座 ——
    for level, what, text in check_no_data(periods):
        findings.append((level, "数据底座", f"{what}：{text}", None, None))

    # —— ② 新鲜度 ——
    last_live = latest_by(periods, lambda p: p.get("kind") == "live")
    last_struct = latest_by(periods, lambda p: "case_total" in (p.get("metrics") or {}))
    for label, doc, limit_key, plain_label in (
            ("诊断侧 live 快照", last_live, "live_snapshot_max_age_days", "诊断数据"),
            ("结构侧（容量/条数）", last_struct, "structural_max_age_days", "知识库统计")):
        limit = fresh.get(limit_key)
        if doc is None:
            findings.append(("fail", "数据新鲜度", f"{label}：一期都没有", "跑 metrics_snapshot.py 组装后 append",
                             f"还没有任何{plain_label}快照——趋势无从谈起"))
            continue
        age = age_days(doc.get("recorded_at"))
        if age is None:
            findings.append(("warn", "数据新鲜度", f"{label}：recorded_at 不可解析（{doc.get('recorded_at')!r}）", None, None))
        elif limit is not None and age > limit:
            findings.append(("fail", "数据新鲜度",
                             f"{label}：最后 {doc.get('period')}（{doc.get('recorded_at')}，{age} 天前）超期 {limit} 天",
                             "跑 metrics_snapshot.py 组装本期快照",
                             f"{plain_label}已经 {age} 天没更新（惯例是每 {limit} 天一次）——"
                             f"现在看到的还是 {doc.get('period')} 的状态"))
        else:
            findings.append(("ok", "数据新鲜度", f"{label}：最后 {doc.get('period')}（{age} 天前，阈值 {limit} 天）", None, None))

    # —— ③ 越界（判据来自 gates.yaml；容量用**当前现实**，不是快照里的旧值）——
    # collect_structural 返回 (out, notes) 元组：原先漏了解包，structural 拿到的是整个
    # 元组 → `structural.get` 抛 AttributeError 被 except 吞掉（s_notes 恒为空），
    # capacity_by_ns 恒为空 dict → **容量越界永远检不出**；`current` 块也跟着恒为 None。
    # 现在走防御包装：结构侧任何异常都降级成"这一块拿不到 + 如实标注"，不崩整轮体检
    # （实测：面板环境下 collect_structural 曾整体抛错，连容量判据一起带走）。
    structural, s_notes = collect_structural_safe(root)
    cells = [(ns, cat, c["count"], c["cap"]) for ns, cs in (structural.get("capacity_by_ns") or {}).items()
             for cat, c in cs.items()]
    prev_cells = {}
    if last_struct:
        for ns, cs in ((last_struct.get("metrics") or {}).get("capacity_by_ns") or {}).items():
            for cat, c in (cs or {}).items():
                if isinstance(c, dict):
                    prev_cells[(ns, cat)] = c.get("count")

    # 容量：**一个格子只报一条**。
    # 为什么（2026-09 七轮，实测）：格子 85/30 会同时越过 soft_cap(>30) 与 hard_cap(>=60)，
    # 于是面板上出现两行 85/30、人话版也几乎一样——读者以为是两件事。判据确实是两条，
    # 但对人来说"这一格超了两条线"是一件事：合成一条，并在展开的判据行里如实写清越过了哪两条。
    capacity_hits = {}   # (ns, cat) → {n, cap, gates:[{id, meaning, action}], hard:bool}
    for g in gates:
        if g.get("dimension") != "capacity_cell":
            continue
        op, val = g.get("op"), g.get("value")
        for ns, cat, n, cap in cells:
            if not op_holds(op, n, val):
                continue
            key = (ns, cat)
            hit = capacity_hits.setdefault(key, {"ns": ns, "cat": cat, "n": n, "cap": cap,
                                                 "gates": [], "hard": False})
            hit["gates"].append({"id": g.get("id"), "meaning": g.get("meaning"), "action": g.get("action")})
            if "hard" in str(g.get("id")):
                hit["hard"] = True

    for key in sorted(capacity_hits, key=lambda k: -capacity_hits[k]["n"]):
        hit = capacity_hits[key]
        ns, cat, n, cap = hit["ns"], hit["cat"], hit["n"], hit["cap"]
        prev = prev_cells.get((ns, cat))
        drift = f"（上次快照 {prev}）" if prev is not None and prev != n else ""
        gate_names = "、".join(str(x["id"]) for x in hit["gates"])
        # 动作取最强的那条（hard 优先，否则按 gates.yaml 顺序）
        action = next((x["action"] for x in hit["gates"] if x["action"] and "hard" in str(x["id"])),
                      hit["gates"][0].get("action"))
        findings.append(("fail", "容量",
                         f"{ns} · {cat} = {n}/{cap}{drift} —— 越过 {'、'.join(str(x['id']) for x in hit['gates'])}"
                         f"（{'；'.join(str(x['meaning']) for x in hit['gates'])}）",
                         action,
                         f"{ns_label(ns)} 的「{cat_label(cat)}」已收录 {n} 条，上限 {cap} 条"
                         + (f"，是上限的 {round(n / cap, 1)} 倍" if cap else "")
                         + ("。同类问题堆得太多，检索会变慢、命中会变散，需要拆成更细的分类"
                            if hit["hard"] else "。已到预警线，建议评估是否拆分")))
    if not capacity_hits:
        findings.append(("ok", "容量", f"所有格子均未触发 ({'、'.join(str(g.get('id')) for g in gates if g.get('dimension') == 'capacity_cell')})",
                         None, None))

    for g in gates:
        gid, dim, op, val = g.get("id"), g.get("dimension"), g.get("op"), g.get("value")
        if dim == "capacity_cell":
            pass   # 已在上面按格子合并处理
        elif dim == "feedback_capture_total":
            live_m = ((last_live or {}).get("metrics") or {})
            fc = live_m.get("feedback_capture")
            if not isinstance(fc, dict):
                findings.append(("warn", "反馈", "最新 live 快照没有 feedback_capture 字段", g.get("action"),
                                 "这次快照没记下修复反馈，无法判断命中是否有效"))
            else:
                total = sum(v for v in fc.values() if isinstance(v, int))
                if op_holds(op, total, val):
                    hits_n = live_m.get("tier2_hit")
                    seen = f"{hits_n} 次命中" if isinstance(hits_n, int) and hits_n > 0 else "已有命中"
                    findings.append(("fail", "反馈", f"最新 live 快照 {last_live.get('period')} 捕获反馈 {total} 条 —— {g.get('meaning')}",
                                     g.get("action"),
                                     f"{seen}，但没有任何一条回报修复结果——"
                                     f"所以「命中是否真的解决问题」「有没有误诊」现在都判断不了"))
                else:
                    findings.append(("ok", "反馈", f"捕获反馈 {total} 条", None, None))
        else:
            findings.append(("warn", "越界", f"gates.yaml 里的 dimension '{dim}' 没有对应评估实现", None, None))
    # —— ④ 可解读性（分母为 0 的指标必须被标成"不可解读"，不能安静地写成 0）——
    live_m = ((last_live or {}).get("metrics") or {})
    for rule in readability:
        metric, kind, why = rule.get("metric"), rule.get("rule"), rule.get("why")
        v = live_m.get(metric)
        if v is None:
            findings.append(("warn", "数字可信度", f"{metric}：最新 live 快照没有该字段（{why}）", None,
                             "这次快照缺一项数据，相关结论无法判断"))
            continue
        if kind == "total_gt_0":
            total = (v or {}).get("total") if isinstance(v, dict) else None
            bad = not isinstance(total, int) or total <= 0
            note = why
        elif kind == "any_gt_0":
            bad = not (isinstance(v, dict) and any(x for x in v.values() if isinstance(x, int)))
            note = why
        elif kind == "source_nonzero":
            # 该指标的可信度取决于另一个"来源"指标是否有数据（例：误诊率取决于反馈捕获）
            src = live_m.get(rule.get("source"))
            src_total = sum(x for x in (src or {}).values() if isinstance(x, int)) if isinstance(src, dict) else 0
            bad = src_total <= 0
            note = f"{why}（来源指标 {rule.get('source')} 计数 {src_total}）"
        else:
            findings.append(("warn", "数字可信度", f"{metric}：rules 里的 rule '{kind}' 没有对应实现", None, None))
            continue
        # 人话版：不写 `misdiagnosis_rate`/`attribution_ratio`/`source_nonzero` 这些实现词，
        # 只说"哪个结论现在不可信 + 为什么"。指标名留给展开后的证据行。
        PLAIN_METRIC = {
            "misdiagnosis_rate": ("误诊率", "命中样本还没被任何人验证过，所以现在算出的是「没人回报」，不是「没有误诊」"),
            "attribution_ratio": ("误诊归因", "至今没有一个「没解决」的回报，所以归因统计没有数据"),
        }
        label, plain_why = PLAIN_METRIC.get(metric, (metric, str(note)))
        findings.append(("fail" if bad else "ok", "数字可信度",
                         f"{metric}：{'不可解读——' + str(note) if bad else '可解读'}", None,
                         f"{label}现在不可解读——{plain_why}" if bad else None))
        # 面板契约：把 metric 名一并带出（面板据此在指标行上打"不可解读"标记）。
        readability_state[metric] = {"readable": not bad, "why": note if bad else None, "label": label}

    # —— ⑤ 内容流程侧（exec-log 聚合：本轮刚接进快照的来源）——
    # 同样防御包装：exec-log 是 .gitignore 运行时件，任何路径/权限问题都不该崩掉整轮体检
    try:
        flow, meta = MS.collect_content_flow(root)
    except Exception as e:
        msg = " ".join(str(e).split())
        flow = {"content_flow_runs": 0, "evolve_check_runs": 0, "evolve_check_no_signal": 0}
        meta = {"where": "（取不到）"}
        s_notes.append(f"内容流程侧采集失败（{type(e).__name__}: {msg[:160]}）——收尾记录数按 0 显示，不代表真的没跑")
    findings.append(("ok" if flow["content_flow_runs"] else "warn", "现场记录",
                     f"收尾记录 {flow['content_flow_runs']} 条（evolve-check {flow['evolve_check_runs']} 次，"
                     f"其中无信号 {flow['evolve_check_no_signal']} 次；来源 {meta['where']}）",
                     None if flow["content_flow_runs"] else "内容流程收尾应落记录（各 skill 收尾节）",
                     None if flow["content_flow_runs"] else
                     "这次没有记录到任何内容流程的收尾动作——可能真的没跑，也可能跑了没留痕（现在两者分不开）"))

    # —— 下一步（候选动作）：判据说"该做什么"，这里给出"粘到对话就能做"的那一下 ——
    # 命令是候选不是自动执行：诊断系统只输出建议，动作由人/agent 触发（与 diagnose 同取向）。
    candidate_commands = [
        {"label": "补反馈", "command": "回报 fix 结果：逐个确认 traces/ 中已定位 case 的 session（含 feedback.outcome: pending 的）"
                                      "fix 应用后是否解决，按 resolved / not_resolved / partial 写 feedback 事件",
         "why": "反馈捕获为 0 时，误诊率/归因比没有分母"},
        {"label": "追快照", "command": "python3 scripts/metrics_snapshot.py",
         "why": "诊断侧/结构侧快照超期 → 趋势断档"},
        {"label": "拆格子", "command": "用 /skill:knowledge-groom 处理容量越界格子（category 轴深化或 platform 轴拆分）",
         "why": "格子超 soft_cap 触发拆分评估，超 hard_cap 强制拆分"},
        {"label": "重建索引", "command": "python3 scripts/build_index.py",
         "why": "索引头注与磁盘不一致时，检索与面板读到的都是旧数"},
    ]

    # —— 判断：判据被评估了几条、数据源在不在（决定 `--check` 的退出码）——
    #
    # 为什么需要这一层（2026-09-11）：`--check` 原本只用"有没有 ✗"映射退出码 0/1，
    # 于是**"体检器坏了"与"本期确实没有违规"不可区分**。实测发生过：一处漏解包让容量
    # 判据恒不触发，`--check` 照样 exit 0 —— 检测腿断了自己不会喊（EV-2026-055）。
    # 现在分三态：0 = 判据全部评过且无越界；1 = 有判据被违反；2 = 有判据没被评过（结构性）。
    # 语义与 `ev_measure.py` 的三态刻意同形（0 符合 / 1 被证伪 / 2 无法判定）。
    gate_audit = []
    broken = list(load_errors)
    for g in gates:
        dim = g.get("dimension")
        ok_impl = dim in IMPLEMENTED_GATE_DIMENSIONS
        gate_audit.append({"id": g.get("id"), "dimension": dim, "implemented": ok_impl})
        if not ok_impl:
            broken.append(f"闸门 {g.get('id')}（dimension={dim}）没有评估实现——这条判据不会被检查")
    readability_audit = []
    for rule in readability:
        metric, kind = rule.get("metric"), rule.get("rule")
        ok_impl = kind in IMPLEMENTED_READABILITY_RULES
        present = metric in live_m
        readability_audit.append({"metric": metric, "rule": kind, "implemented": ok_impl,
                                  "present_in_snapshot": present})
        if not ok_impl:
            broken.append(f"可解读性规则 {metric}（rule={kind}）没有实现——这条判据不会被检查")
        elif not present:
            broken.append(f"可解读性规则 {metric}：最新 live 快照没有该字段，规则**未被评估**（不等于通过）")
    if s_notes:
        # s_notes 已包含"索引不存在/头注格式变了"两类结构侧缺陷；容量格子的缺席也由它解释，
        # 不在这里再报一次（同一件事说三遍会把"体检器自身缺陷"淹掉）
        broken.extend(s_notes)

    fails = [f for f in findings if f[0] == "fail"]
    exit_code = 0
    if broken:
        exit_code = 2
    elif fails:
        exit_code = 1

    payload = {
        "findings": [{"level": l, "face": f, "text": t, "action": a, "plain": p}
                     for l, f, t, a, p in findings],
        "fail_count": len(fails),
        "last_live": (last_live or {}).get("period"),
        "last_structural": (last_struct or {}).get("period"),
        "freshness": {
            "live_age_days": age_days((last_live or {}).get("recorded_at")),
            "structural_age_days": age_days((last_struct or {}).get("recorded_at")),
            "live_limit_days": fresh.get("live_snapshot_max_age_days"),
            "structural_limit_days": fresh.get("structural_max_age_days"),
            "live_periods": len([p for p in periods if p.get("kind") == "live"]),
            "structural_periods": len([p for p in periods if "case_total" in (p.get("metrics") or {})]),
        },
        # 面板据此跳过重算判据：门槛数值只在 gates.yaml 一处（原则二）
        "gates": [{"id": g.get("id"), "dimension": g.get("dimension"), "op": g.get("op"),
                   "value": g.get("value"), "meaning": g.get("meaning"), "action": g.get("action")}
                  for g in gates],
        "readability": readability_state,
        "capacity_cells": [
            {"namespace": ns, "category": cat, "count": n, "cap": cap,
             "soft": cap is not None and n > cap, "hard": n >= HARD_CAP_FALLBACK}
            for ns, cat, n, cap in sorted(cells, key=lambda x: (-x[2], x[0], x[1]))
        ],
        "candidate_commands": candidate_commands,
        "current": {"case_total": structural.get("case_total"),
                    "reference_total": structural.get("reference_total"),
                    "content_flow": flow},
        # 三态与覆盖面：面板首屏据此区分"本期没事"与"体检器没在工作"
        "exit_code": exit_code,
        "check_verdict": "broken" if exit_code == 2 else ("violations" if exit_code == 1 else "clean"),
        "broken": broken,
        "coverage": {
            "gates_total": len(gates),
            "gates_evaluated": len([a for a in gate_audit if a["implemented"]]),
            "gates": gate_audit,
            "readability_total": len(readability),
            "readability_evaluated": len([a for a in readability_audit if a["implemented"] and a["present_in_snapshot"]]),
            "readability": readability_audit,
            "structural_sources_ok": not s_notes,
        },
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return exit_code if args.check else 0

    icon = {"ok": "✓", "warn": "!", "fail": "✗"}
    print("metrics 闭环体检（判据：metrics/gates.yaml）")
    face = None
    for level, f, text, action, plain in findings:
        if f != face:
            print(f"\n[{f}]")
            face = f
        # CLI 面向维护者：技术文案在前（带判据名，便于回查 gates.yaml），人话版在后（便于理解）
        print(f"  {icon[level]} {text}")
        if plain and plain != text and level != "ok":
            print(f"      说人话：{plain}")
        if action and level != "ok":
            print(f"      → {action}")
    cov = payload["coverage"]
    print(f"\n[判据覆盖面] 闸门 {cov['gates_evaluated']}/{cov['gates_total']} 条已评估"
          f" · 数字可信度规则 {cov['readability_evaluated']}/{cov['readability_total']} 条已评估")
    if broken:
        print("\n[体检器自身] 下列判据**未被评估**——这不是'通过'，是检测腿断了：")
        for b in broken:
            print("  ✗ " + b)
    verdict = {"clean": "本期未发现阻塞项（判据全部评过）",
               "violations": "闭环未闭合（%d 项 ✗）" % len(fails),
               "broken": "体检器不完整：有判据未被评估，结论不可用（%d 项 ✗ 仅供参考）" % len(fails)}[payload["check_verdict"]]
    print(f"\n结论：{verdict}")
    if fails:
        print("  ✗ = 有判据被违反但没人处理；行动列即下一步（判据数值在 metrics/gates.yaml）")
    print("  退出码：0 判据全部评过且无越界 · 1 有判据被违反 · 2 有判据未被评估（不可判定）")
    return exit_code if args.check else 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
