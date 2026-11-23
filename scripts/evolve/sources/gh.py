"""``gh`` 命令的共用输入整理与错误映射。

两层消费同一份规则：issue 源的 GitHub 实现与 issue 摄取适配器。错误映射里的
三条文案直接给工程师照做（装 gh / 登录 / 看 stderr 尾部）。
"""

from typing import Any, List

from ..adapters import AdapterError


def label_names(value: Any) -> List[str]:
    """把 ``gh`` 返回的标签（字符串或 ``[{name}]``）统一成名称列表。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    out: List[str] = []
    for item in value:
        name = item.get("name") if isinstance(item, dict) else item
        text = str(name or "").strip()
        if text:
            out.append(text)
    return out


def gh_error(exc: BaseException) -> AdapterError:
    """把 ``gh`` 的失败归一成可照做的提示。"""
    if isinstance(exc, FileNotFoundError):
        return AdapterError(
            "gh CLI not found; install GitHub CLI and run `gh auth login` before "
            "ingesting issues"
        )
    stderr = str(getattr(exc, "stderr", "") or "").strip()
    lowered = stderr.lower()
    if "auth" in lowered or "login" in lowered or "credential" in lowered:
        return AdapterError(
            "gh is not authenticated; run `gh auth login` before ingesting issues"
        )
    detail = stderr[-500:] if stderr else str(exc)
    return AdapterError(f"gh api failed: {detail}")
