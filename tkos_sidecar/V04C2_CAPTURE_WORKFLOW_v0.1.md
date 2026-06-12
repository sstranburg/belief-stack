# v0.4c2 Substrate Capture Workflow — v0.1

**Date:** 2026-06-08
**Status:** Capture-ready. The TKOS write-path sidecar can ingest, verify, and export Codex rollouts as v0.4c2-grade substrate artifacts.
**Predecessors:**
- `TKOS_WRITE_PATH_SCOPE_v0.3.3.md` (the locked sidecar scope)
- `belief_stack_v0_4c2/V04C2_SUBSTRATE_ADMISSION_CRITERIA.md` (the admission rules this workflow must satisfy)
- `project_v04c2_substrate_separation.md` (the discipline that gates which sessions are admissible)

This document is the operational handbook for capturing the v0.4c2 substrate from a fresh Codex project.

---

## §0 Critical reminder before you start

Per the locked admission criteria (§4 hard rule):

> **If traces are not captured from the first session, the project remains useful software but is NOT admissible as the v0.4c2 substrate.**

The TKOS sidecar exists. Its trace capture mechanism is verified working (956 lines from a real Codex rollout, 17 turns, all five completeness checks passing, byte-deterministic export).

But the sidecar's OWN traces — from the sidecar build sessions Codex ran on Sue's machine 2026-06-05 through 2026-06-08 — are **NOT** v0.4c2 substrate. Those sessions started before this workflow doc existed. They were valuable for testing the capture mechanism; they cannot serve as admissible v0.4c2 data.

The v0.4c2 substrate begins at **session 1 of a new Codex project**. Everything before that is pre-substrate work.

---

## §1 One-time setup

Already done as of 2026-06-08:

- TKOS write-path sidecar implemented and tested (76 tests passing, includes capture/verify/export).
- Taxonomy covers all line types observed in real Codex rollouts to date.
- CLI bindings: `tkos capture`, `tkos verify`, `tkos export` available in `tkos_sidecar/tkos.py`.
- Test rollout (956 lines) verified: capture → verify (5/5 pass) → export (byte-deterministic).

You do not need to rebuild anything. The sidecar is capture-ready.

---

## §2 Starting the v0.4c2 substrate project

Per `project_v04c2_substrate_separation.md` (Option A, locked) and `project_v04c2_substrate_plan.md`:

1. Open Codex IDE (the assistant-native environment Sue's been using).
2. Start a **completely new Codex project** for whatever software work Sue chooses (e.g., a small Belief Stack SDK, a runtime sidecar extension, a CLI utility, a paper-site refresh — see substrate plan §5 for the Belief-Stack-SDK recommendation and trade-offs).
3. From session 1, just work normally. Codex will write its rollout JSONL to `~/.codex/sessions/YYYY/MM/DD/rollout-{timestamp}-{uuid}.jsonl` automatically.

The sidecar does NOT need to be running live during the session. The rollout file is the source of truth; capture runs against the closed file post-session.

---

## §3 Capturing a session

After a Codex session is closed (the project is paused, the rollout file is no longer being written to):

```bash
cd /Users/sue/Documents/git/storm
venv/bin/python tkos_sidecar/tkos.py --db tkos_v04c2.db capture \
    /Users/sue/.codex/sessions/YYYY/MM/DD/rollout-XXXXXXXX.jsonl
```

Output:
```
session_id: <uuid-from-session_meta>
rollout:    /Users/sue/.codex/sessions/...
lines:      <N>
categories: {'mapped': X, 'ignored-known': Y, 'unrecognized': 0, 'idempotent_replay': 0}
finalized:  True
```

Use a **dedicated DB file for v0.4c2** (e.g., `tkos_v04c2.db`) — keep it separate from the test/development DBs that captured pre-substrate sessions. This makes the v0.4c2 substrate's data lineage clean.

If `unrecognized` is > 0 in the output, the rollout contains line types the taxonomy doesn't know. STOP and surface — do not silently proceed. The fix is a taxonomy extension; the audit cycle handles this.

---

## §4 Verifying a captured session

```bash
venv/bin/python tkos_sidecar/tkos.py --db tkos_v04c2.db verify <session_id>
```

Output (the five §6.2 checks):
```
session_id: <uuid>
verdict:    PASS | FAIL
  ✓/✗ line_count: ...
  ✓/✗ no_unrecognized: ...
  ✓/✗ sequence_validation: ...
  ✓/✗ hash_verification: ...
  ✓/✗ no_rule_failures: ...
```

A session is v0.4c2-admissible only if `verdict: PASS`. Any check failing means the session has a capture defect that must be diagnosed before the session can be used as substrate.

---

## §5 Exporting a substrate artifact

```bash
venv/bin/python tkos_sidecar/tkos.py --db tkos_v04c2.db export <session_id> \
    --out substrate/v04c2_<session_id>.jsonl
```

The export is one JSONL line per mapped event, sorted by `(turn_idx, event_idx, source_line_number)`, with the active_beliefs snapshot per event. Byte-deterministic — re-exporting the same DB state produces an identical file.

This is the artifact the v0.4c2 backtest (eventually) consumes.

---

## §6 Workflow summary (one session at a time)

```
[Codex IDE]
   Start fresh project. Work normally. Rollout JSONL accumulates.
        │
        │ session closes
        ▼
[shell]  tkos.py capture <rollout.jsonl>
        │
        │ verify capture is complete
        ▼
[shell]  tkos.py verify <session_id>
        │
        │ PASS → export the substrate artifact
        ▼
[shell]  tkos.py export <session_id> --out substrate/...jsonl
        │
        │ artifact committed to substrate library
        ▼
   ready for v0.4c2 backtest
```

Iterate per session. Accumulate substrate over the duration of the v0.4c2 project. When the substrate is large enough (per the v0.4c2 admission criteria §3 minimum thresholds — ≥30 sessions / ≥3K turns / ≥40 paired questions / ≥4 of 5 categories), the v0.4c2 backtest can begin.

---

## §7 What to do if `unrecognized > 0`

The 2026-06-08 capture test surfaced 5 new Codex line types not in the original v0.3.3 taxonomy:

| Codex type | Decision | Reason |
|---|---|---|
| `response_item:custom_tool_call` | Map to `tool_call` | Same shape as `function_call`, different envelope name |
| `response_item:custom_tool_call_output` | Map to `tool_result` | Same shape as `function_call_output` |
| `event_msg:patch_apply_end` | Ignored-known | Redundant with `function_call_output` for `apply_patch` |
| `top_type:compacted` | Ignored-known | Codex internal context-compaction marker |
| `event_msg:context_compacted` | Ignored-known | Codex internal context-management notification |

These are extensions to the locked v0.3.3 taxonomy committed in this same workflow-doc commit. If future captures surface more unrecognized types, follow the same pattern:

1. Inspect the line: what's the type, what does the payload look like, is it a substrate event or Codex metadata?
2. Decide: MAPPED (becomes an event for the rule engine) or IGNORED-KNOWN (counts toward capture completeness but doesn't become an event)
3. Add to `tkos_sidecar/ingest.py` taxonomy constants
4. Re-run capture + verify on the affected session
5. Commit the taxonomy extension as a small audit-response amendment

Do NOT silently ignore unrecognized lines or invent rule mappings. The discipline is: surface, classify, extend the taxonomy, re-verify.

---

## §8 What this workflow does NOT cover

- **Live-mode ingestion** (streaming the rollout as Codex writes it). Batch post-session ingestion is sufficient for v0.4c2 substrate purposes. Live mode is v0.4+ work.
- **Multi-session aggregation queries.** The v0.4c2 backtest would query the substrate per session; cross-session analysis is downstream work.
- **The v0.4c2 backtest itself.** See `belief_stack_v0_4c2/V04C2_SUBSTRATE_ADMISSION_CRITERIA.md` for admission rules; the actual backtest implementation is future work.

---

## §9 What this workflow guarantees

When a session passes all five §6.2 checks:

- Every raw line of the rollout JSONL was persisted to `raw_lines` (line-count check)
- No unknown line types contaminated the capture (no-unrecognized check)
- Mapped events form contiguous per-turn sequences (sequence-validation check)
- The source file hash + per-line hash chain prove no mutation, drop, or reorder (hash check)
- No rule exceptions occurred during ingestion (no-rule-failures check)

Plus the export is byte-deterministic by construction (stable sort key, no wallclock fields), so the substrate artifact is reproducible.

The session is then v0.4c2-admissible at the technical level. Whether it's admissible at the *protocol* level (captured from session 1 of a fresh project, no pre-substrate contamination) is a workflow discipline, not a sidecar check.

---

*Capture-ready. Software-only sidecar build is complete; v0.4c2 substrate work starts next, in a separate fresh Codex project that begins after this commit lands.*
