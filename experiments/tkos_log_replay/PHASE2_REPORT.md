# F-023 Phase 2 — TKOS Log-Replay Measurement Report (v0.1)

_Generated: 2026-05-29T19:10:00.254778Z_

**Rules version:** v0.1, locked 2026-05-29.
**Pre-registration:** [PHASE2_PRE_REGISTRATION_v0.1.md](PHASE2_PRE_REGISTRATION_v0.1.md).
**Issues log:** [PHASE2_ISSUES_LOG.md](PHASE2_ISSUES_LOG.md) (I-001 through I-004).
**Amendments staged for v0.2:** [PHASE2_AMENDMENTS_FOR_V02.md](PHASE2_AMENDMENTS_FOR_V02.md).

---

## 1. Sampling summary

| Field | Value |
|---|---|
| Random seed | 20260529 |
| Cap per session | 200 |
| Sessions | 164 |
| Universe (all classified turns) | 83,271 |
| Sampled evaluation turns | 20,190 |

Note: the pre-registration estimated ~1,000–2,000 evaluation turns.
Actual: 20,190. See I-001 in the issues log.

---

## 2. Belief tracking summary

Belief instances produced by phase2_belief_tracker.py across the sampled sessions:

| Belief | Instances |
|---|--:|
| `fix_attempted` | 7,263 |
| `issue_under_diagnosis` | 1,340 |
| `validation_pending` | 1,119 |
| `user_approval_required` | 526 |
| `pipeline_running` | 422 |
| `pipeline_failed` | 252 |
| `report_ready` | 175 |
| `deploy_pending` | 165 |
| **Total** | **11,262** |

Lifecycle outcomes (retirement reasons):

| Reason | Count |
|---|--:|
| `stale_decay` | 8,137 |
| `transitioned_to_fix_attempted` | 1,146 |
| `validation_observed_None` | 396 |
| `contradicted` | 291 |
| `deploy_executed` | 111 |
| `user_provided_approval` | 44 |
| `completion_evidence` | 12 |

---

## 3. Per-rule outcomes (§6.1)

**Truth labels** (§5.2):

- **TP** = SUPPRESS + actual problem followed
- **FP** = SUPPRESS + actual run was fine within 5-turn window
- **FN** = ALLOW + actual problem followed
- **TN** = ALLOW + actual run was fine
- **UNCERTAIN** = no 5-turn lookahead available (final turn of session); see I-004.

| Rule | Applicable | TP | FP | FN | TN | UNCERTAIN | Detection rate | False-positive rate |
|---|--:|--:|--:|--:|--:|--:|---|---|
| `repeated_failure_loop` | 830 | 0 | 0 | 167 | 643 | 20 | 0.000 | 0.000 |
| `stale_deploy_prior` | 126 | 0 | 0 | 17 | 109 | 0 | 0.000 | 0.000 |
| `stale_pipeline_prior` | 3,146 | 41 | 517 | 190 | 2,379 | 19 | 0.177 | 0.179 |
| `contradicted_fix_prior` | 0 | 0 | 0 | 0 | 0 | 0 | n/a | n/a |

### 3.1 Reading the numbers (§6.1 compliance)

Per §6.1, this report does **not**:

- Claim that TKOS improves Claude. Offline replay is not live impact.
- Compare to a specific F1 or accuracy threshold as "good" or "bad".
- Claim that v0.1 rules are correct beyond what the data shows. They are a v0.1 proposal.
- Generalize beyond this user's 164-session, 10.5-week corpus.

What the v0.1 numbers do show:

- **`repeated_failure_loop`**: applicable on 830 turns, never fired (0 SUPPRESS). Within the applicable population, 167 turns had a downstream problem that was not flagged. The strict signature-match definition (I-003) plus the no-material-action constraint are likely filtering out real loops with paraphrased errors. v0.2 candidate: loosen signature matching.
- **`stale_deploy_prior`**: applicable on 126 deploy actions, never fired (0 SUPPRESS). Within the applicable population, 17 deploy actions had a downstream problem. The §3.2 ambiguity (I-002) is directly relevant — under the literal reading the rule rarely triggers because `user_approval_required` is rarely instantiated AND below threshold simultaneously.
- **`stale_pipeline_prior`**: applicable on 3,146 turns, fired 558 times. Detection rate 0.177 (TP=41, FN=190). False-positive rate 0.179 (FP=517, TN=2379). This is the only rule with non-trivial firing; the 17.9% FPR shows the 20-min threshold is conservative (many long pipelines complete fine without a status check).
- **`contradicted_fix_prior`**: applicable on 0 turns. The applicability predicate (turn IS a Bash validation command with tool_error=true) appears to never match in the sample. Two candidate causes for v0.2 review: (a) the VALIDATION_PATTERNS regex is too narrow; (b) the operationalization should treat any post-fix tool error as validation FAIL, not only Bash validation commands.

### 3.2 Per-session concentration

Number of sessions in which each rule had at least one applicable turn:

| Rule | Sessions |
|---|--:|
| `repeated_failure_loop` | 145 |
| `stale_deploy_prior` | 47 |
| `stale_pipeline_prior` | 61 |
| `contradicted_fix_prior` | 0 |

---

## 4. Repeated-failure-loop subsection (§6.5)

The v0.1 rule produced **0 SUPPRESS verdicts** across 830 applicable turns. Below are anonymized examples of multi-failure clusters that were detected by the rule's applicability predicate but did not meet the signature-match + no-material-action trigger. Each example shows how many turns were matched against the evaluation turn's signature within the 10-turn window.

_(No multi-match examples found; the signature predicate is too narrow to produce even partial matches.)_

---

## 5. Methodology (§6.6)

This report measures the v0.1 rules exactly as pre-registered in [PHASE2_PRE_REGISTRATION_v0.1.md](PHASE2_PRE_REGISTRATION_v0.1.md). Four ambiguities were encountered during implementation and resolved operationally without changing v0.1 semantics:

- **I-001** — sample size estimate (~1k–2k) was off by ~10× (actual 20,190). Implementation followed the stated cap=200/session literally.
- **I-002** — §3.2 "unsatisfied (weight < suppressed threshold)" reads as the opposite of §2.9's threshold semantics. Implementation used the literal §3.2 parenthetical; v0.2 should pick one interpretation explicitly.
- **I-003** — `phase2_signature_match.md` referenced in §3.1 does not exist; implementation defined a conservative inline signature-match function (exact 80-char error prefix, set intersection on file paths and first-token commands).
- **I-004** — §5.5 UNCERTAIN criterion was narrowed to "no follow-up turns in session" because the broader threshold was not pre-registered.

**Sampling protocol:** stratified random sample, seed=20260529, cap=min(200, n_turns) per session across all 164 sessions. Produced 20,190 evaluation turns from a universe of 83,271 classified turns.

**Labeling protocol:** 5-turn look-ahead. Patterns from §5.3 detect user corrections; further tool_error within window counts as continued problem.

---

## 6. Audit trail

| File | SHA-256 |
|---|---|
| `phase2_sample.json` | `651f2f4eadf1309a83b826f47c81c212519c2e23a0e4f6ab6ecbd1620c83821a` |
| `phase2_belief_timelines.jsonl` | `8833f1b4f13f1fd7328b9d5a03087e509d6c50ed46469d9d494fa2b20a370ae2` |
| `phase2_intervention_verdicts.jsonl` | `18047ae600a28a9844b98aa65a804f536312f65ac128f0c8e61c03936356e1b8` |
| `phase2_labeled_outcomes.jsonl` | `2ebb45aa07793199a9bf476ae71d220a0be557c4933b6463a637f7f49d9e4bdc` |

---

## 7. What v0.2 needs

In priority order based on this v0.1 measurement:

1. **Resolve I-002** (§3.2 semantics) explicitly. Under the literal reading, `stale_deploy_prior` is structurally unable to fire on this corpus.
2. **Loosen signature matching for §3.1**. Strict exact-prefix matching produced 0 SUPPRESS verdicts despite 167 ALLOW-FN cases that suggest real loops were present.
3. **Broaden §3.4 applicability**. The current Bash-only validation detection produced 0 applicable turns. Treating any post-fix tool error as a validation outcome would surface more events.
4. **Calibrate §3.3 threshold**. 17.9% FPR at the 20-min boundary suggests the threshold may be too aggressive for this user's pipeline-completion times. A second-pass measurement with the 30-min or 40-min boundary would be cheap.
5. **Rename suppressed → intervention authority threshold** (A-001 in amendments file).
