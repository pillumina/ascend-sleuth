"""端口：进程内数据流接口。

只有 Protocol 定义，不含实现；读文件、调模型、发 PR 都由适配器负责。
核心包不 import 适配器，CLI 也只依赖这里的形状。
"""

from typing import Any, Dict, List, Protocol, runtime_checkable

from .contracts import Patch, Run, Sample, Version


@runtime_checkable
class SampleSource(Protocol):
    """样本源。"""

    def load(self) -> List[Sample]:
        ...


@runtime_checkable
class Evaluator(Protocol):
    """执行器：样本 + 版本 → 执行。执行器拿到的样本不含答案。"""

    def evaluate(self, sample: Sample, versions: Version) -> Run:
        ...


@runtime_checkable
class Scorer(Protocol):
    """评分器：样本 + 执行 → 指标字典。"""

    def score(self, sample: Sample, run: Run) -> Dict[str, Any]:
        ...


@runtime_checkable
class Optimizer(Protocol):
    """优化算法适配器：只产出 Patch 提案，不直接写库或合入。"""

    id: str
    version: str
    scope: str

    def propose(self, target: str, observations: List[Any], current: Any,
                budget: Dict[str, Any]) -> Patch:
        ...


@runtime_checkable
class RecordStore(Protocol):
    """只追加记录存储。"""

    def append(self, record: Dict[str, Any]) -> None:
        ...

    def read(self) -> List[Dict[str, Any]]:
        ...


@runtime_checkable
class Brief(Protocol):
    """周读数：记录 + 指标 → 人读报告。"""

    def render(self, records: List[Dict[str, Any]], metrics: Dict[str, Any]) -> str:
        ...
