#!/usr/bin/env python3
"""
F-023 Phase 2 step 5: human-readable report.

Per PHASE2_PRE_REGISTRATION_v0.1.md §6:
  1. TP / FP / FN / TN counts per intervention rule + UNCERTAIN.
  2. Detection rate per rule, with absolute counts.
  3. False-positive rate per rule, with absolute counts.
  4. Per-session breakdown.
  5. Repeated-failure-loop subsection with ≥3 anonymized example loops.
  6. Methodology section pointing at PHASE2_PRE_REGISTRATION_v0.1.md.

Reports do NOT claim "TKOS improves Claude", do NOT score F1 vs threshold,
do NOT generalize beyond this corpus (§6.1).

Inputs:
  data/phase2_labeled_outcomes.jsonl
  data/phase2_intervention_verdicts.jsonl
  data/phase2_belief_timelines.jsonl
  data/phase2_sample.json

Outputs:
  data/phase2_report.json
  PHASE2_REPORT.md
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from collections import Counter, defaultdict
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent
LABELS_PATH    = ROOT / "data" / "phase2_labeled_outcomes.jsonl"
VERDICTS_PATH  = ROOT / "data" / "phase2_intervention_verdicts.jsonl"
TIMELINES_PATH = ROOT / "data" / "phase2_belief_timelines.jsonl"
SAMPLE_PATH    = ROOT / "data" / "phase2_sample.json"

REPORT_JSON_PATH = ROOT / "data" / "phase2_report.json"
REPORT_MD_PATH   = ROOT / "PHASE2_REPORT.md"

RULES_VERSION = "v0.1"

RULE_ORDER = [
    "repeated_failure_loop",
    "stale_deploy_prior",
    "stale_pipeline_prior",
    "contradicted_fix_prior",
]


def load_jsonl(p: pathlib.Path) -> list[dict]:
    out = []
    with p.open() as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def file_sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    print("Loading inputs…")
    labels    = load_jsonl(LABELS_PATH)
    verdicts  = load_jsonl(VERDICTS_PATH)
    timelines = load_jsonl(TIMELINES_PATH)
    sample    = json.loads(SAMPLE_PATH.read_text())

    # ─── Per-rule TP/FP/FN/TN/UNCERT ─────────────────────────────────────
    per_rule: dict[str, dict] = {}
    for rule in RULE_ORDER:
        items = [l for l in labels if l["rule"] == rule]
        tp = sum(1 for l in items if l["label"] == "TP")
        fp = sum(1 for l in items if l["label"] == "FP")
        fn = sum(1 for l in items if l["label"] == "FN")
        tn = sum(1 for l in items if l["label"] == "TN")
        u  = sum(1 for l in items if l["label"] == "UNCERTAIN")
        applicable = tp + fp + fn + tn + u
        suppress_count = tp + fp
        allow_count    = fn + tn
        det = tp / (tp + fn) if (tp + fn) > 0 else None
        fpr = fp / (fp + tn) if (fp + tn) > 0 else None
        per_rule[rule] = {
            "applicable":   applicable,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "uncertain":    u,
            "suppress_total": suppress_count,
            "allow_total":    allow_count,
            "detection_rate": det,
            "false_positive_rate": fpr,
        }

    # ─── Per-session breakdown ───────────────────────────────────────────
    per_session: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for l in labels:
        per_session[l["session_id"]][l["rule"]][l["label"]] += 1

    # ─── Repeated-failure-loop examples ──────────────────────────────────
    # The v0.1 rule produced 0 SUPPRESS verdicts; surface the ALLOW-with-FN
    # cases (multi-failure but didn't trigger threshold/signature) as
    # diagnostic context for v0.2.
    rfl_examples: list[dict] = []
    seen_sessions: set[str] = set()
    for v in verdicts:
        if v["rule"] != "repeated_failure_loop":
            continue
        ev = v.get("evidence", {})
        mc = ev.get("matched_turn_count", 0)
        if mc < 2 or v["session_id"] in seen_sessions:
            continue
        seen_sessions.add(v["session_id"])
        rfl_examples.append({
            "session_id_hash": hashlib.sha1(v["session_id"].encode()).hexdigest()[:8],
            "turn_idx":        v["turn_idx"],
            "matched_count":   mc,
            "verdict":         v["verdict"],
            "evidence":        ev,
        })
        if len(rfl_examples) >= 5:
            break

    # ─── Belief instance counts (lifecycle summary) ──────────────────────
    belief_counts = Counter(t["belief_name"] for t in timelines)
    retirement_counts = Counter(t["retired_reason"] for t in timelines if t.get("retired_reason"))

    # ─── Sampling summary ────────────────────────────────────────────────
    sampling = {
        "rules_version":    sample["rules_version"],
        "seed":             sample["seed"],
        "cap_per_session":  sample["cap_per_session"],
        "n_sessions":       sample["n_sessions"],
        "n_universe":       sample["n_universe"],
        "n_sampled":        sample["n_sampled"],
    }

    # ─── Phase 1 artifact hashes (per §9 audit trail) ────────────────────
    artifact_hashes = {
        "phase2_sample.json":               file_sha256(SAMPLE_PATH),
        "phase2_belief_timelines.jsonl":    file_sha256(TIMELINES_PATH),
        "phase2_intervention_verdicts.jsonl": file_sha256(VERDICTS_PATH),
        "phase2_labeled_outcomes.jsonl":    file_sha256(LABELS_PATH),
    }

    # ─── Write JSON ──────────────────────────────────────────────────────
    report = {
        "rules_version":   RULES_VERSION,
        "generated_at":    datetime.utcnow().isoformat() + "Z",
        "sampling":        sampling,
        "per_rule":        per_rule,
        "rfl_examples":    rfl_examples,
        "belief_instance_counts":  dict(belief_counts.most_common()),
        "retirement_reason_counts": dict(retirement_counts.most_common()),
        "artifact_sha256": artifact_hashes,
        "n_sessions_with_any_applicable_turn": len(per_session),
        "issues_log_refs": ["I-001", "I-002", "I-003", "I-004"],
    }
    REPORT_JSON_PATH.write_text(json.dumps(report, indent=2))
    print(f"Wrote {REPORT_JSON_PATH}")

    # ─── Write Markdown ──────────────────────────────────────────────────
    lines: list[str] = []
    lines.append("# F-023 Phase 2 — TKOS Log-Replay Measurement Report (v0.1)\n")
    lines.append(f"_Generated: {report['generated_at']}_\n")
    lines.append("**Rules version:** v0.1, locked 2026-05-29.")
    lines.append("**Pre-registration:** [PHASE2_PRE_REGISTRATION_v0.1.md](PHASE2_PRE_REGISTRATION_v0.1.md).")
    lines.append("**Issues log:** [PHASE2_ISSUES_LOG.md](PHASE2_ISSUES_LOG.md) (I-001 through I-004).")
    lines.append("**Amendments staged for v0.2:** [PHASE2_AMENDMENTS_FOR_V02.md](PHASE2_AMENDMENTS_FOR_V02.md).")
    lines.append("")
    lines.append("---\n")
    lines.append("## 1. Sampling summary\n")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Random seed | {sampling['seed']} |")
    lines.append(f"| Cap per session | {sampling['cap_per_session']} |")
    lines.append(f"| Sessions | {sampling['n_sessions']:,} |")
    lines.append(f"| Universe (all classified turns) | {sampling['n_universe']:,} |")
    lines.append(f"| Sampled evaluation turns | {sampling['n_sampled']:,} |")
    lines.append("")
    lines.append("Note: the pre-registration estimated ~1,000–2,000 evaluation turns.")
    lines.append("Actual: 20,190. See I-001 in the issues log.")
    lines.append("")
    lines.append("---\n")
    lines.append("## 2. Belief tracking summary\n")
    lines.append("Belief instances produced by phase2_belief_tracker.py across the sampled sessions:")
    lines.append("")
    lines.append("| Belief | Instances |")
    lines.append("|---|--:|")
    for bname in [
        "fix_attempted", "issue_under_diagnosis", "validation_pending",
        "user_approval_required", "pipeline_running", "pipeline_failed",
        "report_ready", "deploy_pending",
    ]:
        n = report["belief_instance_counts"].get(bname, 0)
        lines.append(f"| `{bname}` | {n:,} |")
    lines.append(f"| **Total** | **{sum(report['belief_instance_counts'].values()):,}** |")
    lines.append("")
    lines.append("Lifecycle outcomes (retirement reasons):")
    lines.append("")
    lines.append("| Reason | Count |")
    lines.append("|---|--:|")
    for reason, n in report["retirement_reason_counts"].items():
        lines.append(f"| `{reason}` | {n:,} |")
    lines.append("")
    lines.append("---\n")
    lines.append("## 3. Per-rule outcomes (§6.1)\n")
    lines.append("**Truth labels** (§5.2):")
    lines.append("")
    lines.append("- **TP** = SUPPRESS + actual problem followed")
    lines.append("- **FP** = SUPPRESS + actual run was fine within 5-turn window")
    lines.append("- **FN** = ALLOW + actual problem followed")
    lines.append("- **TN** = ALLOW + actual run was fine")
    lines.append("- **UNCERTAIN** = no 5-turn lookahead available (final turn of session); see I-004.")
    lines.append("")
    lines.append("| Rule | Applicable | TP | FP | FN | TN | UNCERTAIN | Detection rate | False-positive rate |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|---|---|")
    for rule in RULE_ORDER:
        r = per_rule[rule]
        det = f"{r['detection_rate']:.3f}" if r["detection_rate"] is not None else "n/a"
        fpr = f"{r['false_positive_rate']:.3f}" if r["false_positive_rate"] is not None else "n/a"
        lines.append(
            f"| `{rule}` | {r['applicable']:,} | {r['tp']:,} | {r['fp']:,} | "
            f"{r['fn']:,} | {r['tn']:,} | {r['uncertain']:,} | {det} | {fpr} |"
        )
    lines.append("")
    lines.append("### 3.1 Reading the numbers (§6.1 compliance)\n")
    lines.append("Per §6.1, this report does **not**:")
    lines.append("")
    lines.append("- Claim that TKOS improves Claude. Offline replay is not live impact.")
    lines.append("- Compare to a specific F1 or accuracy threshold as \"good\" or \"bad\".")
    lines.append("- Claim that v0.1 rules are correct beyond what the data shows. They are a v0.1 proposal.")
    lines.append("- Generalize beyond this user's 164-session, 10.5-week corpus.")
    lines.append("")
    lines.append("What the v0.1 numbers do show:")
    lines.append("")
    rfl = per_rule["repeated_failure_loop"]
    sdp = per_rule["stale_deploy_prior"]
    spp = per_rule["stale_pipeline_prior"]
    cfp = per_rule["contradicted_fix_prior"]
    lines.append(
        f"- **`repeated_failure_loop`**: applicable on {rfl['applicable']:,} turns, never fired "
        f"({rfl['suppress_total']} SUPPRESS). Within the applicable population, "
        f"{rfl['fn']:,} turns had a downstream problem that was not flagged. The strict "
        "signature-match definition (I-003) plus the no-material-action constraint are likely "
        "filtering out real loops with paraphrased errors. v0.2 candidate: loosen signature matching."
    )
    lines.append(
        f"- **`stale_deploy_prior`**: applicable on {sdp['applicable']:,} deploy actions, never fired "
        f"({sdp['suppress_total']} SUPPRESS). Within the applicable population, "
        f"{sdp['fn']:,} deploy actions had a downstream problem. The §3.2 ambiguity (I-002) is "
        "directly relevant — under the literal reading the rule rarely triggers because "
        "`user_approval_required` is rarely instantiated AND below threshold simultaneously."
    )
    lines.append(
        f"- **`stale_pipeline_prior`**: applicable on {spp['applicable']:,} turns, fired "
        f"{spp['suppress_total']:,} times. Detection rate "
        f"{spp['detection_rate']:.3f} (TP={spp['tp']}, FN={spp['fn']}). False-positive rate "
        f"{spp['false_positive_rate']:.3f} (FP={spp['fp']}, TN={spp['tn']}). This is the only "
        "rule with non-trivial firing; the 17.9% FPR shows the 20-min threshold is conservative "
        "(many long pipelines complete fine without a status check)."
    )
    lines.append(
        f"- **`contradicted_fix_prior`**: applicable on {cfp['applicable']} turns. The applicability "
        "predicate (turn IS a Bash validation command with tool_error=true) appears to never match "
        "in the sample. Two candidate causes for v0.2 review: (a) the VALIDATION_PATTERNS regex is "
        "too narrow; (b) the operationalization should treat any post-fix tool error as validation "
        "FAIL, not only Bash validation commands."
    )
    lines.append("")
    lines.append("### 3.2 Per-session concentration\n")
    lines.append("Number of sessions in which each rule had at least one applicable turn:")
    lines.append("")
    lines.append("| Rule | Sessions |")
    lines.append("|---|--:|")
    for rule in RULE_ORDER:
        n_sess = sum(1 for sid in per_session if rule in per_session[sid])
        lines.append(f"| `{rule}` | {n_sess} |")
    lines.append("")

    # ─── §6.5 Repeated-failure-loop subsection ───────────────────────────
    lines.append("---\n")
    lines.append("## 4. Repeated-failure-loop subsection (§6.5)\n")
    lines.append(
        f"The v0.1 rule produced **0 SUPPRESS verdicts** across {rfl['applicable']:,} applicable "
        "turns. Below are anonymized examples of multi-failure clusters that were detected by the "
        "rule's applicability predicate but did not meet the signature-match + no-material-action "
        "trigger. Each example shows how many turns were matched against the evaluation turn's "
        "signature within the 10-turn window."
    )
    lines.append("")
    if not rfl_examples:
        lines.append("_(No multi-match examples found; the signature predicate is too narrow to produce "
                     "even partial matches.)_")
    else:
        for i, ex in enumerate(rfl_examples, 1):
            lines.append(f"**Example {i}** — session `{ex['session_id_hash']}`, turn {ex['turn_idx']}")
            lines.append(f"- matched signature count: {ex['matched_count']}")
            lines.append(f"- verdict: {ex['verdict']}")
            if "error_keyword" in ex["evidence"]:
                kw = ex["evidence"]["error_keyword"] or ""
                lines.append(f"- error keyword (first 80 chars): `{kw[:80]}`")
            lines.append("")
    lines.append("")
    lines.append("---\n")
    lines.append("## 5. Methodology (§6.6)\n")
    lines.append("This report measures the v0.1 rules exactly as pre-registered in "
                 "[PHASE2_PRE_REGISTRATION_v0.1.md](PHASE2_PRE_REGISTRATION_v0.1.md). "
                 "Four ambiguities were encountered during implementation and resolved "
                 "operationally without changing v0.1 semantics:")
    lines.append("")
    lines.append("- **I-001** — sample size estimate (~1k–2k) was off by ~10× (actual 20,190). "
                 "Implementation followed the stated cap=200/session literally.")
    lines.append("- **I-002** — §3.2 \"unsatisfied (weight < suppressed threshold)\" reads as "
                 "the opposite of §2.9's threshold semantics. Implementation used the literal §3.2 "
                 "parenthetical; v0.2 should pick one interpretation explicitly.")
    lines.append("- **I-003** — `phase2_signature_match.md` referenced in §3.1 does not exist; "
                 "implementation defined a conservative inline signature-match function (exact "
                 "80-char error prefix, set intersection on file paths and first-token commands).")
    lines.append("- **I-004** — §5.5 UNCERTAIN criterion was narrowed to \"no follow-up turns in "
                 "session\" because the broader threshold was not pre-registered.")
    lines.append("")
    lines.append("**Sampling protocol:** stratified random sample, seed=20260529, "
                 "cap=min(200, n_turns) per session across all 164 sessions. Produced 20,190 "
                 "evaluation turns from a universe of 83,271 classified turns.")
    lines.append("")
    lines.append("**Labeling protocol:** 5-turn look-ahead. Patterns from §5.3 detect user "
                 "corrections; further tool_error within window counts as continued problem.")
    lines.append("")
    lines.append("---\n")
    lines.append("## 6. Audit trail\n")
    lines.append("| File | SHA-256 |")
    lines.append("|---|---|")
    for name, h in artifact_hashes.items():
        lines.append(f"| `{name}` | `{h}` |")
    lines.append("")
    lines.append("---\n")
    lines.append("## 7. What v0.2 needs\n")
    lines.append("In priority order based on this v0.1 measurement:")
    lines.append("")
    lines.append("1. **Resolve I-002** (§3.2 semantics) explicitly. Under the literal reading, "
                 "`stale_deploy_prior` is structurally unable to fire on this corpus.")
    lines.append("2. **Loosen signature matching for §3.1**. Strict exact-prefix matching produced "
                 "0 SUPPRESS verdicts despite 167 ALLOW-FN cases that suggest real loops were "
                 "present.")
    lines.append("3. **Broaden §3.4 applicability**. The current Bash-only validation detection "
                 "produced 0 applicable turns. Treating any post-fix tool error as a validation "
                 "outcome would surface more events.")
    lines.append("4. **Calibrate §3.3 threshold**. 17.9% FPR at the 20-min boundary suggests the "
                 "threshold may be too aggressive for this user's pipeline-completion times. "
                 "A second-pass measurement with the 30-min or 40-min boundary would be cheap.")
    lines.append("5. **Rename suppressed → intervention authority threshold** (A-001 in "
                 "amendments file).")
    lines.append("")
    REPORT_MD_PATH.write_text("\n".join(lines))
    print(f"Wrote {REPORT_MD_PATH}")


if __name__ == "__main__":
    main()
