# -*- coding: utf-8 -*-
"""SkillOpt 快更新搜索循环：批次内成功/失败分组反思 + 全量 dev 严格采纳。

只实现快更新。慢更新（跨 epoch 写入保护区）与 meta-skill 是循环内部的可选阶段，
等审计集样本量与对照结论到位后再加；框架层不为它开特例。

循环单位是批次与 epoch，不是单样本：一批先用当前快照跑完，按
``success_threshold`` 分成成功/失败两组，逐组反思，再合并成一次编辑；候选在
全量 dev 上严格高于现任才采纳，平局与更低都保留现任。最近被拒的补丁进入后续
反思提示，作为运行内记忆。
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from .budget import Budget
from .contract import LoopError, Snapshot
from .decisions import DecisionLog

SKILLOPT_STATE_SCHEMA = "skillopt-fast-v1"


def _mean(scores: Dict[str, float]) -> Optional[float]:
    if not scores:
        return None
    return round(sum(scores.values()) / len(scores), 9)


class SkillOptLoop:
    id = "skillopt"
    version = "v1"

    def __init__(self, seed_skill: str, train_samples: List[str],
                 dev_samples: List[str], *,
                 epochs: int = 3, batch_size: int = 4,
                 reflection_minibatch: int = 2,
                 success_threshold: float = 0.0,
                 rejected_memory: int = 5,
                 max_steps: Optional[int] = None,
                 seed: int = 0,
                 target: str = "", component: str = "",
                 budget: Optional[Budget] = None,
                 decision_log: Optional[DecisionLog] = None,
                 run_id: str = ""):
        if not isinstance(seed_skill, str) or not seed_skill.strip():
            raise LoopError("seed_skill is required")
        for name, values in (("train_samples", train_samples), ("dev_samples", dev_samples)):
            if not values or not all(isinstance(item, str) and item.strip() for item in values):
                raise LoopError(f"{name} must be non-empty strings")
            if len(set(values)) != len(values):
                raise LoopError(f"{name} must not contain duplicates")
        if not isinstance(epochs, int) or isinstance(epochs, bool) or epochs < 1:
            raise LoopError("epochs must be a positive integer")
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
            raise LoopError("batch_size must be a positive integer")
        if not isinstance(reflection_minibatch, int) or isinstance(reflection_minibatch, bool) \
                or reflection_minibatch < 1:
            raise LoopError("reflection_minibatch must be a positive integer")
        if not 0 <= float(success_threshold) <= 1:
            raise LoopError("success_threshold must be between 0 and 1")
        if not isinstance(rejected_memory, int) or isinstance(rejected_memory, bool) \
                or rejected_memory < 0:
            raise LoopError("rejected_memory must be a non-negative integer")
        if max_steps is not None and (
            not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1
        ):
            raise LoopError("max_steps must be a positive integer or null")
        if set(train_samples) & set(dev_samples):
            raise LoopError("train and dev samples must be disjoint")
        self.seed_skill = seed_skill
        self.train_samples = list(train_samples)
        self.dev_samples = list(dev_samples)
        self.epochs = epochs
        self.batch_size = batch_size
        self.reflection_minibatch = reflection_minibatch
        self.success_threshold = float(success_threshold)
        self.rejected_memory = rejected_memory
        self.max_steps = max_steps
        self.seed = seed
        self.target = str(target or "")
        self.component = str(component or "")
        self.budget = budget or Budget()
        self.decision_log = decision_log
        self.run_id = str(run_id or "")
        self.incumbent = Snapshot.from_text(
            "seed", seed_skill, target=self.target, component=self.component,
        )
        self.history: List[Snapshot] = [self.incumbent]
        self.rejected: List[str] = []
        self.batch_scores: Dict[str, float] = {}
        self.batch_feedback: Dict[str, str] = {}
        self.candidate: Optional[Snapshot] = None
        self.candidate_dev: Dict[str, float] = {}
        self.pending_groups: List[Dict[str, Any]] = []
        self.proposals: List[str] = []
        self.phase = "seed_dev"
        self.epoch = 1
        self.batches: List[List[str]] = []
        self.batch_index = 0
        self.batches_done = 0
        self.accepted = 0
        self.stop_reason: Optional[str] = None
        self.step = 0

    # -- actions ---------------------------------------------------------
    def next_action(self) -> Dict[str, Any]:
        if self.stop_reason is not None:
            return {"kind": "stop", "reason": self.stop_reason}
        # 预算恰好用尽时，先把已评完 dev 的候选判掉，再停；否则最后一批
        # 的采纳/拒绝会丢。
        if (self.phase == "candidate_dev" and self.candidate is not None
                and len(self.candidate_dev) == len(self.dev_samples)):
            self._decide_candidate()
        if not self.budget.can_spend("target_runs"):
            self.stop_reason = "target_runs_budget"
            return {"kind": "stop", "reason": self.stop_reason}

        while True:
            if self.phase == "seed_dev":
                action = self._dev_action(self.incumbent, self.incumbent.scores, "seed")
                if action is not None:
                    return action
                self._start_epoch(1)
                continue
            if self.phase == "train":
                missing = [sid for sid in self._current_batch() if sid not in self.batch_scores]
                if missing:
                    return {"kind": "evaluate", "candidate_id": self.incumbent.id,
                            "sample_id": missing[0], "phase": "train",
                            "batch": self.batch_index, "skill": self.incumbent.text}
                self._begin_reflection()
                continue
            if self.phase == "reflect":
                if self.pending_groups:
                    if not self.budget.can_spend("worker_calls"):
                        self.stop_reason = "worker_calls_budget"
                        return {"kind": "stop", "reason": self.stop_reason}
                    return self._reflect_action()
                if len(self.proposals) > 1:
                    if not self.budget.can_spend("worker_calls"):
                        self.stop_reason = "worker_calls_budget"
                        return {"kind": "stop", "reason": self.stop_reason}
                    self.phase = "merge"
                    return self._merge_action()
                text = self.proposals[0] if self.proposals else self.incumbent.text
                self._create_candidate(text)
                continue
            if self.phase == "merge":
                return self._merge_action()
            if self.phase == "candidate_dev":
                action = self._dev_action(self.candidate, self.candidate_dev, self.candidate.id)
                if action is not None:
                    return action
                self._decide_candidate()
                continue
            if self.phase == "batch_done":
                if self.max_steps is not None and self.batches_done >= self.max_steps:
                    self.stop_reason = "max_steps"
                    return {"kind": "stop", "reason": self.stop_reason}
                self.batch_index += 1
                if self.batch_index >= len(self.batches):
                    self._start_epoch(self.epoch + 1)
                    if self.stop_reason is not None:
                        return {"kind": "stop", "reason": self.stop_reason}
                    continue
                self._reset_batch()
                self.phase = "train"
                continue
            if self.phase == "done":
                self.stop_reason = "complete"
                return {"kind": "stop", "reason": self.stop_reason}
            raise LoopError(f"unknown phase {self.phase!r}")

    def apply(self, action: Dict[str, Any], result: Dict[str, Any]) -> None:
        if not isinstance(action, dict) or not isinstance(result, dict):
            raise LoopError("action and result must be objects")
        kind = action.get("kind")
        if kind == "evaluate":
            if "score" not in result:
                raise LoopError("evaluate result requires score")
            self._record_score(action, result["score"], str(result.get("feedback") or ""))
        elif kind == "reflect":
            text = result.get("text")
            if not isinstance(text, str) or not text.strip():
                raise LoopError("reflect result requires edited text")
            if not self.pending_groups:
                raise LoopError("no reflect group pending")
            self.pending_groups.pop(0)
            self.proposals.append(text)
            self.budget.spend("worker_calls")
        elif kind == "merge":
            text = result.get("text")
            if not isinstance(text, str) or not text.strip():
                raise LoopError("merge result requires edited text")
            self.budget.spend("worker_calls")
            self._create_candidate(text)
        elif kind == "stop":
            return
        else:
            raise LoopError(f"unsupported action kind {kind!r}")

    # -- evaluation ------------------------------------------------------
    def _record_score(self, action: Dict[str, Any], score: Any,
                      feedback: str) -> None:
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            raise LoopError("score must be a number")
        if not 0 <= float(score) <= 1:
            raise LoopError("score must be between 0 and 1")
        if not self.budget.can_spend("target_runs"):
            raise LoopError("target_runs budget exhausted")
        sample_id = str(action.get("sample_id") or "")
        phase = action.get("phase")
        if phase == "train":
            if sample_id not in self._current_batch():
                raise LoopError(f"sample {sample_id!r} is not in the current batch")
            if sample_id in self.batch_scores:
                raise LoopError(f"sample {sample_id!r} already evaluated in this batch")
            self.batch_scores[sample_id] = float(score)
            self.batch_feedback[sample_id] = feedback
        elif phase == "dev":
            target = str(action.get("candidate_id") or "")
            scores = self.incumbent.scores if target == self.incumbent.id else self.candidate_dev
            if target != self.incumbent.id and (self.candidate is None or target != self.candidate.id):
                raise LoopError(f"unknown dev candidate {target!r}")
            if sample_id in scores:
                raise LoopError(f"sample {sample_id!r} already evaluated on dev")
            scores[sample_id] = float(score)
        else:
            raise LoopError(f"unknown evaluate phase {phase!r}")
        self.budget.spend("target_runs")
        self.step += 1

    def _dev_action(self, snapshot: Optional[Snapshot], scores: Dict[str, float],
                    candidate_id: str) -> Optional[Dict[str, Any]]:
        if snapshot is None:
            raise LoopError("dev evaluation requires a snapshot")
        missing = [sid for sid in self.dev_samples if sid not in scores]
        if not missing:
            return None
        return {"kind": "evaluate", "candidate_id": candidate_id,
                "sample_id": missing[0], "phase": "dev", "skill": snapshot.text}

    # -- batches / reflection -------------------------------------------
    def _start_epoch(self, epoch: int) -> None:
        if epoch > self.epochs:
            self.phase = "done"
            return
        self.epoch = epoch
        shuffled = list(self.train_samples)
        random.Random(self.seed + epoch).shuffle(shuffled)
        self.batches = [
            shuffled[index:index + self.batch_size]
            for index in range(0, len(shuffled), self.batch_size)
        ]
        self.batch_index = 0
        self._reset_batch()
        self.phase = "train"

    def _reset_batch(self) -> None:
        self.batch_scores = {}
        self.batch_feedback = {}
        self.pending_groups = []
        self.proposals = []
        self.candidate = None
        self.candidate_dev = {}

    def _current_batch(self) -> List[str]:
        if self.batch_index >= len(self.batches):
            return []
        return self.batches[self.batch_index]

    def _begin_reflection(self) -> None:
        items = [
            {"sample_id": sid, "score": self.batch_scores[sid],
             "feedback": self.batch_feedback.get(sid, "")}
            for sid in self._current_batch()
        ]
        failures = [item for item in items if item["score"] <= self.success_threshold]
        successes = [item for item in items if item["score"] > self.success_threshold]
        groups: List[Dict[str, Any]] = []
        for label, pool in (("failure", failures), ("success", successes)):
            for index in range(0, len(pool), self.reflection_minibatch):
                groups.append({"group": label,
                               "items": pool[index:index + self.reflection_minibatch]})
        self.pending_groups = groups
        self.proposals = []
        self.phase = "reflect"

    def _reflect_action(self) -> Dict[str, Any]:
        group = self.pending_groups[0]
        return {
            "kind": "reflect", "candidate_id": self.incumbent.id,
            "skill": self.incumbent.text,
            "group": group["group"], "items": list(group["items"]),
            "rejected": list(self.rejected),
            "epoch": self.epoch, "batch": self.batch_index,
        }

    def _merge_action(self) -> Dict[str, Any]:
        return {"kind": "merge", "candidate_id": self.incumbent.id,
                "skill": self.incumbent.text,
                "proposals": list(self.proposals),
                "rejected": list(self.rejected)}

    def _create_candidate(self, text: str) -> None:
        if not text.strip():
            raise LoopError("candidate text is empty")
        self.pending_groups = []
        self.proposals = []
        self.candidate = Snapshot.from_text(
            f"c{len(self.history)}", text, target=self.target,
            component=self.component, parent=self.incumbent.id,
        )
        self.candidate_dev = {}
        self.phase = "candidate_dev"

    def _decide_candidate(self) -> None:
        if self.candidate is None:
            raise LoopError("no candidate to decide")
        score = _mean(self.candidate_dev)
        baseline = _mean(self.incumbent.scores)
        accepted = score is not None and baseline is not None and score > baseline
        if accepted:
            self.candidate.scores = dict(self.candidate_dev)
            self.incumbent = self.candidate
            self.accepted += 1
            reason = "dev_strict_improvement"
        else:
            self.rejected.append(self.candidate.text)
            if self.rejected_memory == 0:
                self.rejected = []
            elif len(self.rejected) > self.rejected_memory:
                self.rejected = self.rejected[-self.rejected_memory:]
            reason = "dev_not_strictly_better"
        self.history.append(self.candidate)
        self.candidate = None
        self.candidate_dev = {}
        self.batches_done += 1
        if self.decision_log is not None:
            self.decision_log.record(
                self.id, "fast", run=self.run_id, step=self.step,
                candidate=self.history[-1].id, parent=self.history[-1].parent or "",
                score=score, baseline=baseline, accepted=accepted, reason=reason,
            )
        self.phase = "batch_done"

    # -- result ----------------------------------------------------------
    def best_snapshot(self) -> Snapshot:
        return self.incumbent

    def result(self) -> Dict[str, Any]:
        return {
            "loop": self.id,
            "best_id": self.incumbent.id,
            "best_skill": self.incumbent.text,
            "best_score": _mean(self.incumbent.scores),
            "seed_score": _mean(self.history[0].scores),
            "accepted": self.accepted,
            "rejected": len(self.rejected),
            "epochs": self.epochs,
            "epoch": self.epoch,
            "phase": self.phase,
            "batches_done": self.batches_done,
            "calls": self.budget.spent("target_runs"),
            "worker_calls": self.budget.spent("worker_calls"),
            "budget": self.budget.to_dict(),
            "stop_reason": self.stop_reason,
            "dev_samples": list(self.dev_samples),
            "train_samples": list(self.train_samples),
            "target": self.target,
            "component": self.component,
            "history": [{"id": item.id, "parent": item.parent,
                         "score": _mean(item.scores)} for item in self.history],
        }

    # -- persistence -----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_schema": SKILLOPT_STATE_SCHEMA,
            "loop": self.id,
            "seed_skill": self.seed_skill,
            "train_samples": list(self.train_samples),
            "dev_samples": list(self.dev_samples),
            "epochs": self.epochs,
            "batch_size": self.batch_size,
            "reflection_minibatch": self.reflection_minibatch,
            "success_threshold": self.success_threshold,
            "rejected_memory": self.rejected_memory,
            "max_steps": self.max_steps,
            "seed": self.seed,
            "target": self.target,
            "component": self.component,
            "incumbent": self.incumbent.to_dict(),
            "history": [item.to_dict() for item in self.history],
            "rejected": list(self.rejected),
            "batch_scores": dict(self.batch_scores),
            "batch_feedback": dict(self.batch_feedback),
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "candidate_dev": dict(self.candidate_dev),
            "proposals": list(self.proposals),
            "pending_groups": [dict(group) for group in self.pending_groups],
            "phase": self.phase,
            "epoch": self.epoch,
            "batches": [list(batch) for batch in self.batches],
            "batch_index": self.batch_index,
            "batches_done": self.batches_done,
            "accepted": self.accepted,
            "stop_reason": self.stop_reason,
            "step": self.step,
            "budget": self.budget.to_dict(),
            "decision_log": str(self.decision_log.path) if self.decision_log else None,
            "run_id": self.run_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillOptLoop":
        if data.get("state_schema") not in (None, SKILLOPT_STATE_SCHEMA):
            raise LoopError("skillopt state schema mismatch")
        loop = cls(
            seed_skill=str(data.get("seed_skill") or ""),
            train_samples=list(data.get("train_samples") or []),
            dev_samples=list(data.get("dev_samples") or []),
            epochs=int(data.get("epochs") or 3),
            batch_size=int(data.get("batch_size") or 4),
            reflection_minibatch=int(data.get("reflection_minibatch") or 2),
            success_threshold=float(data.get("success_threshold") or 0.0),
            rejected_memory=int(data.get("rejected_memory") or 5),
            max_steps=data.get("max_steps"),
            seed=int(data.get("seed") or 0),
            target=str(data.get("target") or ""),
            component=str(data.get("component") or ""),
            budget=Budget.from_dict(data.get("budget")),
        )
        loop.incumbent = Snapshot.from_dict(data.get("incumbent") or {})
        loop.history = [Snapshot.from_dict(item) for item in data.get("history") or []]
        # 反序列化会为 incumbent 与 history 各建一个对象；同一版本的分数必须
        # 写在同一份上，否则恢复后的 dev 评分只更新 incumbent，历史里仍是空的。
        for index, item in enumerate(loop.history):
            if item.id == loop.incumbent.id:
                loop.history[index] = loop.incumbent
        loop.rejected = list(data.get("rejected") or [])
        loop.batch_scores = {str(k): float(v)
                             for k, v in (data.get("batch_scores") or {}).items()}
        loop.batch_feedback = {str(k): str(v)
                               for k, v in (data.get("batch_feedback") or {}).items()}
        raw_candidate = data.get("candidate")
        loop.candidate = Snapshot.from_dict(raw_candidate) if raw_candidate else None
        loop.candidate_dev = {str(k): float(v)
                              for k, v in (data.get("candidate_dev") or {}).items()}
        loop.proposals = list(data.get("proposals") or [])
        loop.pending_groups = [dict(group) for group in data.get("pending_groups") or []]
        loop.phase = str(data.get("phase") or "seed_dev")
        loop.epoch = int(data.get("epoch") or 1)
        loop.batches = [list(batch) for batch in data.get("batches") or []]
        loop.batch_index = int(data.get("batch_index") or 0)
        loop.batches_done = int(data.get("batches_done") or 0)
        loop.accepted = int(data.get("accepted") or 0)
        loop.stop_reason = data.get("stop_reason")
        loop.step = int(data.get("step") or 0)
        if data.get("decision_log"):
            loop.decision_log = DecisionLog(str(data["decision_log"]))
        loop.run_id = str(data.get("run_id") or "")
        return loop
