# F-023 — TKOS log-replay proof-of-concept

**Phase 1 status:** Complete (2026-05-29).
**Phase 2 status:** Not started — warrant assignment for *cross-turn state-level beliefs* (vs. the per-turn invariant warrants Phase 1 emits) and the intervention catalog.

This directory contains the F-023 log-replay POC infrastructure. It exists to test whether the Belief Stack v0.1 specification, when applied to real Claude session logs, surfaces failure modes (stale priors, missed contradictions, repeated-failure loops, unwarranted interventions) that the assistant itself did not catch at runtime.

The strategic frame, the scope, and the methodology-discipline requirements are documented in the [F-023 backlog card](../BACKLOG.md). This README focuses on what Phase 1 produced and what remains.

---

## What Phase 1 produced

```
data/
├── sessions_normalized.jsonl       — 83,271 turns parsed from 164 JSONL files
├── sessions_inventory.json          — per-session and aggregate corpus stats
├── sessions_classified.jsonl        — every turn + L1 region label + match reason
├── region_distribution.json         — aggregate region distribution
├── reasoning_ledger.jsonl           — full per-turn ledger (label + warrant)
└── reasoning_ledger_summary.json    — ledger summary stats
```

Scripts:
- `parse_sessions.py` — Phase 1 steps 1-3 (inventory, schema inspection, parser)
- `classify_regions.py` — Phase 1 step 4 (L1 region classifier, pre-registered rules)
- `extract_ledger.py` — Phase 1 step 5 (warrant assignment per turn)

---

## Corpus

| Source | Files | Turns | Span |
|---|---:|---:|---|
| 5 main sessions | 5 | 50,587 | 2026-03-16 → 2026-05-29 |
| 159 subagent traces | 159 | 32,684 | (parent-session timeframes) |
| **Total** | **164** | **83,271** | ~10.5 weeks |

Tool-call distribution dominated by Bash (13,282), Edit (6,755), Read (5,602). This is engineering-shaped workload — the substrate for which long-running belief lifecycle, repeated-failure detection, and intervention applicability checks should matter most.

1,309 of 28,946 tool calls (4.5%) failed with explicit `is_error=true`. The error-bearing turns are the highest-yield candidates for Phase 2 intervention checks.

---

## L1 region classifier — pre-registered rules v0.1

The seven typed operational regions named in the F-023 backlog card:

```
data_fetch          ingesting external data
pipeline_run        running multi-step automated workflows
failure_diagnosis   investigating an error or unexpected outcome
validation          verifying correctness of code / data / state
deploy_readiness    preparing for or executing a deploy
report_generation   creating output artifacts (reports, briefs, dashboards)
evidence_sealing    cryptographic timestamping, signing, audit trails
UNCLASSIFIED        conversation that doesn't match any of the above
```

Classification rules — locked at v0.1, in `classify_regions.py`:
- **slash commands**: `/evening`, `/morning` → `pipeline_run`; `/add-actor` → `data_fetch`; `/loop` → UNCLASSIFIED
- **system reminders**: UNCLASSIFIED (framework noise)
- **assistant turns**: Bash command pattern banks per region (`scripts/run_pipeline.py` → `pipeline_run`; `git commit/push` → `deploy_readiness`; `pytest|tsc|--check` → `validation`; etc.). Tool name signals (`WebFetch` → `data_fetch`). Diagnosis-text patterns (`"let me check"`, `"what's the issue"`, `"error/failed/traceback"`) → `failure_diagnosis`.
- **user turns**: deploy intent (`"deploy"`, `"ship it"`) → `deploy_readiness`; correction language (`"no, that's wrong"`, `"let me correct"`) → `failure_diagnosis`; tool_error in result → `failure_diagnosis`.

The rules were written before the distribution was run. They are not to be tuned to the data distribution after running. Any future revision must bump the rules version (v0.2, v0.3 etc.) — silent edits forbidden.

### Resulting distribution

| Region | Count | % |
|---|---:|---:|
| validation | 6,573 | 7.89% |
| failure_diagnosis | 2,542 | 3.05% |
| report_generation | 2,175 | 2.61% |
| pipeline_run | 1,752 | 2.10% |
| deploy_readiness | 1,133 | 1.36% |
| data_fetch | 563 | 0.68% |
| evidence_sealing | 265 | 0.32% |
| **UNCLASSIFIED** | **68,268** | **82.0%** |

The 82% UNCLASSIFIED is a real finding, not a bug. Most turns in long Claude sessions are conversation (assistant explanation, user follow-up questions, thinking, hedges). The 18% that match operational regions are the "action moments" within that conversation. This is what we want — typed regions identify the operational substrate, leaving the rest as honest "regular conversation."

---

## Warrant policy — pre-registered v0.1

All Phase 1 ledger entries emit **invariant warrants** conforming to the [`warrant-v0.1.json`](https://topicspace.ai/schemas/warrant-v0.1.json) schema. Rationale: each turn's claim is structural — the assistant ran a command, the command produced a tool_result, the result either succeeded or failed. Decay over wall-clock time is not the right model for per-turn engineering operations.

**Decaying warrants apply later** (Phase 2/3) to **state-level beliefs carried across turns** — "the pipeline is running," "the user is away," "the deploy is pending." Those DO age and require reconciliation. Per-turn operations are invariant.

Per-turn warrant fields:
- `schema_version`: `warrant-v0.1`
- `warrant_type`: `invariant`
- `birth_timestamp`: turn timestamp
- `support_n`: `max(1, n_tool_uses + n_tool_results)`
- `coverage_status`: `IN_DISTRIBUTION` if classified to a region; `UNCLASSIFIED` otherwise
- `evidence_refs`: `[session:..., uuid:..., tool_use:...]`
- `validation_status`: `PASS` (no tool errors), `FAIL` (≥1 tool error), or `UNKNOWN` (no tools called)

Validation distribution:
- PASS: 27,626 (33.2%)
- FAIL: 1,309 (1.6%)
- UNKNOWN: 54,336 (65.3%)

---

## Methodology discipline (carried forward to Phase 2+)

Per the F-023 backlog card:

1. **Random sample, not failure-cherry-picking.** Phase 1 parsed ALL sessions. Sampling for Phase 2 will use a documented random seed and a stratified-by-session approach.
2. **Pre-registered intervention criteria.** Phase 2's "stale prior triggers intervention" rules must be written before any TKOS-replay numbers are produced. Same discipline as Phase 1's classifier rules.
3. **False positive accounting.** Phase 3's comparison table must report cases where TKOS would have intervened but the actual run was fine. Without this, the writeup looks like "TKOS catches the exact failures we already knew about."
4. **Honest framing.** The comparison is offline detection rate against retrospective ground truth, not measured live impact. TKOS would have *flagged* X; whether it would have *changed* the outcome is hypothesis, not evidence.

---

## What Phase 2 needs

Phase 2 builds on the Phase 1 ledger:

1. **Cross-turn state-level beliefs (decaying warrants)** — track claims that span multiple turns: "the pipeline is running" (born when a pipeline-run turn fires, ages over wall-clock time, retired when a subsequent turn confirms completion or failure). These are the warrants where decay actually matters.
2. **Pre-registered intervention catalog rules** — define what makes a state-level belief "stale enough to suppress an intervention." Lock rules before running.
3. **Intervention applicability checks** — at every assistant action with a stale prior, compute whether TKOS would have suppressed it.
4. **Repeated-failure-loop detection** — sessions where the assistant retried the same broken thing for 5+ turns. The strongest sub-claim per the backlog card.

Phase 3 builds the comparison table (TP / FP / FN / TN). Phase 4 is the writeup.

---

## Reading the ledger

Each line in `data/reasoning_ledger.jsonl` is a single turn:

```json
{
  "session_id": "main::a7ee69be-...",
  "turn_idx": 1234,
  "uuid": "...",
  "timestamp": "2026-05-28T07:13:00Z",
  "role": "assistant",
  "label": {
    "operation_type": "pipeline_run",
    "match_reason":   "bash_pattern=pipeline_run:scripts/run_pipeline.py",
    "rules_version":  "v0.1"
  },
  "warrant": {
    "schema_version":   "warrant-v0.1",
    "warrant_type":     "invariant",
    "birth_timestamp":  "2026-05-28T07:13:00Z",
    "support_n":        2,
    "coverage_status":  "IN_DISTRIBUTION",
    "evidence_refs":    ["session:...", "uuid:...", "tool_use:..."],
    "validation_status":"PASS"
  },
  "tool_uses_count":    1,
  "tool_results_count": 1,
  "has_error":          false,
  "is_meta":            false
}
```

The label and warrant together form the v0.1 representation contract. Every classified turn carries both. UNCLASSIFIED turns carry the label `UNCLASSIFIED` and a warrant with `coverage_status: UNCLASSIFIED` — they are recorded but explicitly outside the substrate the typology covers, per the spec's L1 representation contract.
