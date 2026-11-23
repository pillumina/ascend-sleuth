"""知识库内容哈希：评测版本坐标里的 ``base_kb`` / ``candidate_kb``。

为什么不是 HEAD 短 sha：一份结论要能回答「同一份知识库上重跑会不会得到同一结论」。
HEAD 只说明提交，不说明 ``knowledge/`` 的内容；同一提交下有人改了未提交的 case，
HEAD 不变而评测对象已经变了。内容哈希按路径与字节确定性计算，基线、候选 worktree
各算一份，差异就是候选补丁。

只算 ``knowledge/`` 下的 YAML 与 Markdown；``references/`` 与运行时件不进这个坐标。
纯函数：调用方给根目录，不读环境变量、不打印。
"""

import hashlib
from pathlib import Path

SUFFIXES = (".yaml", ".yml", ".md")
UNKNOWN = "unknown"


def content_rev(root) -> str:
    """→ 12 位内容哈希；目录不存在或没有可读文件时返回 ``unknown``（不编假值）。"""
    base = Path(root)
    knowledge = base / "knowledge"
    if not knowledge.is_dir():
        return UNKNOWN
    digest = hashlib.sha256()
    files = 0
    for path in sorted(knowledge.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        try:
            body = path.read_bytes()
            rel = path.relative_to(base).as_posix()
        except OSError:
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(body)
        digest.update(b"\0")
        files += 1
    if not files:
        return UNKNOWN
    return digest.hexdigest()[:12]
