"""样本本地存储与生命周期操作。

候选、active/field、active/core 三类样本都放本地运行件 ``<root>/.s2-replay/evolve/samples/``
（``.s2-replay/`` 已 gitignore）；一条样本一个 YAML，写入走临时文件 + 原子替换。

状态转换只调用 ``pools.check_transition``，这里不复制状态机。所有会给状态
带来变化的操作都记时间、原因与操作人。
"""

import os
import tempfile
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .contracts import (
    ORIGINS,
    source_needs_provenance,
    PURPOSES,
    STATUSES,
    Sample,
    now_iso,
    valid_id,
)
from .object_types import OBJECT_TYPES
from .pools import (
    assert_origin_transition,
    assert_purpose_transition,
    assert_transition,
    check_transition,
    source_group,
    split_test,
    stratum_of,
)

EVOLVE_DIR = Path(".s2-replay") / "evolve"
SAMPLES_DIRNAME = "samples"


class StoreError(RuntimeError):
    """样本文件缺失、重复、格式错或状态转换非法。"""


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", suffix=".yaml", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class SampleStore:
    """本地样本库。``root`` 是仓库检出目录（不是 ``.s2-replay`` 本身）。"""

    def __init__(self, root: Optional[Path] = None, base: Optional[Path] = None) -> None:
        """``root`` → ``<root>/.s2-replay/evolve``；``base`` 直接指定该目录。

        显式 ``base`` 用于把本地样本锚到主检出（CLI 默认行为）；测试与 ``--root``
        用 ``root`` 保持检出内隔离。
        """
        if base is not None:
            self.base = Path(base)
            self.root = self.base.parent.parent if self.base.parent.name == ".s2-replay" \
                else self.base.parent
        elif root is not None:
            self.root = Path(root)
            self.base = self.root / EVOLVE_DIR
        else:
            raise StoreError("SampleStore requires root or base")
        self.samples_dir = self.base / SAMPLES_DIRNAME
        self.core_dir = self.root / "eval" / "core" / "samples"

    # ---------------------------------------------------------------- 读取
    def path_for(self, id: str) -> Path:
        sample_id = id
        if not valid_id(sample_id):
            raise StoreError(f"invalid sample id: {sample_id!r}")
        return self.samples_dir / f"{sample_id}.yaml"

    def _read_path(self, path: Path) -> Sample:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise StoreError(f"invalid YAML in {path}: {exc}") from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise StoreError(f"cannot read {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise StoreError(f"sample file must contain an object: {path}")
        try:
            sample = Sample.from_dict(raw)
        except ValueError as exc:
            raise StoreError(f"invalid sample in {path}: {exc}") from exc
        return sample

    def core_path_for(self, id: str) -> Path:
        sample_id = id
        if not valid_id(sample_id):
            raise StoreError(f"invalid sample id: {sample_id!r}")
        return self.core_dir / f"{sample_id}.yaml"

    def _load_at(self, path: Path, sample_id: str) -> Optional[Sample]:
        if not path.exists():
            return None
        sample = self._read_path(path)
        if sample.id != sample_id:
            raise StoreError(
                f"sample id mismatch: file {path.name} contains id {sample.id!r}"
            )
        return sample

    def load(self, id: str) -> Optional[Sample]:
        sample_id = id
        return (self._load_at(self.path_for(sample_id), sample_id)
                or self._load_at(self.core_path_for(sample_id), sample_id))

    def require(self, id: str) -> Sample:
        sample = self.load(id)
        if sample is None:
            raise StoreError(f"no such sample: {id}")
        return sample

    def read_all(self, strict: bool = True) -> List[Sample]:
        local = ([self._read_path(path)
                  for path in sorted(self.samples_dir.glob("*.yaml"))]
                 if self.samples_dir.exists() else [])
        core = ([self._read_path(path)
                 for path in sorted(self.core_dir.glob("*.yaml"))]
                if self.core_dir.exists() else [])
        out = []
        seen = set()
        for sample in local + core:
            if sample.id in seen and strict:
                raise StoreError(
                    f"duplicate sample id across local and eval/core: {sample.id}"
                )
            seen.add(sample.id)
            out.append(sample)
        return sorted(out, key=lambda item: item.id)

    def list(
        self,
        status: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> List[Sample]:
        if status is not None and status not in STATUSES:
            raise StoreError(f"unknown status {status!r}; expected one of {list(STATUSES)}")
        if origin is not None and origin not in ORIGINS:
            raise StoreError(f"unknown origin {origin!r}; expected one of {list(ORIGINS)}")
        return [
            sample for sample in self.read_all()
            if (status is None or sample.status == status)
            and (origin is None or sample.origin == origin)
        ]

    def find_by_source(self, source: str, exclude_id: Optional[str] = None) -> List[Sample]:
        group = source_group({"source": source, "id": exclude_id or ""})
        return [
            sample for sample in self.read_all()
            if sample.id != exclude_id and source_group(sample) == group
        ]

    # ---------------------------------------------------------------- 写入
    def _write(self, sample: Sample) -> Path:
        sample.validate()
        if not self.path_for(sample.id).exists() and self.core_path_for(sample.id).exists():
            raise StoreError(
                f"{sample.id} is a tracked eval/core sample; edit it via PR, not the local store"
            )
        path = self.path_for(sample.id)
        text = yaml.safe_dump(
            sample.to_dict(),
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        if not text.endswith("\n"):
            text += "\n"
        _atomic_write(path, text)
        return path

    def _record_change(
        self,
        sample: Sample,
        old: str,
        new: str,
        reason: str,
        actor: str,
        from_origin: Optional[str] = None,
        to_origin: Optional[str] = None,
        from_purpose: Optional[str] = None,
        to_purpose: Optional[str] = None,
    ) -> None:
        stamp = now_iso()
        entry: Dict[str, Any] = {
            "from": old,
            "to": new,
            "reason": reason,
            "actor": actor,
            "at": stamp,
        }
        if from_origin is not None or to_origin is not None:
            entry["from_origin"] = from_origin
            entry["to_origin"] = to_origin
        if from_purpose is not None or to_purpose is not None:
            entry["from_purpose"] = from_purpose
            entry["to_purpose"] = to_purpose
        sample.history.append(entry)
        sample.updated_at = stamp

    # ---------------------------------------------------------------- 生命周期
    def new(
        self,
        id: str,
        object_type: str,
        source: str,
        origin: str = "field",
        purpose: str = "evaluation",
        expected: Optional[Dict[str, Any]] = None,
        rubric: Optional[Dict[str, Any]] = None,
        input: Optional[Dict[str, Any]] = None,
        expected_kind: Optional[str] = None,
        proposed: Optional[Dict[str, Any]] = None,
        provenance: Optional[Dict[str, Any]] = None,
        non_diagnostic: bool = False,
        notes: Optional[str] = None,
    ) -> Sample:
        """创建候选样本。候选可以先缺答案，但 ``sample check`` 会拦下。"""
        sample_id = id
        if not valid_id(sample_id):
            raise StoreError(f"invalid sample id: {sample_id!r}")
        if object_type not in OBJECT_TYPES:
            raise StoreError(
                f"unknown object_type {object_type!r}; expected one of {list(OBJECT_TYPES)}"
            )
        if origin not in ORIGINS:
            raise StoreError(f"unknown origin {origin!r}; expected one of {list(ORIGINS)}")
        if origin != "field":
            raise StoreError("candidate must start from origin=field")
        if purpose not in PURPOSES:
            raise StoreError(f"unknown purpose {purpose!r}; expected one of {list(PURPOSES)}")
        path = self.path_for(sample_id)
        if path.exists() or self.load(sample_id) is not None:
            raise StoreError(f"duplicate sample id: {sample_id}")
        if source and self.find_by_source(source, exclude_id=sample_id):
            existing = self.find_by_source(source, exclude_id=sample_id)[0]
            raise StoreError(f"duplicate source used by sample {existing.id}: {source}")

        stamp = now_iso()
        if expected_kind is None:
            expected_kind = "rubric" if rubric and not expected else "resolution"
        sample = Sample(
            id=sample_id,
            status="candidate",
            object_type=object_type,
            origin=origin,
            purpose=purpose,
            source=source,
            input=dict(input or {}),
            expected=expected,
            expected_kind=expected_kind,
            rubric=rubric,
            proposed=proposed,
            provenance=dict(provenance) if provenance is not None else None,
            non_diagnostic=non_diagnostic,
            created_at=stamp,
            updated_at=stamp,
            notes=notes,
        )
        sample.validate()
        self._write(sample)
        return sample

    def admission_errors(self, sample: Sample) -> List[str]:
        return self._admission_errors(sample)

    def _admission_errors(self, sample: Sample) -> List[str]:
        """准入校验的唯一实现：schema、来源、答案、用途与查重。"""
        errors = sample.errors(require_answer=True)
        if sample.status == "candidate" and sample.origin != "field":
            errors.append("candidate must start from origin=field")
        test_ready = sample.status == "active" and sample.origin == "core"
        if sample.purpose == "test" and sample.status != "retired" and not test_ready:
            errors.append("purpose=test only from active/core-evaluation")
        if sample.purpose == "feedback" and sample.origin == "core":
            errors.append("purpose=feedback must stay in origin=field")
        if (sample.object_type == "diagnosis"
                and sample.purpose in ("evaluation", "test")):
            provenance = sample.provenance or {}
            if provenance.get("sanitized") is False or (
                    provenance.get("sanitized") is None
                    and source_needs_provenance(sample.source)):
                errors.append("purpose=evaluation/test requires sanitized provenance")
        if sample.non_diagnostic and sample.purpose in ("evaluation", "test"):
            errors.append("non_diagnostic sample cannot enter evaluation/test")
        if sample.object_type in OBJECT_TYPES:
            spec = OBJECT_TYPES[sample.object_type]
            if sample.purpose not in spec.allowed_purposes:
                errors.append(
                    f"purpose={sample.purpose} not allowed for object_type={sample.object_type}; "
                    f"allowed: {list(spec.allowed_purposes)}"
                )
        others = self.read_all(strict=False)
        for other in others:
            if other.id != sample.id and source_group(other) == source_group(sample):
                errors.append(f"duplicate source also used by sample {other.id}")
                break
        if sum(1 for other in others if other.id == sample.id) > 1:
            errors.append(f"duplicate sample id: {sample.id}")
        return errors

    def check(self, id: str) -> List[str]:
        """复核清单的机械部分；返回全部错误（空列表表示通过）。"""
        sample = self.load(id)
        if sample is None:
            return [f"no such sample: {id}"]
        return self._admission_errors(sample)

    def review(
        self,
        id: str,
        approve: bool,
        actor: str = "maintainer",
        reason: str = "",
    ) -> Sample:
        """维护者复核：通过 → active/field；拒绝 → rejected（终态）。"""
        sample = self.require(id)
        target = "active" if approve else "rejected"
        if approve:
            errors = self._admission_errors(sample)
            if errors:
                raise StoreError("review rejected: " + "; ".join(errors))
        try:
            assert_transition(sample.status, target)
        except ValueError as exc:
            raise StoreError(str(exc)) from exc
        old = sample.status
        sample.status = target
        if approve:
            sample.origin = "field"
        self._record_change(
            sample, old, target,
            reason or ("approved by maintainer" if approve else "rejected by maintainer"),
            actor,
        )
        self._write(sample)
        return sample

    def promote(self, id: str, to: str = "core", actor: str = "maintainer",
                reason: str = "") -> Sample:
        """active + origin=field → active + origin=core；status 不变。"""
        if to != "core":
            raise StoreError(f"promote target must be 'core', got {to!r}")
        sample = self.require(id)
        if sample.status != "active":
            raise StoreError(
                f"invalid transition: {sample.status} -> core origin; only active can be promoted"
            )
        old_origin = sample.origin
        try:
            assert_origin_transition(sample.origin, "core")
        except ValueError as exc:
            raise StoreError(str(exc)) from exc
        if sample.purpose == "test":
            raise StoreError(
                "promote rejected: purpose=test is derived from active/core evaluation, "
                "not promoted from a candidate"
            )
        if (sample.provenance or {}).get("sanitized") is False:
            raise StoreError(
                "promote rejected: provenance.sanitized is false; redact before core"
            )
        prospective = replace(sample, origin="core")
        errors = self._admission_errors(prospective)
        if errors:
            raise StoreError("promote rejected: " + "; ".join(errors))
        sample.origin = "core"
        self._record_change(
            sample, "active", "active",
            reason or "promoted to core origin", actor,
            from_origin=old_origin, to_origin="core",
        )
        self._write(sample)
        return sample

    def set_answer(
        self,
        id: str,
        expected: Optional[Dict[str, Any]] = None,
        rubric: Optional[Dict[str, Any]] = None,
        expected_kind: Optional[str] = None,
        provenance: Optional[Dict[str, Any]] = None,
        actor: str = "maintainer",
        reason: str = "",
    ) -> Sample:
        """给 candidate/active 补答案；``provenance`` 只做局部合并。"""
        sample = self.require(id)
        if sample.status not in ("candidate", "active"):
            raise StoreError(
                f"answer can only be set on candidate/active; {id} is {sample.status}"
            )
        if expected is None and rubric is None:
            raise StoreError("expected or rubric is required")
        if expected_kind is None:
            if rubric is not None and expected is None:
                expected_kind = "rubric"
            elif expected is not None and rubric is None:
                expected_kind = "resolution"
            else:
                expected_kind = sample.expected_kind
        merged_provenance = dict(sample.provenance or {})
        if provenance:
            merged_provenance.update(provenance)
        if merged_provenance:
            merged_provenance.setdefault("trigger", "manual_case")
            merged_provenance.setdefault("sanitized", False)
            merged_provenance.setdefault("redactions", [])
            merged_provenance.setdefault("confidence", "agent-reviewed")
            merged_provenance.setdefault("extraction", "manual")
        prospective = replace(
            sample,
            expected=dict(expected) if expected is not None else None,
            rubric=dict(rubric) if rubric is not None else None,
            expected_kind=expected_kind,
            provenance=merged_provenance or None,
        )
        errors = self._admission_errors(prospective)
        if errors:
            raise StoreError("set-answer rejected: " + "; ".join(errors))
        sample.expected = prospective.expected
        sample.rubric = prospective.rubric
        sample.expected_kind = prospective.expected_kind
        sample.provenance = prospective.provenance
        self._record_change(
            sample, sample.status, sample.status,
            reason or "answer set by maintainer", actor,
        )
        self._write(sample)
        return sample

    def set_purpose(
        self,
        id: str,
        purpose: str,
        actor: str = "maintainer",
        reason: str = "",
    ) -> Sample:
        """改 active 样本的 purpose；走 purpose 白名单与准入校验。"""
        if purpose not in PURPOSES:
            raise StoreError(f"unknown purpose {purpose!r}; expected one of {list(PURPOSES)}")
        sample = self.require(id)
        if sample.purpose == purpose:
            return sample
        if sample.status != "active":
            raise StoreError(
                f"only active samples can change purpose; {id} is {sample.status}"
            )
        try:
            assert_purpose_transition(sample.purpose, purpose)
        except ValueError as exc:
            raise StoreError(str(exc)) from exc
        if purpose == "test" and sample.origin != "core":
            raise StoreError("purpose=test requires active + origin=core")
        if purpose == "feedback" and sample.origin != "field":
            raise StoreError("purpose=feedback requires origin=field")
        prospective = replace(sample, purpose=purpose)
        errors = self._admission_errors(prospective)
        if errors:
            raise StoreError("set-purpose rejected: " + "; ".join(errors))
        old = sample.purpose
        sample.purpose = purpose
        self._record_change(
            sample, "active", "active",
            reason or f"purpose changed: {old} -> {purpose}", actor,
            from_purpose=old, to_purpose=purpose,
        )
        self._write(sample)
        return sample

    def absorb(self, id: str, actor: str = "maintainer", reason: str = "") -> Sample:
        """答案进库后的样本刷新：evaluation/feedback → regression；test 退休。"""
        sample = self.require(id)
        if sample.purpose == "regression":
            return sample
        if sample.purpose == "test":
            if sample.status == "retired":
                return sample
            if sample.status != "active":
                raise StoreError(
                    f"test sample can only be invalidated from active; got {sample.status}"
                )
            sample.status = "retired"
            self._record_change(
                sample, "active", "retired",
                reason or "test invalidated: answer entered knowledge base", actor,
                from_purpose="test", to_purpose="test",
            )
            self._write(sample)
            return sample
        if sample.purpose not in ("evaluation", "feedback"):
            raise StoreError(f"cannot absorb purpose={sample.purpose!r}")
        return self.set_purpose(
            id, "regression", actor=actor,
            reason=reason or "absorbed: answer entered knowledge base",
        )

    def draw_test(self, size: int = 4, method: str = "hash",
                  strata: Optional[Dict[str, int]] = None,
                  actor: str = "maintainer", reason: str = "") -> List[Sample]:
        """从 active + origin=core + evaluation 抽 test 并改 purpose。

        ``method`` 由 strategy 的 ``samples.split`` 决定（hash / group），传给
        ``pools.split_test``；本层不复制切分规则。
        """
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise StoreError("size must be a non-negative integer")
        existing = [
            sample for sample in self.read_all()
            if sample.status == "active" and sample.origin == "core"
            and sample.purpose == "test"
        ]
        if len(existing) >= size:
            return sorted(existing, key=lambda sample: sample.id)
        remaining = size - len(existing)
        targets = dict(strata or {})
        if targets:
            seen = {}
            for sample in existing:
                key = stratum_of(sample)
                seen[key] = seen.get(key, 0) + 1
            targets = {
                key: max(0, target - seen.get(key, 0))
                for key, target in targets.items()
            }
            # 已有 test 覆盖了部分层后，配额之和不能超过剩余槽位；超出时按缺口
            # 从大到小截断，避免 draw_test 在“补一层”时整体报错。
            while sum(targets.values()) > remaining:
                key = max(targets, key=lambda item: (targets[item], item))
                targets[key] -= 1
            targets = {key: value for key, value in targets.items() if value}
        selected = split_test(
            self.read_all(), size=remaining, method=method, strata=targets,
        )
        drawn: List[Sample] = []
        for sample in selected:
            drawn.append(self.set_purpose(
                sample.id, "test", actor=actor,
                reason=reason or "drawn for test set",
            ))
        return sorted(existing + drawn, key=lambda sample: sample.id)

    def export_core(self, id: str) -> Path:
        """把本地 active/core 样本写入 tracked eval/core/samples/，并移除本地副本。"""
        sample = self.require(id)
        if sample.status != "active":
            raise StoreError("export-core requires an active sample")
        if sample.origin != "core":
            raise StoreError("export-core requires origin=core (promote first)")
        if sample.purpose not in ("test", "regression"):
            raise StoreError("export-core requires purpose=test or regression")
        self.core_dir.mkdir(parents=True, exist_ok=True)
        path = self.core_path_for(sample.id)
        text = yaml.safe_dump(
            sample.to_dict(), sort_keys=False, allow_unicode=True,
            default_flow_style=False,
        )
        if not text.endswith("\n"):
            text += "\n"
        _atomic_write(path, text)
        local = self.path_for(sample.id)
        if local.exists():
            local.unlink()
        return path

    def retire(self, id: str, actor: str = "maintainer", reason: str = "") -> Sample:
        """active → retired（软退休，可复活）。"""
        sample = self.require(id)
        try:
            assert_transition(sample.status, "retired")
        except ValueError as exc:
            raise StoreError(str(exc)) from exc
        old = sample.status
        sample.status = "retired"
        self._record_change(sample, old, "retired", reason or "retired", actor)
        self._write(sample)
        return sample

    def revive(self, id: str, actor: str = "maintainer", reason: str = "") -> Sample:
        """retired/field → candidate，重新走复核；core origin 不降级回 field。"""
        sample = self.require(id)
        try:
            assert_transition(sample.status, "candidate")
        except ValueError as exc:
            raise StoreError(str(exc)) from exc
        if sample.origin == "core":
            raise StoreError(
                "retired/core sample cannot revive to candidate/field; create a new candidate"
            )
        old = sample.status
        sample.status = "candidate"
        self._record_change(sample, old, "candidate", reason or "revived for review", actor)
        self._write(sample)
        return sample

    # ---------------------------------------------------------------- 读数
    def counts(self) -> Dict[str, Dict[str, int]]:
        samples = self.read_all()
        return {
            "status": dict(Counter(sample.status for sample in samples)),
            "origin": dict(Counter(sample.origin for sample in samples)),
            "purpose": dict(Counter(sample.purpose for sample in samples)),
            "total": len(samples),
        }


def can_transition(status: str, new_status: str) -> bool:
    """对外暴露状态机检查，避免调用方各自判断。"""
    return check_transition(status, new_status)


def import_pilot(store: "SampleStore", tasks_path: Path) -> Dict[str, List[str]]:
    """把一次 pilot 的 samples 注册进样本队列；已存在的跳过，不改状态。"""
    import json

    tasks = json.loads(Path(tasks_path).read_text(encoding="utf-8"))
    created: List[str] = []
    skipped: List[str] = []
    for entry in tasks.get("samples") or []:
        sid = str(entry.get("short_id") or entry.get("id"))
        if store.load(sid) is not None:
            skipped.append(sid)
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            raise StoreError(f"pilot sample {sid!r} has no path")
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise StoreError(f"invalid sample file: {entry['path']}")
        store.new(
            id=sid,
            object_type="diagnosis",
            source=str(data.get("source") or entry.get("id")),
            origin="field",
            purpose="evaluation",
            input=data.get("input") or {},
            expected=data.get("expected"),
            expected_kind=data.get("expected_kind") or "resolution",
            provenance={"trigger": "issue_import", "sanitized": True,
                        "redactions": [], "confidence": "issue-verified",
                        "extraction": "auto"},
            notes=f"imported from pilot {tasks.get('candidate_id', '')}".strip(),
        )
        created.append(sid)
    return {"created": created, "skipped": skipped}
