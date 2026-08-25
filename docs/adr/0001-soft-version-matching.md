# Soft version matching: downgrade confidence, never hard-exclude

Case `compat` ranges (framework/CANN/HDK versions) are checked against the customer's environment, but mismatches only downgrade confidence — they never hard-exclude a case from the candidate set.

**Why:** Ascend platform differences are field-level within cases, not case-level. A case validated on A3+910C often applies to A5+950 with the same root cause. Hard-excluding on version mismatch would cause catastrophic false negatives during cold start when the case base is sparse — if the only relevant case was validated on a slightly different version, it would be invisible. Cases with known platform-specific behavior already encode that explicitly in per-platform `diagnosis` branches; soft matching handles the rest.

**Rejected alternative:** Hard version gating. Simpler to reason about but would require exact version coverage for every case before it becomes discoverable — impractical given the combinatorial explosion of Ascend platform × framework × CANN × HDK versions and the cold-start reality.
