# Watching an Assistant Forget: A TKOS Log-Replay Case Study

_A preregistered offline audit of long-running Claude session logs using Belief Stack primitives._

## Status

Draft case study. Phase 1 complete. Phase 2 v0.1 and v0.2 measurements complete.

## Controlling question

Long-running assistants do not only need more memory. They need maintained operational state.

This case study asks whether a TKOS-style replay layer can reconstruct state-level beliefs from real assistant logs, age those beliefs over time, and identify cases where an assistant may have acted on stale, contradicted, or insufficiently warranted state.

The claim is not that TKOS improves Claude. This is an offline replay study, not a live intervention study.

The narrower question is:

> Can TKOS replay identify stale or contradicted state-level beliefs in long-running assistant sessions, using preregistered rules, while accounting for false positives?

## What this case study tests

This case study tests the Belief Stack pattern on a typed operational substrate: engineering assistant logs.

The raw material is long-running workflow behavior: tool calls, tool errors, pipeline runs, validation steps, deployment readiness, report generation, and correction loops.

That makes it a useful substrate for TKOS because the assistant's work depends on operational beliefs that persist across turns: the pipeline is still running; a fix has been attempted; validation is pending; a deploy is waiting on approval; a report is ready; a prior failure has been resolved.

Those beliefs are not single-turn facts. They age. They can be refreshed. They can be contradicted. And if the assistant acts on them without checking whether they still hold, the workflow can drift.

## What this does not claim

This case study does not claim that TKOS improves Claude.

It does not claim live runtime impact.

It does not claim the v0.1 or v0.2 intervention rules are production-ready.

It does not generalize beyond one user's Claude session logs.

It tests whether an offline replay harness can make state-level assistant failures measurable.

## Phase 1: Building the replay substrate

Phase 1 converted raw Claude session logs into a replayable Belief Stack substrate.

The parser normalized 83,271 turns from 164 JSONL files across roughly 10.5 weeks of work. The corpus included 28,946 tool calls and 1,309 explicit tool errors.

Each turn was assigned to one of seven typed operational regions where possible: data fetch, pipeline run, failure diagnosis, validation, deploy readiness, report generation, and evidence sealing.

Turns outside that operational substrate were left UNCLASSIFIED.

That high UNCLASSIFIED rate was intentional. The goal was not to force every conversational turn into a region. The goal was to identify the action-bearing parts of the workflow and leave ordinary conversation outside coverage.

Every classified turn emitted both a label and a warrant. That is the Belief Stack representation contract in miniature: no label without warrant.

## Phase 2: From per-turn facts to cross-turn beliefs

Phase 2 introduced cross-turn state-level beliefs.

Unlike per-turn tool facts, these beliefs decay. The replay layer tracked eight state beliefs:

`pipeline_running`, `pipeline_failed`, `issue_under_diagnosis`, `fix_attempted`, `validation_pending`, `deploy_pending`, `report_ready`, and `user_approval_required`.

Each belief had birth, refresh, retirement, contradiction, and decay rules. The purpose was not to infer vague intent. The purpose was to reconstruct operational state: what the assistant appeared to believe was true at a given point in the workflow, and whether that belief still had enough warrant to authorize action.

Phase 2 sampled 20,190 evaluation turns from the 83,271-turn universe, stratified by session with a 200-turn-per-session cap and a locked random seed (20260529). Across those 20,190 evaluation points, 11,262 belief instances were tracked across the session ledger — births, refreshes, contradictions, and stale-decay retirements all logged with timestamps.

## Phase 2 v0.1: The first locked measurement

The v0.1 intervention catalog tested four patterns: `repeated_failure_loop`, `stale_deploy_prior`, `stale_pipeline_prior`, and `contradicted_fix_prior`.

The important result from v0.1 was not that the catalog worked.

It mostly did not.

Three of four rules were structurally too narrow or ambiguous. `repeated_failure_loop` never fired. `stale_deploy_prior` never fired. `contradicted_fix_prior` had zero applicable turns. Only `stale_pipeline_prior` fired at scale.

That is still a useful result.

The replay harness did what it was supposed to do: it made the failure of the rules visible instead of allowing the system to narrate success.

## What v0.1 taught us

v0.1 exposed four concrete problems.

First, repeated-failure-loop detection was too strict. Exact or near-exact signature matching did not capture how repeated failures appear in real assistant logs.

Second, deploy gating had a threshold-semantics problem. The approval requirement rule was written in a way that made it nearly unable to fire.

Third, contradicted-fix detection was too narrow. It depended on Bash validation failures and missed broader post-fix tool errors.

Fourth, stale pipeline detection was measurable but miscalibrated. A 20-minute threshold produced many suppressions, but also a non-trivial false-positive rate.

The result was not a failed proof of concept. It was a successful falsification pass.

## Phase 2 v0.2: Amended rules, same measurement discipline

v0.2 kept the same sample, same success criterion, same belief definitions, and same labeling protocol.

Only the intervention rules changed.

The amendments renamed the intervention threshold, fixed deploy-gating semantics, loosened repeated-failure signature matching, broadened contradicted-fix detection with context overlap, and moved stale-pipeline threshold from 20 minutes to 30 minutes.

v0.2 was not treated as a replacement for v0.1. It was reported separately, with a head-to-head comparison.

That separation matters. v0.1 remains the record of what the first locked rules did. v0.2 tests whether specific amendments improve measurement coverage without hiding the earlier failure.

## What v0.2 showed

### Head-to-head: v0.1 vs v0.2

The same 20,190-turn sample, the same belief timelines, the same 5-turn lookahead for labeling. The only thing that changed is the intervention rule operationalizations.

The table should be read as a calibration artifact, not a scoreboard: v0.2 improved some measurements, exposed new modeling failures, and left other rules unchanged.

| Rule | Applicable | SUPPRESS v0.1 → v0.2 | TP v0.1 → v0.2 | FP v0.1 → v0.2 | FN v0.1 → v0.2 | TN v0.1 → v0.2 | Detection rate v0.1 → v0.2 | False-positive rate v0.1 → v0.2 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| `repeated_failure_loop` | 830 → 830 | 0 → 0 | 0 → 0 | 0 → 0 | 167 → 167 | 643 → 643 | 0.000 → 0.000 | 0.000 → 0.000 |
| `stale_deploy_prior` | 126 → 126 | 0 → 0 | 0 → 0 | 0 → 0 | 17 → 17 | 109 → 109 | 0.000 → 0.000 | 0.000 → 0.000 |
| `stale_pipeline_prior` | 3,146 → 3,146 | 558 → 242 | 41 → 21 | 517 → 221 | 190 → 210 | 2,379 → 2,675 | 0.177 → 0.091 | 0.179 → 0.076 |
| `contradicted_fix_prior` | 0 → 178 | 0 → 178 | 0 → 42 | 0 → 136 | 0 → 0 | 0 → 0 | n/a → 1.000* | n/a → 1.000* |

\* `contradicted_fix_prior` has no ALLOW verdicts by construction (applicability implies SUPPRESS), so the detection-rate and FPR denominators are degenerate. The meaningful metric for this rule is **precision: 42 / 178 ≈ 0.24**.

The prose below walks the table row by row.

### Repeated-failure-loop

Repeated-failure-loop detection still did not fire. Even after loosening signature matching to a disjunction — same tool plus error-message Jaccard ≥ 0.5, or shared file path with shared command first-token, or shared exception class — the rule produced zero suppressions. That suggests either the corpus contains few three-in-ten-turn same-signature loops, or the current definition still does not match how loops actually appear in assistant workflows.

### Stale deploy gating

Stale deploy gating also still did not fire. This time the result pointed away from the intervention rule and toward the belief lifecycle. By the time a deploy action appears, `user_approval_required` has usually already been retired by the same user signal that births `deploy_pending`. The two beliefs do not co-exist when the intervention needs them. That is a state-modeling issue, not just a rule issue.

### Stale pipeline detection

Stale pipeline detection showed a clear threshold tradeoff. Moving from 20 minutes to 30 minutes reduced suppressions (558 → 242) and more than halved the false-positive rate (0.179 → 0.076), but it also halved detection (0.177 → 0.091). That suggests the problem is not solved by a single global timeout. Pipeline expectations likely need duration priors by task type.

### Contradicted-fix detection

Contradicted-fix detection became measurable. v0.1 had zero applicable turns; v0.2 surfaced 178. But precision was low: 42 of those 178 contradictions held up in the five-turn lookahead window, and 136 did not. The context-overlap predicate caught real validation failures but also incidental same-file or same-command errors that did not actually invalidate the fix. The rule needs a stronger temporal constraint or a sharper distinction between validation-context failures and incidental overlap.

## What the stack made visible

A normal log parser can tell you that a command failed.

A normal dashboard can count tool errors.

The Belief Stack view asks a different question:

> What did the assistant believe was true at this point in the workflow, what evidence gave that belief authority, had that authority decayed, and should the next action have been allowed?

That is the difference between observing events and maintaining operational state.

In this case study, the stack made four things visible:

1. operational regions within long conversations
2. state-level beliefs that persisted across turns
3. intervention rules whose failures could be measured
4. lifecycle/modeling errors that would have been invisible in a simple tool-error count

The most important finding is not that v0.2 "worked."

The most important finding is that v0.2 turned broad v0.1 failures into narrower modeling questions.

## Why this matters

Long-running assistants are increasingly used for engineering workflows, research workflows, analysis pipelines, and deployment-adjacent work.

In those settings, failures often do not come from a single bad answer.

They come from stale operational state: assuming a pipeline is still running when it has failed; assuming a fix worked before validation; retrying the same broken action; deploying from an outdated approval state; carrying forward an old plan after evidence changed.

These are not primarily memory failures.

They are state-management failures.

TKOS is the hypothesis that these failures can be made explicit enough to audit, suppress, or eventually prevent.

## Limits

This is an offline replay study.

The ground truth is retrospective.

The corpus comes from one user's Claude sessions.

The intervention rules are early.

The v0.1 and v0.2 catalogs are not production-ready.

The strongest claim available at this stage is that the replay method can reconstruct assistant state, apply preregistered intervention rules, and falsify those rules with explicit false-positive accounting.

## Next validation

The next step is not a public runtime claim. It is v0.3.

v0.3 should begin with hand-review of repeated-failure-loop candidate windows, because further loosening without examples risks inventing a detector for a pattern that may not exist in this corpus.

It should also revise `user_approval_required` lifecycle behavior, likely by separating `approval_pending` from `approval_observed`.

For `stale_pipeline_prior`, v0.3 should test adaptive expected-duration priors instead of a global 20- or 30-minute threshold.

For `contradicted_fix_prior`, v0.3 should add a temporal window around the fix attempt and distinguish validation-context failures from incidental overlap.

If those changes improve detection while reducing false positives, the case study can move from "measurement harness validated" to "intervention catalog beginning to calibrate."

If they do not, that is also useful. It means the state representation or labeling protocol needs revision before any live-runtime claim is justified.

---

## Methodology references

- Phase 1 substrate construction: [tkos_log_replay/README.md](./README.md)
- Phase 2 v0.1 pre-registration: [PHASE2_PRE_REGISTRATION_v0.1.md](./PHASE2_PRE_REGISTRATION_v0.1.md)
- Phase 2 v0.1 measurement report: [PHASE2_REPORT.md](./PHASE2_REPORT.md)
- Phase 2 v0.2 pre-registration: [PHASE2_PRE_REGISTRATION_v0.2.md](./PHASE2_PRE_REGISTRATION_v0.2.md)
- Phase 2 v0.2 head-to-head report: [PHASE2_REPORT_v0_2.md](./PHASE2_REPORT_v0_2.md)
- Implementation ambiguities log: [PHASE2_ISSUES_LOG.md](./PHASE2_ISSUES_LOG.md)
- v0.2 amendments: [PHASE2_AMENDMENTS_FOR_V02.md](./PHASE2_AMENDMENTS_FOR_V02.md)
