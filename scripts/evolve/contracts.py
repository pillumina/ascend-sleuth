"""数据契约：样本、执行、结论、版本。

这里是字段与合法取值的唯一来源。上层（samples、records、cli）只通过
``to_dict`` / ``from_dict`` 交换数据，不另写一套字段名。

设计口径见 ``proposals/2026-11-17-self-evolution-design-appendix.md`` §A：

- ``status``：candidate / active / retired / rejected
- ``origin``：core（静态核心集）/ field（动态现场集）；active + origin=core 才是 core 样本
- ``purpose``：evaluation / feedback / test / regression / cross / scale
- ``object_type``：diagnosis / case / reference / trace

状态转换不在这里校验（唯一实现在 ``pools.check_transition``），这里只校验
字段存在、类型与枚举取值。核心模块只依赖标准库。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

STATUSES = ("candidate", "active", "retired", "rejected")
ORIGINS = ("core", "field")
PURPOSES = ("evaluation", "feedback", "test", "regression", "cross", "scale")
OBJECT_TYPE_VALUES = ("diagnosis", "case", "reference", "trace")
EXPECTED_KINDS = ("resolution", "assertion", "rubric")
PROVENANCE_TRIGGERS = ("diagnosis_end", "postmortem", "groom", "manual_case",
                       "issue_import")
PROVENANCE_CONFIDENCE = ("issue-verified", "maintainer-reviewed", "agent-reviewed")
PROVENANCE_EXTRACTIONS = ("auto", "manual")
_PROVENANCE_KEYS = {"trigger", "trace_ref", "report_ref", "captured_at",
                    "kb_rev", "sanitized", "redactions", "confidence",
                    "extraction"}
DECISIONS = ("accept", "insufficient", "reject", "unknown")
PROTOCOL_VERSION = "evolve-v1"


class ContractError(ValueError):
    """字段缺失、类型不对或枚举取值非法。"""


def now_iso() -> str:
    """UTC 时刻，秒级；样本历史与记录共用。"""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


_ID_EXTRA = set("._:-")


def valid_id(value: Any) -> bool:
    """样本 id 同时是文件名：只允许单段安全字符，挡住路径穿越。"""
    if not isinstance(value, str) or not value:
        return False
    if value in (".", ".."):
        return False
    if not (value[0].isalnum()):
        return False
    return all(ch.isalnum() or ch in _ID_EXTRA for ch in value)


def _enum_error(name: str, value: Any, allowed: tuple) -> Optional[str]:
    if value not in allowed:
        return f"{name} must be one of {list(allowed)}, got {value!r}"
    return None


def _optional_dict(name: str, value: Any) -> Optional[str]:
    if value is not None and not isinstance(value, dict):
        return f"{name} must be an object or null, got {type(value).__name__}"
    return None


def _drop_none(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, dict) and not value:
            continue
        if isinstance(value, list) and not value:
            continue
        out[key] = value
    return out


@dataclass
class Sample:
    """一个被评估的对象。"""

    id: str
    status: str = "candidate"
    object_type: str = "diagnosis"
    origin: str = "field"
    purpose: str = "evaluation"
    source: str = ""
    input: Dict[str, Any] = field(default_factory=dict)
    expected: Optional[Dict[str, Any]] = None
    expected_kind: str = "resolution"
    rubric: Optional[Dict[str, Any]] = None
    non_diagnostic: bool = False
    limits: Optional[Dict[str, Any]] = None
    proposed: Optional[Dict[str, Any]] = None
    provenance: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    notes: Optional[str] = None

    def errors(self, require_answer: bool = False) -> List[str]:
        """返回全部字段错误；空列表表示通过。

        ``require_answer=True`` 是入池/复核时的严格模式：候选也必须已有
        ``expected`` 或 ``rubric``（RFC 6.7 的复核清单）。默认模式只要求
        active 带答案，候选可以先落在队列里补答案。
        """
        errs: List[str] = []
        if not valid_id(self.id):
            errs.append(
                "id is required and must be a safe filename "
                "(letters/digits/._:-, no path separators)"
            )
        if not isinstance(self.source, str) or not self.source.strip():
            errs.append("source is required")
        for name, value, allowed in (
            ("status", self.status, STATUSES),
            ("object_type", self.object_type, OBJECT_TYPE_VALUES),
            ("origin", self.origin, ORIGINS),
            ("purpose", self.purpose, PURPOSES),
            ("expected_kind", self.expected_kind, EXPECTED_KINDS),
        ):
            message = _enum_error(name, value, allowed)
            if message:
                errs.append(message)
        for name, value in (
            ("input", self.input),
            ("expected", self.expected),
            ("rubric", self.rubric),
            ("limits", self.limits),
            ("proposed", self.proposed),
        ):
            message = _optional_dict(name, value)
            if message:
                errs.append(message)
        if not isinstance(self.non_diagnostic, bool):
            errs.append("non_diagnostic must be a boolean")
        if not isinstance(self.history, list):
            errs.append("history must be a list")
        has_answer = bool(self.rubric) or _expected_has_answer(self.expected)
        if self.expected and not self.rubric:
            for key in ("resolution", "fix", "fix_commit"):
                value = self.expected.get(key)
                if isinstance(value, str) and any(
                    marker in value.lower() for marker in ("待补", "todo", "tbd", "待定")
                ):
                    if require_answer or self.status == "active":
                        errs.append(f"expected.{key} is a placeholder, not an answer")
                    has_answer = False
                    break
        if self.status == "active" and not has_answer:
            errs.append("active sample must have expected or rubric")
        if require_answer and not has_answer:
            errs.append("sample must have expected or rubric before admission")
        if self.expected_kind == "rubric" and not self.rubric:
            errs.append("expected_kind=rubric requires rubric")
        if self.limits is not None and self.purpose != "scale":
            errs.append("limits is only valid for purpose=scale")
        errs.extend(_provenance_errors(self.provenance))
        return errs

    def validate(self, require_answer: bool = False) -> "Sample":
        errs = self.errors(require_answer=require_answer)
        if errs:
            raise ContractError("; ".join(errs))
        return self

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "status": self.status,
            "object_type": self.object_type,
            "origin": self.origin,
            "purpose": self.purpose,
            "source": self.source,
            "input": dict(self.input or {}),
            "expected": self.expected,
            "expected_kind": self.expected_kind,
            "rubric": self.rubric,
            "non_diagnostic": self.non_diagnostic,
            "limits": self.limits,
            "proposed": self.proposed,
            "provenance": self.provenance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "history": list(self.history or []),
            "notes": self.notes,
        }
        return _drop_none(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Sample":
        if not isinstance(data, dict):
            raise ContractError(f"sample must be an object, got {type(data).__name__}")
        unknown = [key for key in data if key not in _SAMPLE_KEYS]
        if unknown:
            raise ContractError(f"unknown sample field(s): {', '.join(sorted(unknown))}")
        try:
            sample = cls(
                id=data.get("id", ""),
                status=data.get("status", "candidate"),
                object_type=data.get("object_type", "diagnosis"),
                origin=data.get("origin", "field"),
                purpose=data.get("purpose", "evaluation"),
                source=data.get("source", ""),
                input=dict(data.get("input") or {}),
                expected=data.get("expected"),
                expected_kind=data.get("expected_kind", "resolution"),
                rubric=data.get("rubric"),
                non_diagnostic=data.get("non_diagnostic", False),
                limits=data.get("limits"),
                proposed=data.get("proposed"),
                provenance=data.get("provenance"),
                created_at=data.get("created_at"),
                updated_at=data.get("updated_at"),
                history=list(data.get("history") or []),
                notes=data.get("notes"),
            )
        except (TypeError, ValueError) as exc:
            raise ContractError(f"invalid sample: {exc}") from exc
        return sample


def _expected_has_answer(value: Any) -> bool:
    if not isinstance(value, dict):
        return bool(value)
    if "resolution" in value or "fix" in value:
        return any(str(value.get(key) or "").strip()
                   for key in ("resolution", "fix", "fix_commit"))
    for item in value.values():
        if isinstance(item, str):
            if item.strip():
                return True
        elif item not in (None, [], {}):
            return True
    return False


def source_needs_provenance(source: str) -> bool:
    """非 URL 来源按本地材料处理，必须带来源信息与脱敏结论。"""
    return "://" not in str(source or "").strip()


def _provenance_errors(value: Any) -> List[str]:
    """来源信息：可选对象；未知键与非法取值直接报错，不静默忽略。"""
    if value is None:
        return []
    if not isinstance(value, dict):
        return ["provenance must be an object or null"]
    unknown = [key for key in value if key not in _PROVENANCE_KEYS]
    errs = [f"unknown provenance field(s): {', '.join(sorted(unknown))}"] if unknown else []
    trigger = value.get("trigger")
    if trigger not in PROVENANCE_TRIGGERS:
        errs.append(f"provenance.trigger must be one of {list(PROVENANCE_TRIGGERS)}")
    for name in ("trace_ref", "report_ref", "captured_at", "kb_rev"):
        item = value.get(name)
        if item is not None and (not isinstance(item, str) or not item.strip()):
            errs.append(f"provenance.{name} must be a non-empty string or null")
    if not isinstance(value.get("sanitized"), bool):
        errs.append("provenance.sanitized must be boolean")
    redactions = value.get("redactions", [])
    if not isinstance(redactions, list) or not all(
            isinstance(item, str) and item.strip() for item in redactions):
        errs.append("provenance.redactions must be a list of non-empty strings")
    confidence = value.get("confidence")
    if confidence not in PROVENANCE_CONFIDENCE:
        errs.append(f"provenance.confidence must be one of {list(PROVENANCE_CONFIDENCE)}")
    extraction = value.get("extraction")
    if extraction not in PROVENANCE_EXTRACTIONS:
        errs.append(f"provenance.extraction must be one of {list(PROVENANCE_EXTRACTIONS)}")
    return errs


_SAMPLE_KEYS = {
    "id", "status", "object_type", "origin", "purpose", "source", "input",
    "expected", "expected_kind", "rubric", "non_diagnostic", "limits",
    "proposed", "provenance", "created_at", "updated_at", "history", "notes",
}


@dataclass
class Version:
    """让一次执行与一次结论可复现的坐标。"""

    protocol: str
    policy: str
    base_kb: str
    candidate_kb: str
    candidate: str
    model: str
    algorithm: str = "baseline"
    algorithm_version: str = "manual"
    budget: Optional[Dict[str, Any]] = None
    seed: Optional[int] = None

    REQUIRED = ("protocol", "policy", "base_kb", "candidate_kb", "candidate", "model")
    OPTIONAL = ("algorithm", "algorithm_version", "budget", "seed")

    def errors(self) -> List[str]:
        errs: List[str] = []
        for name in self.REQUIRED:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                errs.append(f"versions.{name} is required")
        for name in ("algorithm", "algorithm_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                errs.append(f"versions.{name} is required")
        if self.budget is not None and not isinstance(self.budget, dict):
            errs.append("versions.budget must be an object or null")
        if self.seed is not None and (
            not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 0
        ):
            errs.append("versions.seed must be a non-negative integer or null")
        return errs

    def validate(self) -> "Version":
        errs = self.errors()
        if errs:
            raise ContractError("; ".join(errs))
        return self

    def to_dict(self) -> Dict[str, Any]:
        data = {name: getattr(self, name) for name in self.REQUIRED}
        data["algorithm"] = self.algorithm
        data["algorithm_version"] = self.algorithm_version
        if self.budget is not None:
            data["budget"] = self.budget
        if self.seed is not None:
            data["seed"] = self.seed
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Version":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ContractError("versions must be an object")
        known = set(cls.REQUIRED + cls.OPTIONAL)
        unknown = [key for key in data if key not in known]
        if unknown:
            raise ContractError(f"unknown versions field(s): {', '.join(sorted(unknown))}")
        values = {name: data.get(name, "") for name in cls.REQUIRED}
        values["algorithm"] = data.get("algorithm", "baseline") or "baseline"
        values["algorithm_version"] = data.get("algorithm_version", "manual") or "manual"
        values["budget"] = data.get("budget")
        values["seed"] = data.get("seed")
        version = cls(**values)
        version.validate()
        return version


@dataclass
class Patch:
    """优化算法的提案；只描述改什么，不直接写库、不合入。"""

    target_kind: str   # skill / knowledge / tooling / harness
    target_component: str
    summary: str
    algorithm: str
    algorithm_version: str
    payload: Dict[str, Any] = field(default_factory=dict)
    budget: Optional[Dict[str, Any]] = None
    seed: Optional[int] = None

    def validate(self) -> "Patch":
        for name in ("target_kind", "target_component", "summary",
                     "algorithm", "algorithm_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ContractError(f"patch.{name} is required")
        if not isinstance(self.payload, dict):
            raise ContractError("patch.payload must be an object")
        if self.budget is not None and not isinstance(self.budget, dict):
            raise ContractError("patch.budget must be an object or null")
        if self.seed is not None and (
            not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 0
        ):
            raise ContractError("patch.seed must be a non-negative integer or null")
        return self


@dataclass
class Run:
    """在某一组版本下对样本做的一次评估。"""

    sample: str
    versions: Version
    metrics: Dict[str, Any] = field(default_factory=dict)
    cost: Optional[Dict[str, Any]] = None
    harness_session: Optional[str] = None
    trace_ref: Optional[str] = None
    at: str = ""

    def errors(self) -> List[str]:
        errs: List[str] = []
        if not isinstance(self.sample, str) or not self.sample.strip():
            errs.append("run.sample is required")
        try:
            Version.from_dict(self.versions)
        except ContractError as exc:
            errs.append(str(exc))
        if not isinstance(self.metrics, dict):
            errs.append("run.metrics must be an object")
        message = _optional_dict("run.cost", self.cost)
        if message:
            errs.append(message)
        return errs

    def validate(self) -> "Run":
        errs = self.errors()
        if errs:
            raise ContractError("; ".join(errs))
        return self

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "sample": self.sample,
            "versions": self.versions.to_dict(),
            "metrics": dict(self.metrics or {}),
            "cost": self.cost,
            "harness_session": self.harness_session,
            "trace_ref": self.trace_ref,
            "at": self.at,
        }
        return _drop_none(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Run":
        if not isinstance(data, dict):
            raise ContractError("run must be an object")
        unknown = [key for key in data if key not in _RUN_KEYS]
        if unknown:
            raise ContractError(f"unknown run field(s): {', '.join(sorted(unknown))}")
        run = cls(
            sample=data.get("sample", ""),
            versions=Version.from_dict(data.get("versions") or {}),
            metrics=dict(data.get("metrics") or {}),
            cost=data.get("cost"),
            harness_session=data.get("harness_session"),
            trace_ref=data.get("trace_ref"),
            at=data.get("at", ""),
        )
        run.validate()
        return run


_RUN_KEYS = {
    "sample", "versions", "metrics", "cost", "harness_session", "trace_ref", "at",
}


@dataclass
class Conclusion:
    """比较基线与候选之后得到的判断。"""

    decision: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    cost: Optional[Dict[str, Any]] = None
    reason: str = ""
    versions: Optional[Version] = None
    pool_hash: Optional[str] = None
    reuse_index: int = 0
    alpha_eff: Optional[float] = None
    b: Optional[int] = None
    c: Optional[int] = None
    n: Optional[int] = None
    p_value: Optional[float] = None
    delta_q: Optional[float] = None
    cost_ratio: Optional[float] = None
    sample: Optional[str] = None
    card: Optional[str] = None
    proposal: Optional[str] = None
    pool: Optional[str] = None
    at: str = ""

    def errors(self) -> List[str]:
        errs: List[str] = []
        message = _enum_error("decision", self.decision, DECISIONS)
        if message:
            errs.append(message)
        if not isinstance(self.metrics, dict):
            errs.append("conclusion.metrics must be an object")
        message = _optional_dict("conclusion.cost", self.cost)
        if message:
            errs.append(message)
        if self.versions is not None:
            try:
                Version.from_dict(self.versions)
            except ContractError as exc:
                errs.append(str(exc))
        if not isinstance(self.reuse_index, int) or self.reuse_index < 0:
            errs.append("reuse_index must be a non-negative integer")
        for name in ("b", "c", "n"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or value < 0):
                errs.append(f"{name} must be a non-negative integer or null")
        for name in ("delta_q", "cost_ratio"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
            ):
                errs.append(f"{name} must be a number or null")
        for name in ("sample", "card", "proposal", "pool"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                errs.append(f"{name} must be a non-empty string or null")
        return errs

    def validate(self) -> "Conclusion":
        errs = self.errors()
        if errs:
            raise ContractError("; ".join(errs))
        return self

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "decision": self.decision,
            "metrics": dict(self.metrics or {}),
            "cost": self.cost,
            "reason": self.reason,
            "versions": self.versions.to_dict() if self.versions else None,
            "pool_hash": self.pool_hash,
            "reuse_index": self.reuse_index,
            "alpha_eff": self.alpha_eff,
            "b": self.b,
            "c": self.c,
            "n": self.n,
            "p_value": self.p_value,
            "delta_q": self.delta_q,
            "cost_ratio": self.cost_ratio,
            "sample": self.sample,
            "card": self.card,
            "proposal": self.proposal,
            "pool": self.pool,
            "at": self.at,
        }
        return _drop_none(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Conclusion":
        if not isinstance(data, dict):
            raise ContractError("conclusion must be an object")
        unknown = [key for key in data if key not in _CONCLUSION_KEYS]
        if unknown:
            raise ContractError(f"unknown conclusion field(s): {', '.join(sorted(unknown))}")
        versions = data.get("versions")
        conclusion = cls(
            decision=data.get("decision", ""),
            metrics=dict(data.get("metrics") or {}),
            cost=data.get("cost"),
            reason=data.get("reason", ""),
            versions=Version.from_dict(versions) if versions else None,
            pool_hash=data.get("pool_hash"),
            reuse_index=data.get("reuse_index", 0),
            alpha_eff=data.get("alpha_eff"),
            b=data.get("b"),
            c=data.get("c"),
            n=data.get("n"),
            p_value=data.get("p_value"),
            delta_q=data.get("delta_q"),
            cost_ratio=data.get("cost_ratio"),
            sample=data.get("sample"),
            card=data.get("card"),
            proposal=data.get("proposal"),
            pool=data.get("pool"),
            at=data.get("at", ""),
        )
        conclusion.validate()
        return conclusion


_CONCLUSION_KEYS = {
    "decision", "metrics", "cost", "reason", "versions", "pool_hash",
    "reuse_index", "alpha_eff", "b", "c", "n", "p_value", "delta_q",
    "cost_ratio", "sample", "card", "proposal", "pool", "at",
}
