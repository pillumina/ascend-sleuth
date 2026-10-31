"""Groom 测试共用的临时仓库与夹具（不是测试模块本身）。"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE_TMPL = """cases:
  - id: {cid}
    title: "{title}"
    category: {category}
    tags: [{tags}]
    symptoms:
{symptoms}
    root_cause: "{root_cause}"
    fix: "{fix}"
    severity: service-affecting
    fix_type: config-change
    quickly_check:
      primary:
        command_template: "grep -i '{sig}' {{{{log_path}}}}"
        expected: "regex:{sig}"
    diagnosis:
      - check: "确认前提"
        command_template: "echo {cid}"
        expected: "regex:{cid}"
"""


def env():
    e = dict(os.environ)
    e["PYTHONUTF8"] = "1"
    e["PYTHONIOENCODING"] = "utf-8"
    return e


def git(repo: Path, *args, check=True):
    p = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env())
    if check and p.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} 失败：{p.stderr}")
    return p


def run_py(repo: Path, *args):
    return subprocess.run([sys.executable, *args], cwd=str(repo), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env(), timeout=300)


def write_case(repo: Path, rel: str, cid, title="测试 case", category="interrupt",
               symptoms=("测试症状",), root_cause="测试根因", fix="测试修复",
               tags=("test",), sig=None):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    symptoms_yaml = "\n".join(f'      - "{s}"' for s in symptoms)
    text = CASE_TMPL.format(
        cid=cid, title=title, category=category, tags=", ".join(tags),
        symptoms=symptoms_yaml, root_cause=root_cause, fix=fix, sig=sig or cid,
    )
    path.write_text(text, encoding="utf-8")
    return path


def init_repo(repo: Path, cases=None):
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "groom@example.com")
    git(repo, "config", "user.name", "Groom Test")
    shutil.copytree(ROOT / "scripts", repo / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    # 用真实 .gitignore：inbox 草稿、groom sidecar、traces 等运行时件不该被测试的
    # `git add -A` 扫进提交（否则 reset 会把"本地草稿"一起抹掉，测出一个假缺陷）。
    shutil.copy2(ROOT / ".gitignore", repo / ".gitignore")
    for rel, kwargs in (cases or {}).items():
        write_case(repo, rel, **kwargs)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    return repo


def commit_all(repo: Path, message="update"):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def make_index(repo: Path):
    p = run_py(repo, "scripts/build_index.py")
    if p.returncode != 0:
        raise AssertionError(f"build_index 失败：{p.stdout}\n{p.stderr}")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "index")


def snapshot_meta(repo: Path, commit=None, authoritative=True, fresh=True):
    commit = commit or git(repo, "rev-parse", "HEAD").stdout.strip()
    return {
        "schema": "groom-snapshot/v1", "ok": True, "repo": str(repo),
        "branch": "main", "remote": "origin", "ref": "refs/remotes/origin/main",
        "commit": commit, "short": commit[:12], "fresh": fresh,
        "authoritative": authoritative, "worktree": str(repo),
        "index": {"state": "verified", "detail": None},
        "inbox": str(repo / "postmortems" / "inbox"),
    }


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_draft(repo: Path, key="draft-a", **kwargs):
    inbox = repo / "postmortems" / "inbox"
    case = write_case(repo, f"postmortems/inbox/{key}.case.yaml", **kwargs)
    return case
