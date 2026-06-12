# Phase 2 — Implementation issues log (v0.1)

Append-only log of ambiguities or interpretation calls encountered while
implementing the v0.1 pre-registration. Each entry records what the
ambiguity was, what implementation decision was made, and whether the
decision should be folded into v0.2 as a rule clarification.

Discipline: implementation should not silently interpret unclear rules.
Any judgment call goes here; the v0.1 measurement is then reported with
this log attached.

---

## I-001 — Sample size estimate was off by an order of magnitude

**Encountered:** 2026-05-29, during phase2_sample.py first run.

**Pre-registration text (§4.3):**
> "Expected eval size: ~1,000–2,000 evaluation turns total, depending on
> session size distribution."

**What actually happened:** With cap=200/session and 164 sessions, the
sample came out to **20,190 turns** — about 10× the estimate.

**Reason:** The estimate appears to have anticipated mostly small subagent
traces; in fact many sessions are 100–200 turns and a handful are ≥ 200,
so the cap activates often. Cap × 164 sessions = ~33k ceiling, real
sample 20k.

**Interpretation decision:** None — the rule (cap=200) was applied
literally as written. The estimate was a parenthetical, not a binding
parameter.

**v0.2 amendment candidate:** the estimate sentence should be removed
or replaced with the correct figure. The cap value itself can stay or be
revised based on what the downstream stages need.

**Impact:** larger eval set than expected; more statistical headroom; more
compute for Phase 2 stages. No directional effect on validity.

---

## I-002 — §3.2 `user_approval_required` "unsatisfied" semantics conflict with §2.9 threshold definition

**Encountered:** 2026-05-29, during phase2_intervention_catalog.py implementation.

**Pre-registration text (§3.2):**
> "`user_approval_required` belief is unsatisfied (authority weight < suppressed threshold)."

**Pre-registration text (§2.9):**
> "Suppressed threshold: weight ≥ 0.7. Above this, interventions backed by the belief may fire without additional check."

**The conflict:** §2.9 says weight ≥ 0.7 means the belief is *strong enough to back an intervention* (suppress firing). §3.2 says weight < 0.7 = "unsatisfied" → fire suppress. These read in opposite directions:

- Natural reading of "user_approval_required is unsatisfied" = "approval is still pending / belief is strong/fresh" → weight HIGH
- Literal §3.2 parenthetical = "weight < 0.7" → weight LOW

Two coherent interpretations:
- (A) Literal: weight < 0.7 = unsatisfied → SUPPRESS deploy
- (B) Intent: weight ≥ 0.7 = unsatisfied → SUPPRESS deploy (matches §2.9 "interventions backed by the belief may fire")

There is also a tertiary ambiguity: should the rule trigger require the belief to have been *instantiated* at some point in the session, or does an uninstantiated belief count as weight = 0 (i.e., satisfies < 0.7 trivially)?

**Implementation decision:** Following the user's instruction to build literally what the pre-registration says:
- Trigger = `deploy_pending` belief active AND a `user_approval_required` instance has been birthed at some prior point in this session AND its weight at the evaluation time is < SUPPRESSED_THRESHOLD (0.7).
- Uninstantiated user_approval_required does NOT trigger the rule (treat as "no requirement exists").
- This is interpretation (A) plus the "instance must exist" qualifier.

**v0.2 amendment candidate:** Pick (A) or (B) explicitly. If (B): rewrite §3.2 to read "user_approval_required is active AND its weight ≥ intervention authority threshold". If (A): clarify that "unsatisfied = weakened belief" semantics.

**Impact:** Direction-dependent. Under (A), the rule fires more often as beliefs decay through 0.7. Under (B), the rule fires when approval requirement is fresh. The v0.1 measurement uses (A); v0.2 measurement will use whichever is chosen and be reported as a separate run for direct comparison.

---

## I-003 — `phase2_signature_match.md` referenced in §3.1 does not exist

**Encountered:** 2026-05-29, during phase2_intervention_catalog.py implementation.

**Pre-registration text (§3.1):**
> "The failure signatures are the same, defined as: same tool name AND same error keyword OR same file path AND same command pattern. The match function is documented in `phase2_signature_match.md` (forthcoming, v0.1)."

**The issue:** The referenced file does not exist in the repository at lock time. The rule itself is stated in §3.1 ("same tool name AND same error keyword OR same file path AND same command pattern"), but operationalization details (error keyword extraction, command pattern definition) are absent.

**Implementation decision (v0.1):** Implement the signature match function inline in phase2_intervention_catalog.py with explicit choices, documented in code comments:
1. **Tool name match:** exact equality on `tool_use.name`.
2. **Error keyword:** lowercased, first 80 chars of the first error message in the turn's tool_results. Two turns share an "error keyword" if the first 80 chars match exactly (after stripping whitespace).
3. **File path:** any file path argument appearing in tool_use input, lowercased. Two turns share a "file path" if their file-path sets intersect.
4. **Command pattern:** the first whitespace-delimited token of any Bash command (e.g. `python`, `pytest`, `git`). Two turns share a "command pattern" if their first-token sets intersect.
5. Signature match = `(same tool name AND same error keyword) OR (same file path AND same command pattern)`.

**v0.2 amendment candidate:** Either write `phase2_signature_match.md` as a standalone spec, or fold the above into §3.1 directly.

**Impact:** Choice of signature definition affects how many candidate loops are detected. The choices above are conservative (exact string matches), which will under-detect loops with paraphrased error messages.

---

## I-004 — §5.5 UNCERTAIN criterion underspecified

**Encountered:** 2026-05-29, during phase2_label_outcomes.py implementation.

**Pre-registration text (§5.5):**
> "Turns where neither correction nor success can be confidently labeled within the window are tagged UNCERTAIN and reported as a separate count alongside TP/FP/FN/TN."

**The issue:** §5.2 implicitly treats "no correction in 5-turn window" as evidence of success (FP/TN). But §5.5 says some cases are UNCERTAIN — and doesn't define when. Two operational triggers seem defensible:
- (A) Evaluation turn sits within the last 1–4 turns of its session (insufficient lookahead).
- (B) Lookahead window contains only system events, no user/assistant prose to inspect.

**Implementation decision (v0.1):** UNCERTAIN iff the evaluation turn has < 1 follow-up turn within the session (i.e., is the final turn of its session). All other cases use §5.2 binary mapping. This is the narrowest defensible reading.

**v0.2 amendment candidate:** Either widen UNCERTAIN explicitly (e.g., < 5 follow-up turns), or commit to the narrow reading and remove §5.5 ambiguity.

**Impact:** Under the narrow reading UNCERTAIN counts will be small (sample is 20,190 turns; final-turn fraction is ~164 sessions × 1 turn ÷ 20,190 ≈ 0.8%). A wider reading would shift many TN/FP into UNCERTAIN.

---

(Entries appended below as they are encountered.)
