#!/usr/bin/env python3
# replay_prep.py —— 从缓存的 issue 线程生成回放测试的输入文件
#
# 措辞差回放（docs/eval-reports/0001 计划 Phase D 模式 1）：
#   case 的 symptoms 从全线程（含开发者结论）提炼；回放输入只用用户首帖——
#   朴素措辞、常无错误码、混无关信息，是真实工程师输入的合理代理。
#   两者的措辞差 = 防止"自己命中自己"的信息隔离。
#
# 用法：python3 scripts/replay_prep.py <threads_dir> <assessment.jsonl> <out_dir>
#   读取门槛通过的 issue，产出 out_dir/replay-input-<n>.md（首帖裁剪版）

import json
import re
import sys
from pathlib import Path


def clip_body(body: str, limit: int = 3500) -> str:
    """首帖裁剪：保错误栈与关键段，去长贴里的重复粘贴。日志裁剪原则（原则九）的入库版。"""
    if not body:
        return ""
    # 去 markdown 图片/链接修饰，保留文本
    body = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'[图:\1]', body)
    body = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', body)
    if len(body) <= limit:
        return body
    # 超长时保头尾（头：环境/症状描述；尾：结论性输出）
    return body[: limit * 2 // 3] + "\n\n……（中段裁剪）……\n\n" + body[-limit // 3:]


def main():
    threads_dir, assess_path, out_dir = (Path(p) for p in sys.argv[1:4])
    out_dir.mkdir(parents=True, exist_ok=True)
    assessment = [json.loads(l) for l in open(assess_path, encoding="utf-8")]
    selected = [a for a in assessment if a.get("gate_pass")]

    manifest = []
    for a in selected:
        n = a["number"]
        issue_file = threads_dir / f"issue-{n}.json"
        if not issue_file.exists():
            continue
        it = json.load(open(issue_file, encoding="utf-8"))
        replay = {
            "issue": n,
            "title": it["title"],
            "first_post": clip_body(it.get("body") or ""),
        }
        # 期望值来自评估结论（人核对象）
        replay["expected"] = {
            "category": a.get("category"),
            "root_cause_contains": a.get("one_line_root_cause", "")[:30],
        }
        outf = out_dir / f"replay-input-{n}.md"
        outf.write_text(
            f"# 回放输入（issue #{n}，仅首帖）\n\n"
            f"标题：{it['title']}\n\n---\n\n{replay['first_post']}\n",
            encoding="utf-8",
        )
        manifest.append({"issue": n, "file": str(outf), **replay["expected"]})

    mfile = out_dir / "replay-manifest.json"
    json.dump(manifest, open(mfile, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"生成 {len(manifest)} 个回放输入 → {out_dir}")
    print(f"manifest: {mfile}")


if __name__ == "__main__":
    main()
