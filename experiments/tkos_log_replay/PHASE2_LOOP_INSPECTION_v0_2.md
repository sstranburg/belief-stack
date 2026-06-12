# Phase 2 — Repeated-failure-loop hand-inspection (read-only)

_Conducted: 2026-05-30. Bounded read-only inspection per user direction
("inspect 5–10 candidate windows and determine whether 'repeated
failure loop' is actually present in the substrate and what it looks
like; no new detector, no new rules, no implementation")._

This document records what hand-reading the candidate loop windows
surfaced. It does not change v0.1 or v0.2 measurements; it informs
the framing of v0.3 scope.

---

## 1. Why this inspection happened

The v0.1 `repeated_failure_loop` rule produced 0 SUPPRESS verdicts in
830 applicable cases. v0.2 loosened the signature predicate (Jaccard
≥ 0.5 disjunction + exception-class match) — also produced **0
SUPPRESS verdicts**, and on closer inspection 0 prior-match pairs
across all 830 applicable rows.

The v0.2 case-study report queued a hand-review as the v0.3 gating
step: before further loosening (e.g., to embeddings-based semantic
similarity), determine whether the v0.2 result reflects "loops are
absent" or "loops are present but the detector misses them."

This document answers that question.

---

## 2. Method

A candidate window is a turn position T in a session where the
trailing 10-turn window (including T) contains **≥ 3 turns** that
either:

- have `l1_region == "failure_diagnosis"`, or
- carry any `tool_result.is_error == true`.

This is the v0.1 / v0.2 applicability predicate, applied directly to
the substrate without the signature predicate. It identifies "is this
a stretch of repeated failures?" without judging "are the failures
the same?"

Scan returned **386 candidate windows** across 164 sessions. The top
12 windows (highest failure-density, deduplicated to one window per
session) were extracted via [/tmp/tkos_find_loop_candidates.py](file:///tmp/tkos_find_loop_candidates.py). Six were hand-read by following the
session ledger turn-by-turn (failure-user turn → preceding assistant
turn → following assistant prose).

---

## 3. What the windows actually look like

All six inspected windows are clear loops. They cluster into four
behavioral types.

### Type A — Pure invocation loops

Same script attempted multiple times with cosmetic variations of the
invocation. The assistant doesn't realize the underlying error is the
same; it keeps tweaking how it invokes the script.

Example, session `ed22b861` window `[92..101]`, 5 retries of
`build_backtest_history.py`:

| Turn | Assistant Bash command |
|--:|---|
| 91 | `venv/bin/python scripts/build_backtest_history.py` |
| 93 | `venv/bin/python scripts/build_backtest_history.py` |
| 95 | `/path/to/repo/venv/bin/python /path/to/repo/scripts/build_backtest_history.py` |
| 97 | `source venv/bin/activate && python scripts/build_backtest_history.py` |
| 99 | `source venv/bin/activate && python scripts/build_backtest_history.py` |
| 101 | (assistant prose) *"It seems `build_backtest_history.py` is being blocked by your permission settings. Could you approve it…"* |

The assistant tried five invocations before recognizing it was a
permission-denial loop and asking the user. Every attempt referenced
the same script (`scripts/build_backtest_history.py`) and used Bash;
only the path prefix and shell wrapper varied. Same pattern in
session `c9e3377d` (5 retries of `clean_narrative_lineages.py`).

### Type B — Tool-strategy iteration loops

Same goal, multiple invocation strategies. The assistant cycles
through different ways of accomplishing the same task before either
recognizing the underlying obstacle or succeeding.

Example, session `cc6cc5e1` window `[652..661]`, 5 attempts to load
and analyze `actors.json`:

| Turn | Strategy |
|--:|---|
| 652 | `python3 -c "..."` |
| 654 | `python3 << 'PYEOF'` (heredoc) |
| 656 | `python3 /dev/stdin << 'EOF'` |
| 658 | `node -e "..."` (switched language entirely) |
| 660 | `node -e "..."` |

Shared file path (`actors.json`) across all 5; shared task (load +
sort by NDS); tool family changed (python3 → node). Token-level
overlap is low between the attempts, but the file-path signature is
consistent.

### Type C — Read-tool loops

Repeated `Read` tool calls, often on missing or wrong-path files.

Example, session `961dc71c` window `[2..11]`, 5 `Read` failures
back-to-back. The assistant was trying to read a file that
didn't exist at the location it was guessing; each Read failed with
the same shape of error; assistant tried a slightly different path
each time.

### Type D — Query iteration loops

Iterating on a data-extraction query (typically a chain of `grep`,
`sed`, `head`, `wc`). The assistant is in a refining-the-query loop,
not a failed-action loop — each turn returns *some* output, but the
output doesn't match the assistant's expectation, so it tweaks the
query.

Example, session `e91f7168` window `[27..36]`, 5 `grep` variations
all targeting `narrative_pressure.jsonl` / `actor_storm_summaries.jsonl`.
Shared file path; shared first command-token (`grep`); the grep
pattern itself drifted across attempts.

---

## 4. Why the v0.2 signature predicate missed all of these

The diagnosis is structural, not threshold-related.

**The failure-classified turns are user-role turns carrying
`tool_results`. The originating `tool_uses` live on the immediately
preceding assistant turn.**

The v0.2 `turn_signature_v02()` function extracts its signature
fields from the failure turn directly:

| Signature field | Extracted from | What it gets on a failure-user turn |
|---|---|---|
| `tools` | `turn.tool_uses[*].name` | empty (tool_uses are on the prior assistant turn) |
| `cmd_tokens` | `turn.tool_uses[Bash].input_summary` first-token | empty |
| `file_paths` | regex on `tool_uses[*].input_summary` | empty |
| `error_words` | `tool_results[is_error].content` word bag | populated (or empty if content is empty string) |
| `exception_classes` | regex on tool_result content | rarely populated for shell errors |

Both v0.2 disjunction predicates (1) "shared tool + Jaccard ≥ 0.5"
and (2) "shared file path + shared cmd token" require non-empty
`tools` / `file_paths` / `cmd_tokens` on *both* turns being compared.
Since failure-user turns have all three empty, predicates (1) and
(2) can never fire. The signature predicate effectively reduces to
predicate (3) alone — shared exception class — which fires only for
errors carrying a `[A-Z][a-zA-Z]*Error\b` token. Most shell errors
(permission denied, command not found, non-zero exit) don't carry
such a token.

**Result: 0 prior-match pairs across all 830 applicable cases.** The
loops are present — abundantly — but the signature function is
looking in the wrong turn for the discriminating information.

---

## 5. The "do we need embeddings?" question

**No, not for this substrate.**

The hypothesis behind the embeddings consideration was that real loops
have paraphrased semantic content that token-level matching can't see.
The inspected windows do not show that pattern. They show:

- Type A: literal command variation (same script, different invocation paths)
- Type B: explicit strategy iteration (same file, different tooling)
- Type C: same Read tool, varied paths
- Type D: same query family (grep + same files), varied patterns

All four types are caught **trivially** by a signature function that
operates on the assistant-turn `tool_uses` field. Predicate 2
(shared file path AND shared command first-token) alone would have
matched every Type A and most Type B / C / D windows in the sample.

Embeddings would add machinery (model lock-in, batch-embedding step,
threshold tuning, an additional warrant question about the model's
own grouping behavior) without addressing the actual diagnosis. The
v0.2 signature function design was sound; the **extraction target
was wrong**.

If at a later v0.3 / v0.4 measurement, signature extraction is fixed
and meaningful matches still miss some loops, *that* would be the
moment to revisit embeddings. From this inspection, the substrate
doesn't justify it.

---

## 6. What v0.3 TKOS scope should consider (framing, not lock)

This document does not lock any v0.3 rule. It surfaces three framing
points for the next pre-registration:

1. **Pair the failure turn with its invoking assistant turn before
   extracting the signature.** For every failure-classified user turn
   at index `i`, compute the signature from the union of `tool_uses`
   on turn `i-1` (the invocation) and `tool_results` on turn `i` (the
   error). This is a one-line change to `turn_signature_v02()` and is
   almost certainly the load-bearing v0.3 amendment.

2. **The four loop types may warrant separate intervention
   semantics.** Type A (pure invocation retry without material
   change) is the canonical "suppress this" case. Type B (strategy
   iteration) is *legitimate exploration* — suppressing it would be
   wrong. The v0.1 "no material action between failures" constraint
   was meant to handle this distinction; it deserves explicit per-
   type testing in v0.3.

3. **The Type A → user-asks-for-approval transition (turn 101 in
   `ed22b861`) is a cleanly-resolvable lifecycle event.** The
   assistant *did* eventually recognize the loop and ask the user.
   The intervention rule's value is in firing *earlier* — at attempt
   3 instead of attempt 5. v0.3 should explicitly test "would
   firing at threshold = 2 (instead of 3) materially improve early-
   recognition without inflating false positives?"

These are notes for the v0.3 pre-registration author; nothing here is
binding on the v0.1 or v0.2 measurements, which stand as-is.

---

## 7. Honest read

The v0.2 case-study report said: *"either real loops in this corpus
look different than the rule expects, or our signature definition
still misses how the same error gets reported across retries."*
The hand-review answers cleanly: **the rule expects the right thing;
it just looks for it on the wrong turn.** The loops are present, the
shape is exactly what the original v0.1 §3.1 design imagined, and a
small structural fix in the signature-extraction code path would
catch them.

This is a more boring and more useful answer than "we need
embeddings." It also means v0.3 is more contained than the v0.2
report's §9 priority list implied — the "hand-review repeated-
failure-loop windows" gating step (priority #1) has been done, and
the answer is "fix where the signature is extracted from, not how it
is compared."
