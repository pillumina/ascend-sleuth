"""数据源接口。

``source_id`` 是稳定来源键，同时用于 state 分区与候选 ``source`` 前缀：
GitHub 为 ``github/<repo>``（保持旧 state 键不变），本地导出为 ``local/<repo>``。
"""

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class IssueSource(Protocol):
    """一条 issue 源需要提供的两个动作。"""

    @property
    def source_id(self) -> str:
        ...

    def list_issues(self, repo: str, labels, since, state: str = "closed") -> List[Dict[str, Any]]:
        """返回精简元数据；不要求含 body。"""
        ...

    def fetch_issue(self, repo: str, number: Any) -> Dict[str, Any]:
        """返回首帖 title/body/closed_at；不读评论。"""
        ...
