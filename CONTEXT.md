# Ascend Sleuth

昇腾训练/推理问题的诊断知识体系。把问题定位从个人经验沉淀为结构化、可检索、可演化的团队知识资产。

## Language

**Case**:
A structured diagnosis rule stored in `knowledge/<namespace>/` (Tier 2). Machine-actionable: symptoms, quickly_check patterns, diagnosis verification steps, root cause, and fix. Distilled from one or more postmortems by the groom process.
_Avoid_: Rule, entry, record

**Postmortem**:
A raw (or lightly structured) investigation record stored in `postmortems/` (Tier 3). The narrative of what happened, what was tried, what the root cause turned out to be. The source material from which cases are extracted. A postmortem may be a full write-up or a pointer to an external investigation doc.
_Avoid_: Incident report, RCA document, case

**Case ID**:
A stable identifier shared by a case and its source postmortem (e.g., `SGL-PD-HEAP-001`). The ID is assigned at postmortem time and persists through promotion to Tier 2.
_Avoid_: Ticket number, issue ID

**Groom**:
The weekly maintenance process (`/skill:knowledge-groom`) that promotes postmortems to cases, validates references, deduplicates, recalculates confidence scores, and soft-retires stale cases.
_Avoid_: Curate, maintain, review

**Triage Tree**:
The Tier 1 routing table (`triage-tree.yaml`). Maps symptom patterns to search namespaces and problem categories. Always loaded, ≤ 30 branches.
_Avoid_: Decision tree, routing table

**Namespace**:
A scoped directory under `knowledge/` that groups cases by workload type × framework (e.g., `training/mindspeed-llm/`, `inference/sglang/`). Used as the primary search dimension during diagnosis.
_Avoid_: Category, folder, module

**Category**:
The orthogonal problem-type dimension: `interrupt` (hang/crash/OOM), `precision` (NaN/divergence), or `performance` (throughput/latency). Determines the shape of `quickly_check` and the default deep-investigation tools.
_Avoid_: Type, severity, class

**Dispatch Axes**:
The three orthogonal dimensions that together determine which cases to load: Platform (A2/A3/A5), Workload (training/inference × framework → namespace), and Category (interrupt/precision/performance).
_Avoid_: Routing dimensions

**Confidence Score**:
A time-decayed metric (`hits / (hits + misdiagnoses)`) maintained by groom. Calibration: >0.8 high-confidence (apply directly), 0.5–0.8 medium (prepare plan B), <0.5 low (treat as hint only).
_Avoid_: Priority, weight, rank

**Trace**:
A step-level audit log written to `diagnosis_state-<session_id>.yaml` during each diagnose session. The sole mechanism for misdiagnosis attribution: distinguishes case errors (fix the YAML) from execution errors (fix the skill body).
_Avoid_: Log, transcript, history

**Skill**:
An agent-callable workflow defined by a `SKILL.md` file following the Agent Skills spec. The four skills in this system are diagnose, to-postmortem, knowledge-groom, and resume-diagnosis.
_Avoid_: Command, plugin, tool

**Severity**:
A gate on how a matched fix should be delivered: `benign` (give fix directly), `service-affecting` (give fix but flag side effects like requires-restart), or `data-loss-risk` (halt — do not give fix, preserve state, notify owner).
_Avoid_: Priority, urgency, impact

**Soft Match**:
Version compatibility uses soft matching: a case's `compat` ranges are checked against the customer's environment, but mismatches downgrade confidence rather than hard-excluding the case. This is deliberate — a case validated on A5 may still apply to A3.
_Avoid_: Strict match, exact match
