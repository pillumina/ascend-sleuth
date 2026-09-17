#!/usr/bin/env python3
# rename_ref.py —— 把"移动/改名一个 tracked 文件"变成一条命令
#
# 为什么需要它（实测喂出来的）：文档按层分目录那一次，移动 17 篇牵出三类连带改动，全是手工做的——
#   ① 全仓路径引用（markdown 相对链接、`docs/…` 形式的绝对引用、YAML 注释里的路径、散文里的裸路径）；
#   ② 改进项卡里的路径引用（43 张卡 55 处）；
#   ③ 判据的**组件键**（`surface_basis.path`，取值优先级最高来自 `decisions[type=action].conclusion`）。
# 手工的代价当场就显出来了：一次性脚本只处理了"链接目标也移动了"的情形，10 条指向未移动目标的
# 相对链接漏改，是随后跑坏链检查才发现的；而第 ③ 类根本不是"改文字"能解决的——decisions 是
# 只追加的审计链，按纪律不许回写，于是历史卡永久挂在旧键上，判据「同一组件重复做功」少报。
#
# 本工具把第 ①② 类做成一条命令，把第 ③ 类做成**别名登记**（不动历史文本，改解析时归一）。
#
# 审计链豁免（硬规则，不是开关）：
#   - `proposals/ideas/*.yaml` 的 `decisions:` 块：写进去的是"当时发生了什么"，含当时的路径；
#   - `docs/adr/**`：决策留痕，同为只追加档案。
#   这两处一律不改。历史引用靠别名解析，不靠回写。
#
# 用法：
#   python3 scripts/rename_ref.py <旧路径> <新路径>              # 默认 dry-run，只打印将改什么
#   python3 scripts/rename_ref.py <旧路径> <新路径> --apply      # 真写
#   python3 scripts/rename_ref.py <旧路径> <新路径> --apply --no-alias   # 不登记别名
#   退出码：0 = 成功（含"无需改动"）；1 = 参数/前置校验失败（如新路径不存在）
#
# 前置校验：新路径必须已存在（先 git mv 再跑本工具）。旧路径不存在时按"已搬完"处理，
# 仍然执行（这正是幂等重跑的场景：引用早改完了，只是别名还没登记）。

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from _stdio import pin_utf8_stdio, write_text_lf

TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".py", ".js", ".json", ".example", ".txt", ".html"}
SKIP_DIRS = (".git/", "node_modules/")
# 只追加档案：一个字不改（含其中的路径）
AUDIT_PREFIXES = ("docs/adr/",)
CARDS_DIR = "proposals/ideas"
ALIAS_REL = Path("proposals") / "component-aliases.yaml"


def frozen_artifacts(root: Path) -> set:
    """按内容哈希钉住的量尺件：默认**只报不改**，因为改它们要付一套显式代价。

    实测教训：一次批量替换很容易顺手把 `eval/golden/**` 的注释路径也改掉——那会同时
    弄红 `holdout --check`（封存夹具哈希）与 `eval-scorecard`（观测账本里的夹具哈希），
    必须重新封存 + 重建账本 + PR 打 `holdout-change` 标签。为一句注释付这套摩擦不值得，
    所以默认跳过并如实报出；确实要改时用 `--include-frozen` 显式承担。
    """
    import yaml
    out = set()
    for rel, key in (("eval/holdout.yaml", "entries"), ("eval/scorecard.yaml", "entries")):
        path = root / rel
        if not path.exists():
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for e in (doc.get(key) or []):
            if isinstance(e, dict) and e.get("fixture"):
                out.add(f"eval/golden/{e['fixture']}")
    out.add("eval/holdout.yaml")        # 封存清单本身也要显式动
    return out


def tracked_files(root: Path):
    out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split()
    return [p for p in out if Path(p).suffix in TEXT_SUFFIXES and not p.startswith(SKIP_DIRS)]


def split_decisions(text: str):
    """卡文本 → (decisions 之前的正文, decisions 块, 之后的正文)。

    decisions 是只追加的审计链，改它等于篡改记录——所以把它整段摘出来不碰。
    """
    m = re.search(r"^decisions:\s*$", text, re.M)
    if not m:
        return text, "", ""
    rest = text[m.end():]
    nxt = re.search(r"^[A-Za-z_]", rest, re.M)
    end = m.end() + (nxt.start() if nxt else len(rest))
    return text[:m.start()], text[m.start():end], text[end:]


def rewrite_links(text: str, base_dir: Path, root: Path, old: str, new: str):
    """改写 markdown/普通链接里的相对路径。

    关键点（手工那次在这里漏过）：**链接目标没移动、但写链接的文件移动了**时，链接同样要重算。
    所以这里不看"目标是否在移动集合里"，而是逐个链接按旧目录解析、按新目录重写。
    """
    old_p, new_p = root / old, root / new
    n = 0
    # 该文件自身是否也参与这次搬家（由调用方决定 base_dir），此处只做重算
    def repl(m):
        nonlocal n
        label, path = m.group(1), m.group(2)
        if re.match(r"^[a-z]+:|^#|^mailto:", path):
            return m.group(0)
        anchor = ""
        if "#" in path:
            path, anchor = path.split("#", 1)
            anchor = "#" + anchor
        try:
            tgt = (base_dir / path).resolve()
        except OSError:
            return m.group(0)
        # 目标 = 本次移动的旧路径 → 指到新路径；否则目标没动，链接文本也不动
        if tgt != old_p.resolve():
            return m.group(0)
        rel = os.path.relpath(new_p, base_dir)
        n += 1
        # 标签本身**是路径形态**（含 `/`）且解到旧路径时一并对齐——否则会出现"指向 A 却写着 B"的链接
        # （实测形态：[../rsi-mechanism.md](rsi-mechanism.md)）。只当标签不含 `/` 时（如 [eval.md](…)）
        # 它是人读的名字，不是路径，别动。
        lab = label.strip()
        lab_is_path = "/" in lab
        if lab_is_path:
            try:
                lab_is_path = (base_dir / lab).resolve() == old_p.resolve()
            except OSError:
                lab_is_path = False
        if lab_is_path or lab == old:
            label = rel
        return f"[{label}]({rel}{anchor})"

    text = re.sub(r"\[([^\]]*)\]\(([^)\s]+)\)", repl, text)
    return text, n


def rebase_links(text: str, old_dir: Path, new_dir: Path):
    """被移动的那份文件自己：把它的相对链接按**旧目录**解析、按**新目录**重写。

    为什么必须单独处理：相对链接是相对"包含它的文件"算的，文件一移动，**目标没动也会断**。
    手工那次的一次性脚本只处理了"链接目标也移动了"的情形，于是 10 条指向未移动目标的
    相对链接漏改，是随后跑坏链检查才发现的。
    """
    n = 0

    def repl(m):
        nonlocal n
        label, path = m.group(1), m.group(2)
        if re.match(r"^[a-z]+:|^#|^mailto:", path):
            return m.group(0)
        anchor = ""
        if "#" in path:
            path, anchor = path.split("#", 1)
            anchor = "#" + anchor
        try:
            tgt = (old_dir / path).resolve()
        except OSError:
            return m.group(0)
        if not tgt.exists():
            return m.group(0)          # 本来就坏，不动（本工具只修"因搬家而断"的）
        rel = os.path.relpath(tgt, new_dir)
        if rel == path:
            return m.group(0)
        n += 1
        return f"[{label}]({rel}{anchor})"

    return re.sub(r"\[([^\]]*)\]\(([^)\s]+)\)", repl, text), n


def rewrite_plain(text: str, old: str, new: str):
    """裸路径（含反引号内、YAML 注释、散文）：按 token 边界替换，避免打到更长路径的前缀。"""
    pat = re.compile(re.escape(old) + r"(?![A-Za-z0-9_/.-])")
    out, n = pat.subn(new, text)
    return out, n


def load_aliases(path: Path):
    if not path.exists():
        return {"version": 1, "aliases": {}}
    import yaml
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    doc.setdefault("version", 1)
    doc.setdefault("aliases", {})
    return doc


def append_alias(path: Path, old: str, new: str, note: str):
    """把 旧→新 追加进别名表（组件键解析时归一；历史文本不回写）。"""
    import yaml
    doc = load_aliases(path)
    if doc["aliases"].get(old) == new:
        return False
    doc["aliases"][old] = new
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# 组件别名（数据）——EV-2026-129\n"
        "#\n"
        "# 用途只有一个：路径搬家之后，**历史引用仍要解析到同一个组件**。\n"
        "# `surface_basis.path` 的取值优先级最高来自 `decisions[type=action].conclusion`，\n"
        "# 而 decisions 是只追加的审计链、不许回写路径——不归一的话，同一处改动会被\n"
        "# 搬家前/后的卡拆成两个组件键，判据「同一组件重复做功」就会少报且不报错。\n"
        "#\n"
        "# 由 `scripts/rename_ref.py` 自动追加，不手写。语义是\"这个旧键要并到那个新键\"。\n"
        "\n"
    )
    body = yaml.safe_dump(doc, allow_unicode=True, sort_keys=True)
    write_text_lf(path, header + body, encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="移动/改名 tracked 文件后，一条命令改完引用（审计链豁免）")
    ap.add_argument("old", help="旧路径（仓库根相对）")
    ap.add_argument("new", help="新路径（仓库根相对，须已存在）")
    ap.add_argument("--apply", action="store_true", help="真写；默认只打印将改什么")
    ap.add_argument("--no-alias", action="store_true", help="不登记组件别名")
    ap.add_argument("--include-frozen", action="store_true",
                    help="连按内容哈希钉住的量尺件一起改（会弄红 holdout/scorecard，需重新封存）")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()

    root = args.root.resolve()
    old, new = args.old.strip("/"), args.new.strip("/")
    if not (root / new).exists():
        print(f"rename_ref: 新路径不存在：{new}\n  先 git mv，再跑本工具（防手误搬错）", file=sys.stderr)
        return 1
    if old == new:
        print("rename_ref: 旧路径与新路径相同，无事可做", file=sys.stderr)
        return 1

    files = tracked_files(root)
    frozen = set() if args.include_frozen else frozen_artifacts(root)
    changed, skipped_audit, skipped_frozen, total_plain, total_links = [], 0, [], 0, 0
    for rel in files:
        p = root / rel
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        head, dec, tail = text, "", ""
        if rel.startswith(AUDIT_PREFIXES):
            # 只追加档案整份跳过
            if old in text:
                skipped_audit += 1
            continue
        if rel in frozen and old in text:
            skipped_frozen.append(rel)
            continue
        if rel.startswith(CARDS_DIR + "/"):
            head, dec, tail = split_decisions(text)
        n0 = 0
        if rel == new:
            # 被移动的这份文件：先把它自己的相对链接按旧目录重算
            head, n0 = rebase_links(head, (root / old).parent, p.parent)
            tail, n0b = rebase_links(tail, (root / old).parent, p.parent)
            n0 += n0b
        new_head, n1 = rewrite_links(head, p.parent, root, old, new)
        new_head, n2 = rewrite_plain(new_head, old, new)
        new_tail, n3 = rewrite_plain(tail, old, new)
        if n0 or n1 or n2 or n3:
            total_plain += n2 + n3
            total_links += n1 + n0
            changed.append((rel, n1 + n0, n2 + n3))
            if args.apply:
                write_text_lf(p, new_head + dec + new_tail, encoding="utf-8")
        if dec and old in dec:
            skipped_audit += 1

    mode = "已写入" if args.apply else "dry-run（未写任何文件；加 --apply 才写）"
    print(f"rename_ref: {old} → {new}　{mode}")
    if not changed:
        print("  无需改动：检出里已没有指向旧路径的可改引用")
    for rel, n1, n2 in changed:
        print(f"  {rel}　链接 {n1} · 路径 {n2}")
    print(f"  合计：{len(changed)} 个文件、链接 {total_links} 处、路径 {total_plain} 处")
    if skipped_audit:
        print(f"  审计链豁免：{skipped_audit} 个文件含旧路径但一字未改"
              "（decisions 块 / docs/adr/ 是只追加档案；历史引用靠别名解析）")
    if skipped_frozen:
        print(f"  冻结件跳过：{len(skipped_frozen)} 个（按内容哈希钉住的量尺，改它们要重新封存 + 重建账本）："
              + "、".join(skipped_frozen[:3]) + ("…" if len(skipped_frozen) > 3 else ""))
        print("    确实要改：加 --include-frozen，随后跑 holdout.py --reseal --all 与 "
              "eval_scorecard.py --build，PR 带 holdout-change 标签")

    if not args.no_alias:
        if args.apply:
            wrote = append_alias(root / ALIAS_REL, old, new, "")
            print(f"  别名：{'已登记' if wrote else '已存在'} {old} → {new}（{ALIAS_REL}）")
        else:
            print(f"  别名：将登记 {old} → {new}（{ALIAS_REL}）")
    if not args.apply:
        print("  下一步：确认无误后加 --apply 重跑")
    return 0


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
