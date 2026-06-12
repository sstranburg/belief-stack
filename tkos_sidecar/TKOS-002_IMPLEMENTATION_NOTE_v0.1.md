# TKOS-002 Read-Path Slice — Implementation Note v0.1

**Status:** Implemented and acceptance-tested.
**Date:** 2026-06-02
**Spec:** [`TKOS-002_IMPLEMENTATION_SLICE_v0.1.md`](TKOS-002_IMPLEMENTATION_SLICE_v0.1.md)
**Code:** [`tkos.py`](tkos.py) · [`test_tkos.py`](test_tkos.py)

---

## What was built

One Python module, stdlib only. ~430 lines including the rendering helpers.

| File | Purpose |
|------|---------|
| `tkos.py` | SQLite DDL + demo fixture + state reconstruction + overlay ranking + CLI |
| `test_tkos.py` | Six acceptance tests, plain-assertion runner |

**Two CLI commands:**

- `tkos state <session_id> --turn T [--include-retired] [--json]` — human-facing tabular state view at any past turn.
- `tkos overlay <session_id> --turn T --budget N [--K K] [--json]` — AI-facing compact, ranked, budgeted overlay over the same store.

---

## What the slice proves

**Belief state can be reconstructed from an event trail, at an arbitrary turn, without relying on a frozen snapshot.**

That is the substrate. Every downstream surface depends on it.

Concretely, both CLI commands route through one function — `reconstruct_state(conn, session_id, turn)` — which replays `belief_events` ordered by `at_turn` to derive the active belief set as-of that turn. No materialized snapshot table exists. The `active_beliefs` view in the DDL is deliberately not used on the `--turn T` code path; this is checked by Test C.

**The dual-consumer claim is demonstrated at the fixture level.** Same SQLite store, same audit-trail replay, two different rendered surfaces — a tabular human-debug view and a compact AI-grounding overlay. There is no second source of truth.

---

## Acceptance test results (all six pass)

| # | Test | Result |
|---|------|--------|
| A | At turn 8 (pre-validation), `validation_pending` + `action_blocked` + `fix_attempted` + `pipeline_failed` all active | ✅ pass |
| B | At turn 10 (post-validation), `validation_pending` retired, `validation_complete` active; ≥5 retired beliefs in counts | ✅ pass |
| C | No snapshot tables in schema; `--turn T` reconstruction is self-contained against `belief_events` | ✅ pass |
| D | At turn 8 with budget=1000, overlay admits all four blockers, fits budget (105/1000 tokens used) | ✅ pass |
| E | At turn 10 with budget=1000, overlay admits `validation_complete` + `fix_attempted`, excludes retired `validation_pending`, fits budget (61/1000) | ✅ pass |
| F | At turn 8 with budget=50 (tight), 1 belief admitted (active blocker), 3 omitted, no partial lines, cap honored to the token (41/50) | ✅ pass |

Test F caught a real budget-accounting bug during development — the first implementation used a fixed header reserve of 20 tokens while the actual header is ~22, so the cap was being silently violated. Fixed by computing the header reserve from a worst-case placeholder render.

---

## What changed in the design while building

- **Header reserve must be computed, not guessed.** The placeholder-header approach (compute the max possible header at this K and budget, reserve those tokens up front) holds the cap honestly even at tight budgets. Hard-coded reserves caused Test F to fail.
- **Omitted-summary line is gated on fit.** Per OB-002 §3.1 tier 6, the omitted-counts summary is added *only if* the resulting overlay still fits under the budget. At tight budgets the summary is dropped; the count is still visible in the header.
- **The OB-002 §3.0 out-of-window meta-rule structurally fires but is a no-op in this fixture.** The demo session is only 12 turns long; with K=20 nothing is ever out-of-window. The ranking code computes the meta-rule correctly so it activates as soon as the substrate sees a real long session, but the fixture cannot exercise it. This was expected and is documented in the slice spec.

---

## What's next

In priority order, against the **same** substrate (no schema changes required):

1. **`tkos timeline <session_id>`** — chronological `belief_events` stream with filters. Answers TKOS-002 §5 questions Q2 ("what changed since turn T-1"), Q4 ("which belief caused `action_blocked`"), Q7 ("show all `validation_pending` beliefs, retired included").
2. **`tkos explain <belief_id>`** — single-belief drill-down. Answers Q3, Q5, Q8.
3. **Write path** — replace the hand-written fixture with a deterministic rule engine over a synthetic event stream, then a real adapter (Claude Code logs first per TKOS-001 §10 Q1).
4. **Optional local HTML trace viewer** — only if it fits in a half-day per TKOS-002 §6.5.

None of these is an architectural blocker. The dual-consumer substrate now exists.

---

## Anti-claims (what this note does *not* assert)

- This is not a runtime. It is read-only, against a single hand-written session, with no event ingestion.
- This is not a production sidecar. There is no `observe()` call, no rule engine, no `risk()` action checks.
- The OB-002 v0.2 ranking policy is implemented faithfully but is **not** itself measured here. The slice does not run paired-question generation, does not score deterministic metrics, and does not constitute new empirical evidence beyond the v0.1 result.

The slice's job was to prove the substrate. It did. Subsequent measurement work belongs in P3 (the v0.2 run) and beyond.

---

*End of implementation note.*
