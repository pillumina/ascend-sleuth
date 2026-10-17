#!/usr/bin/env python3
"""migrate_upstream_anchors.py —— 给已有案例补 `upstream` 锚点（一次性迁移，不是每次 groom 都跑）。

为什么值得补：外部对照闭环（`docs/mechanism/diagnosis-observability.md` 3.6）的分母是「有上游
关联的案例」。字段刚加进 schema 时全库一条都没有，于是这个指标的分母是 0，`verify_upstream_outcomes.py`
跑出来的全是「不可对照」——那是**没数据**，不是「上游都没确认」。补锚点让这条闭环有分母。

**只补能机械判定的那些**，判据两条同时成立才写：

  1. 案例头部注释里**只有一个** GitHub issue / PR 链接（多个说明正文还引了别的 issue，那是参照
     而不是来源，机械分不出哪个是锚点）；
  2. 链接里的编号**等于案例 id 末尾的数字**（`VLLM-ASC-12430` ↔ issue 12430）——这一条是独立
     佐证：id 与来源编号一致，说明这个链接就是这条案例的来源，而不是顺带提到的兄弟 issue。
     实测全库 117 条满足且无一例冲突。

判不准的一律**不写**，列进报告交人（宁缺勿错：写错锚点会让自动查证把「内容与别的 issue 一致」
记成这条案例的外部验证）。剩下的分两类：头部没有链接的（来源是内部分析或工程师输入）、头部有
多个链接的（人工确认哪一个才是来源）。

用法：
  python3 scripts/migrate_upstream_anchors.py            # dry-run：列出将写与将交回人处理的
  python3 scripts/migrate_upstream_anchors.py --apply    # 写进案例文件
  python3 scripts/migrate_upstream_anchors.py --root <检出>

退出码：0 = 成功（含「没有要补的」）；2 = 参数或环境不可用。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _stdio import pin_utf8_stdio, write_text_lf  # noqa: E402

URL_RE = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/(issues|pull)/(\d+)")
ID_NUM_RE = re.compile(r"(\d+)$")


def scan_case(path: Path):
    """一条案例 → {id, header_urls, needs, anchor}；不是案例文件返回 None。"""
    text = path.read_text(encoding="utf-8")
    if "cases:" not in text:
        return None
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return None
    cases = doc.get("cases") or []
    if not cases or not isinstance(cases[0], dict):
        return None
    case = cases[0]
    cid = str(case.get("id") or "")
    if case.get("upstream") is not None:
        return {"id": cid, "state": "已有锚点", "anchor": None, "text": text}
    header = text.split("cases:", 1)[0]
    urls = sorted(set(URL_RE.findall(header)))
    if not urls:
        return {"id": cid, "state": "头部没有上游链接（来源是内部排查或工程师输入）",
                "anchor": None, "text": text}
    if len(urls) > 1:
        return {"id": cid, "state": f"头部有 {len(urls)} 个上游链接，分不出哪个是来源",
                "anchor": None, "text": text}
    repo, kind, num = urls[0]
    m = ID_NUM_RE.search(cid)
    if not m or m.group(1) != num:
        return {"id": cid, "state": f"链接编号 {num} 与 id 末尾数字不一致，不敢当来源",
                "anchor": None, "text": text}
    key = "issue" if kind == "issues" else "pr"
    return {"id": cid, "state": "可补", "text": text,
            "anchor": {"repo": repo, key: int(num),
                       "url": f"https://github.com/{repo}/{kind}/{num}"}}


def insert_anchor(text: str, anchor: dict) -> str:
    """把锚点插到 `- id:` 那一行之后（案例的第一个字段位置）。

    插在开头而不是文件末尾：上游锚点是**来源**信息，与 `id` / `title` 同属"这条案例是什么"，
    丢在文件尾部半年后没人会把它与正文关联起来。锚点本身是可选字段，位置不影响解析。
    """
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("- id:"):
            indent = ln[: len(ln) - len(ln.lstrip())] + "  "
            key = "issue" if "issue" in anchor else "pr"
            block = [
                f"{indent}# 上游锚点：外部对照查证（scripts/verify_upstream_outcomes.py）按它查上游状态，",
                f"{indent}#   结局写进 validation_record。它判断的是内容对不对，不是现场是否解决。",
                f"{indent}upstream:",
                f"{indent}  - repo: {anchor['repo']}",
                f"{indent}    {key}: {anchor[key]}",
                f"{indent}    url: {anchor['url']}",
            ]
            return "\n".join(lines[: i + 1] + block + lines[i + 1:])
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description="给已有案例补 upstream 锚点（一次性迁移）")
    ap.add_argument("--apply", action="store_true", help="真的写（默认 dry-run）")
    ap.add_argument("--root", default=None, help="检出根（默认：脚本上两级）")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    kdir = root / "knowledge"
    if not kdir.is_dir():
        print(f"knowledge/ 不存在：{kdir}", file=sys.stderr)
        return 2

    todo, skipped, already = [], [], 0
    for f in sorted(kdir.rglob("*.yaml")):
        if f.name.startswith("_"):
            continue
        info = scan_case(f)
        if info is None:
            continue
        if info["state"] == "已有锚点":
            already += 1
            continue
        (todo if info["anchor"] else skipped).append((f, info))

    print(f"扫描 {len(todo) + len(skipped) + already} 条案例：可补 {len(todo)}、"
          f"交人处理 {len(skipped)}、已有锚点 {already}。")
    for f, info in todo:
        a = info["anchor"]
        key = "issue" if "issue" in a else "pr"
        print(f"  + {f.relative_to(root)}  {a['repo']} {key} #{a[key]}")
    if skipped:
        print(f"\n以下 {len(skipped)} 条判不准，交人处理（脚本不写）：")
        for f, info in skipped:
            print(f"  - {f.relative_to(root)}：{info['state']}")
    if not todo:
        print("\n没有可机械补的锚点。")
        return 0
    if not args.apply:
        print("\n--dry-run（默认）：未写任何文件。确认后加 --apply。")
        return 0
    for f, info in todo:
        write_text_lf(f, insert_anchor(info["text"], info["anchor"]), encoding="utf-8")
    print(f"\n已给 {len(todo)} 条案例补上 upstream 锚点。"
          "接着跑：python3 scripts/build_index.py（案例内容变了，索引要重建）")
    return 0


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
