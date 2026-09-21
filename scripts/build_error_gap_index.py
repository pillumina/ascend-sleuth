#!/usr/bin/env python3
# build_error_gap_index.py —— 生成 references/errors/_code-gaps.yaml（错误码缺口索引）
#
# 为什么要它（实测）：步骤 2 收尾的键触发只在 `references/errors/<族>.yaml` 里按 code 查，
# 查不到就记 `miss`。但同一个码往往已在 `references/fault-patterns/<域>.yaml` 里有完整的
# 症状→根因→修法。交叉核对：故障模式表里出现的 6 位错误码中 **12 个全库错误表都没有行**——
# 于是"这张表没收录"被读成"库里没有"，agent 转去源码或常识，而答案一直在隔壁那张表里。
# 本索引把那 12 个码变成一次跳转（查这里 → 打开 seen_in）。
#
# **不是第二份错误码表**：不复制 meaning/fix（那是 seen_in 词条的内容，抄一遍必漂移），
# 只记"这个码能在哪看到"。哪一段是生成、哪一段是手写，见各段自己的头注。
#
# 用法：
#   python3 scripts/build_error_gap_index.py            # 生成
#   python3 scripts/build_error_gap_index.py --check    # 新鲜度校验（CI：reference-validation job）
#
# 出处口径：只扫 `6 位数字`（507035 / 207007 …）与 `EE#### / EH####` 形态的码——
# 官方错误码参考里的 6 位码与 E* 码是"可作检索键"的两种；`0x…` 十六进制是设备异常码，
# 归属与查法不同（在故障模式表内按域查），不在本索引口径内。

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import yaml

from _stdio import write_text_lf

OUT_REL = "errors/_code-gaps.yaml"

# 缺口的码 → 手工补的一句"这个码讲的是什么"（生成不出来：它来自人读词条后的判断）。
# 空串 = 还没人读过，**允许**（不假装它已审阅）；`verify_references.py` 会把空 note 的
# 条数列出来当待办，而不是让构建失败——构建失败会诱使人写一句废话把它糊过去。
NOTES = {
    "100002": "aclInit 重复初始化——可忽略并继续（该码的官方行为在故障模式表里，不在错误表）",
    "107000": "aclInit 参数无效（配置路径 / 权限 / json 层级）",
    "107002": "进程中断与 msprobe 工具副作用两处出现（同一码两个场景）",
    "107012": "aclrtProcessReport failed——进程异常退出后资源未释放一类",
    "207007": "Event 超上限（Event id alloc error / no event resource）——与 507903 同族但机制不同",
    "207008": "halResourceIdAlloc streamid failed——同上族",
    "507899": "异步拷贝查询接口时序（Set free error / Devmm_iotcl_free failed）",
    "107001": "aclrtSetDevice 设备 ID 无效（越界 / 驱动未加载）——同码不同因，先看 npu-smi 能否列出设备",
    "107003": "aclrtMemcpyAsync 的 Stream 上下文错误 / 多 Device 跨用 Stream、Event",
    "207000": "接口返回功能不支持（ACL_ERROR_RT_FEATURE_NOT_SUPPORT）——先核对实际加载的库与版本",
    "207001": "aclrtMalloc 内存申请失败（ACL_ERROR_RT_MEMORY_ALLOCATION）——与 OOM 一类同看",
    "507017": "算子执行域（operator-exec）——见该词条的症状面",
    "507032": "模型推理域（model-inference）——见该词条的症状面",
    "507008": "编译执行域（compile-exec）——见该词条的症状面",
    "768032": "模型推理域（model-inference）——见该词条的症状面",
    "507035": (
        "UB 寄存器/搬运族的症状面——**先核对病因**：现场撞见的 507035 是索引 buffer 取值越界，"
        "与本族症状不是同一病因，命中不等于可套用"
    ),
}

# 无归属的码：全库任何表都没有它，只有现场撞见过。记的是覆盖缺口本身（原则十）。
# 补进错误表或补上 seen_in 之后从这里移出。
_NO_HOME = [
    {
        "code": "507014",
        "seen_scene": "MC2 融合算子（MoeDistributeDispatchV2）aicore/AIV timeout，驱动 24.1.x + CANN 9.0.1",
        "next": "查官方错误码参考 507xxx 族是否有此行；有则补进 cann-runtime.yaml 的 errors，没有则补进同一文件的 content.code_gaps",
    },
]

CODE_RE = re.compile(r"^(?:\d{6}|E[HIJ]\d{4})$")

# 族文件归属：按码前缀映射（与 ascend-error-code-structure 的 module_files 同一口径；
# 6 位码的模块位在错误表里按族文件切分，这里只覆盖"实际出现过缺口"的几条）
FAMILY_BY_PREFIX = [
    ("507", "cann-runtime-error-codes"),
    ("561", "cann-runtime-error-codes"),
    ("768", "cann-runtime-error-codes"),
    ("207", "cann-runtime-error-codes"),
    ("107", "acl-error-codes"),
    ("100", "acl-error-codes"),
]


def family_of(code: str) -> str:
    for prefix, fam in FAMILY_BY_PREFIX:
        if code.startswith(prefix):
            return fam
    return ""


def table_codes_and_pattern_codes(refs: Path):
    """返回（错误表已有码集合, {码: [出现它的故障模式词条相对路径]}）。"""
    table = set()
    for p in sorted((refs / "errors").glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for e in ((doc.get("content") or {}).get("errors") or []):
            if isinstance(e, dict) and e.get("code"):
                table.add(str(e["code"]))
    seen = {}
    for p in sorted((refs / "fault-patterns").glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        text = p.read_text(encoding="utf-8")
        rel = p.relative_to(refs.parent).as_posix()
        for m in set(re.findall(r"\b(?:\d{6}|E[HIJ]\d{4})\b", text)):
            if CODE_RE.match(m):
                seen.setdefault(m, set()).add(rel)
    return table, {k: sorted(v) for k, v in seen.items()}


def collect(refs: Path):
    table, seen = table_codes_and_pattern_codes(refs)
    gaps = []
    for code in sorted(seen):
        if code in table:
            continue
        gaps.append(
            {
                "code": code,
                "belongs_to": family_of(code),
                "seen_in": seen[code],
                "note": NOTES.get(code, ""),
            }
        )
    return gaps


def render(refs: Path) -> str:
    gaps = collect(refs)
    no_home = [g for g in _NO_HOME if g["code"] not in {x["code"] for x in gaps}]
    header = f"""# 错误码缺口索引（键触发查错误码表**未命中**时的下一步）——结构化绑定，不写散文
#
# 为什么存在（实测）：步骤 2 收尾的键触发只在 `references/errors/<族>.yaml` 里按 code 查。
# 查不到就记 `miss` 收场，而**同一个码往往已在故障模式表里有完整的症状→根因→修法**。
# 实测交叉核对：故障模式表（references/fault-patterns/）里出现的错误码中，有 {len(gaps)} 个
# 全库错误表都没有行。于是"这张表没收录"被读成"库里没有"，agent 转去源码或常识，
# 而答案一直在隔壁那张表里——两次真实诊断各撞上一次（507014 表缺行、507035 表缺行）。
#
# 本文件的两个作用，都只做一次动作：
#   ① **检索跳板**：错误表未命中 → 按本表查一行 → 直接打开 `seen_in` 指的故障模式词条；
#   ② **覆盖债台账**：哪些码"官方表没有行但我们有事实"被显式列出，而不是散落在各种 miss 里。
#
# **不是第二份错误码表**：本文件不复制 meaning/fix（那是 seen_in 词条的内容，抄一遍必漂移）。
# 它只记"这个码在哪能看到"，即一次跳转。
#
# 本文件整体由 `scripts/build_error_gap_index.py` 生成（--check 校验新鲜度，CI）；
# `note` 一句是人读词条后的判断，手工维护在脚本的 NOTES 表里——**留空不报错**，
# 但 `verify_references.py --check` 会把留空的条数列出来当待办（不逼人写废话糊过去）。
#
# 口径：只收 6 位数字码与 E*#### 码（官方错误码参考的两种可检索键）；`0x…` 设备异常码
# 归属与查法不同（在故障模式表内按域查），不在本索引内。

generated_at: {date.today()}
source: references/fault-patterns/*.yaml 中出现的错误码 − references/errors/*.yaml 已有行
"""
    doc = {"code_gaps": gaps, "no_home": no_home}
    body = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=10 ** 6, default_flow_style=False)
    tail = """
# 无归属：全库任何表都没有这个码，只有现场撞见过——记的是覆盖缺口本身（原则十：诚实退化）。
# 补进错误表（errors）或给出 seen_in 之后从本段移出。
"""
    return header + body + tail.lstrip("\n")


def parses(text: str) -> str:
    try:
        d = yaml.safe_load(text)
    except Exception as e:
        return str(e).splitlines()[0]
    if not isinstance(d, dict) or not isinstance(d.get("code_gaps"), list):
        return "解析结果不是 {code_gaps: [...]}"
    for i, g in enumerate(d["code_gaps"]):
        if not isinstance(g, dict) or not {"code", "belongs_to", "seen_in", "note"} <= set(g):
            return f"code_gaps[{i}] 字段不全（需 code/belongs_to/seen_in/note）"
    return ""


def _normalize(text: str) -> str:
    """生成日期不参与比对——否则跨天跑 --check 会假红。"""
    return re.sub(r"^generated_at: .*$", "generated_at: <DATE>", text, flags=re.M)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--root", default=None)
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    refs = root / "references"
    text = render(refs)
    out = refs / OUT_REL
    err = parses(text)
    if err:
        print(f"生成失败：产物不是合法形态：{err}")
        return 1
    if args.check:
        if not out.exists():
            print(f"{OUT_REL} 不存在——运行 scripts/build_error_gap_index.py 生成")
            return 1
        old = out.read_text(encoding="utf-8")
        if _normalize(old) != _normalize(text):
            print(f"{OUT_REL} 过期——references/ 有变更未重建（运行 scripts/build_error_gap_index.py）")
            return 1
        print(f"错误码缺口索引新鲜且可解析（{len(yaml.safe_load(text)['code_gaps'])} 条缺口）")
        return 0
    write_text_lf(out, text, encoding="utf-8")
    print(f"已生成 {out}（{len(yaml.safe_load(text)['code_gaps'])} 条缺口）")
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio

    pin_utf8_stdio()
    sys.exit(main())
