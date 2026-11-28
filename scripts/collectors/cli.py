#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户现场采集器的只读清单与打包入口。

用法：
  python3 scripts/collectors/cli.py list [--json]
  python3 scripts/collectors/cli.py show <name> [--json]
  python3 scripts/collectors/cli.py bundle <name> --out-dir <新目录> [--json]

这里不执行任何采集，也不访问网络：`bundle` 只把脚本、依赖和说明复制到一个新目录，
由工程师交给客户在现场运行。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

from registry import COLLECTORS, UPSTREAM_COMMIT_FULL, UPSTREAM_URL, find  # noqa: E402

SCHEMA_VERSION = 1


def force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def _source(item: dict, file_entry: dict) -> Path:
    return REPO / file_entry["source"]


def _entry_source(item: dict) -> Path | None:
    entry = item.get("entry")
    if not entry:
        return None
    for file_entry in item["files"]:
        if file_entry["target"] == entry:
            return REPO / file_entry["source"]
    return None


def _command(item: dict, script: str) -> str | None:
    template = item.get("command")
    return template.format(script=script) if template else None


def _payload(item: dict) -> dict:
    entry_source = _entry_source(item)
    entry_target = item.get("entry")
    files = []
    for file_entry in item["files"]:
        source = _source(item, file_entry)
        files.append(
            {
                "source": file_entry["source"],
                "source_absolute": str(source),
                "target": file_entry["target"],
                "exists": source.is_file(),
            }
        )
    source_command = None
    bundle_command = None
    if entry_source is not None and entry_target:
        source_command = _command(item, _rel(entry_source))
        bundle_command = _command(item, entry_target)
    return {
        "name": item["name"],
        "title": item["title"],
        "kind": item["kind"],
        "purpose": item["purpose"],
        "entry": entry_target,
        "entry_source": _rel(entry_source) if entry_source else None,
        "source_command": source_command,
        "bundle_command": bundle_command,
        "environments": item["environments"],
        "privilege": item["privilege"],
        "impact": item["impact"],
        "duration": item["duration"],
        "outputs": item["outputs"],
        "sensitive": item["sensitive"],
        "consumer": item.get("consumer"),
        "steps": item.get("steps") or [],
        "notes": item.get("notes") or [],
        "files": files,
        "installed": all(file_entry["exists"] for file_entry in files),
    }


def cmd_list(args: argparse.Namespace) -> int:
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "name": item["name"],
                        "title": item["title"],
                        "kind": item["kind"],
                        "purpose": item["purpose"],
                        "outputs": item["outputs"],
                        "consumer": item.get("consumer"),
                    }
                    for item in COLLECTORS
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print(f"{'name':<20} {'kind':<8} 用途")
    for item in COLLECTORS:
        purpose = item["purpose"]
        if len(purpose) > 56:
            purpose = purpose[:56] + "…"
        print(f"{item['name']:<20} {item['kind']:<8} {purpose}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    item = find(args.name)
    if item is None:
        print(f"未知采集器：{args.name}；可用：{', '.join(x['name'] for x in COLLECTORS)}", file=sys.stderr)
        return 2
    payload = _payload(item)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["installed"] else 1

    print(f"采集器：{payload['name']}（{payload['title']}）")
    print(f"类型：{'脚本' if payload['kind'] == 'script' else '人工操作'}")
    print(f"用途：{payload['purpose']}")
    print("适用环境：")
    for value in payload["environments"]:
        print(f"  - {value}")
    print(f"权限：{payload['privilege']}")
    print(f"运行影响：{payload['impact']}")
    print(f"预计耗时：{payload['duration']}")
    if payload["source_command"]:
        print(f"建议命令：{payload['source_command']}")
    if payload["steps"]:
        print("执行步骤：")
        for index, step in enumerate(payload["steps"], 1):
            print(f"  {index}. {step}")
    print("脚本文件：" if payload["kind"] == "script" else "交付文件：")
    for file_entry in payload["files"]:
        mark = "" if file_entry["exists"] else "（缺失）"
        print(f"  - {file_entry['source']}{mark}")
    print("客户需要返回：")
    for value in payload["outputs"]:
        print(f"  - {value}")
    if payload["consumer"]:
        print(f"采集后交给：{payload['consumer']}（scripts/analyzers/cli.py run {payload['consumer']}）")
    else:
        print("采集后交给：无自动适配器；由诊断 agent 直接读 JSON 证据")
    print(f"敏感信息：{payload['sensitive']}")
    if payload["notes"]:
        print("注意：")
        for value in payload["notes"]:
            print(f"  - {value}")
    return 0 if payload["installed"] else 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _readme(item: dict) -> str:
    lines = [
        f"# {item['title']}（{item['name']}）",
        "",
        "本采集器在客户现场执行。Sleuth 只负责推荐与交付文件，不操作客户环境。",
        "",
        "## 用途",
        "",
        item["purpose"],
        "",
        "## 适用环境",
        "",
    ]
    lines += [f"- {value}" for value in item["environments"]]
    lines += [
        "",
        "## 权限",
        "",
        item["privilege"],
        "",
        "## 运行影响",
        "",
        item["impact"],
        "",
        f"预计耗时：{item['duration']}",
        "",
    ]
    if item["kind"] == "script":
        lines += ["## 执行命令", "", "```bash", _command(item, item["entry"]), "```", ""]
    else:
        lines += ["## 执行步骤", ""]
        lines += [f"{index}. {step}" for index, step in enumerate(item.get("steps") or [], 1)]
        lines += [""]
    lines += ["## 客户需要返回", ""]
    lines += [f"- {value}" for value in item["outputs"]]
    lines += [
        "",
        "## 采集后交给",
        "",
        (
            f"把结果回传给 Sleuth 侧，由 `{item['consumer']}` 分析"
            f"（Sleuth 侧执行：`python3 scripts/analyzers/cli.py run {item['consumer']} --inputs <绝对路径>`）。"
            if item.get("consumer")
            else "没有自动适配器；把 JSON 与诊断材料一起交给诊断 agent 读取。"
        ),
        "",
        "## 敏感信息",
        "",
        item["sensitive"],
        "",
    ]
    if item.get("notes"):
        lines += ["## 注意", ""]
        lines += [f"- {value}" for value in item["notes"]]
        lines += [""]
    lines += [
        "## 来源",
        "",
        f"上游：{UPSTREAM_URL}，提交 `{UPSTREAM_COMMIT_FULL}`。",
        "上游未声明开源许可；迁入与再分发依据迁入方确认的作者口头授权，尚无书面许可记录。",
        "",
    ]
    return "\n".join(lines)


def cmd_bundle(args: argparse.Namespace) -> int:
    item = find(args.name)
    if item is None:
        print(f"未知采集器：{args.name}；可用：{', '.join(x['name'] for x in COLLECTORS)}", file=sys.stderr)
        return 2
    payload = _payload(item)
    missing = [file_entry["source"] for file_entry in payload["files"] if not file_entry["exists"]]
    if missing:
        print("以下源文件缺失，未生成采集包：" + "；".join(missing), file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir).expanduser().resolve()
    if out_dir.exists():
        if not out_dir.is_dir():
            print(f"输出路径不是目录：{out_dir}", file=sys.stderr)
            return 1
        if any(out_dir.iterdir()):
            print(f"输出目录不是空目录，拒绝覆盖：{out_dir}", file=sys.stderr)
            return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for file_entry in item["files"]:
        source = _source(item, file_entry)
        target = out_dir / file_entry["target"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if target.suffix in (".sh", ".py", ".pyz"):
            try:
                target.chmod(0o755)
            except OSError:
                pass
        files.append(
            {
                "path": file_entry["target"],
                "sha256": _sha256(target),
                "source": file_entry["source"],
            }
        )

    (out_dir / "README.md").write_text(_readme(item), encoding="utf-8")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "name": item["name"],
        "title": item["title"],
        "kind": item["kind"],
        "purpose": item["purpose"],
        "command": _command(item, item["entry"]) if item.get("entry") else None,
        "environments": item["environments"],
        "privilege": item["privilege"],
        "impact": item["impact"],
        "duration": item["duration"],
        "outputs": item["outputs"],
        "sensitive": item["sensitive"],
        "consumer": item.get("consumer"),
        "steps": item.get("steps") or [],
        "notes": item.get("notes") or [],
        "files": files,
        "upstream": {
            "repository": UPSTREAM_URL,
            "commit": UPSTREAM_COMMIT_FULL,
            "license": "none-declared",
            "authorization": "作者口头授权迁入与再分发；尚无书面许可记录",
        },
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    (out_dir / "collector.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if args.json:
        print(json.dumps({"bundle_dir": str(out_dir), "files": files}, ensure_ascii=False, indent=2))
    else:
        print(f"采集包：{out_dir}")
        print("文件：")
        for file_entry in files:
            print(f"  - {file_entry['path']}  sha256={file_entry['sha256'][:16]}…")
        print("说明：README.md")
        print("清单：collector.json")
        print(f"BUNDLE_DIR={out_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    parser = argparse.ArgumentParser(description="Sleuth 客户现场采集器清单")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="列出全部采集器")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="查看一个采集器的完整交付说明")
    show.add_argument("name")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_show)

    bundle = sub.add_parser("bundle", help="把脚本、依赖与说明复制到一个新目录")
    bundle.add_argument("name")
    bundle.add_argument("--out-dir", required=True, help="必须是不存在或空的新目录")
    bundle.add_argument("--json", action="store_true")
    bundle.set_defaults(func=cmd_bundle)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
