#!/usr/bin/env python3
"""
F-023 Phase 2 v0.2: head-to-head report.

Reports v0.2 numbers alongside v0.1 numbers (read from phase2_report.json).
Honors §6.1 honesty constraints. Writes phase2_report_v0_2.json and
PHASE2_REPORT_v0_2.md.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from collections import Counter, defaultdict
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent
LABELS_V02_PATH   = ROOT / "data" / "phase2_labeled_outcomes_v0_2.jsonl"
VERDICTS_V02_PATH = ROOT / "data" / "phase2_intervention_verdicts_v0_2.jsonl"
TIMELINES_PATH    = ROOT / "data" / "phase2_belief_timelines.jsonl"
SAMPLE_PATH       = ROOT / "data" / "phase2_sample.json"
V01_REPORT_PATH   = ROOT / "data" / "phase2_report.json"

REPORT_JSON_PATH = ROOT / "data" / "phase2_report_v0_2.json"
REPORT_MD_PATH   = ROOT / "PHASE2_REPORT_v0_2.md"

RULES_VERSION = "v0.2"
RULE_ORDER = [
    "repeated_failure_loop",
    "stale_deploy_prior",
    "stale_pipeline_prior",
    "contradicted_fix_prior",
]


def load_jsonl(p):
    out = []
    with p.open() as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def file_sha256(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def per_rule_summary(labels):
    out = {}
    for rule in RULE_ORDER:
        items = [l for l in labels if l["rule"] == rule]
        tp = sum(1 for l in items if l["label"] == "TP")
        fp = sum(1 for l in items if l["label"] == "FP")
        fn = sum(1 for l in items if l["label"] == "FN")
        tn = sum(1 for l in items if l["label"] == "TN")
        u  = sum(1 for l in items if l["label"] == "UNCERTAIN")
        applicable = tp + fp + fn + tn + u
        det = tp / (tp + fn) if (tp + fn) > 0 else None
        fpr = fp / (fp + tn) if (fp + tn) > 0 else None
        precision = tp / (tp + fp) if (tp + fp) > 0 else None
        out[rule] = {
            "applicable":   applicable,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "uncertain":    u,
            "suppress_total": tp + fp,
            "allow_total":    fn + tn,
            "detection_rate": det,
            "false_positive_rate": fpr,
            "precision":     precision,
        }
    return out


def fmt_rate(v):
    return f"{v:.3f}" if v is not None else "n/a"


def fmt_delta(v01, v02):
    if v01 is None or v02 is None:
        return "—"
    d = v02 - v01
    sign = "+" if d > 0 else ""
    return f"{sign}{d:.3f}"


def main():
    print("Loading v0.2 outputs…")
    labels   = load_jsonl(LABELS_V02_PATH)
    verdicts = load_jsonl(VERDICTS_V02_PATH)
    timelines = load_jsonl(TIMELINES_PATH)
    sample = json.loads(SAMPLE_PATH.read_text())

    print("Loading v0.1 report for head-to-head…")
    v01_report = json.loads(V01_REPORT_PATH.read_text())
    v01_per_rule = v01_report["per_rule"]

    per_rule_v02 = per_rule_summary(labels)

    # ── Repeated-failure-loop examples (still surfacing ALLOW-with-partial-match) ──
    rfl_examples = []
    seen_sessions = set()
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

    # ── Per-session concentration ──
    per_session = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for l in labels:
        per_session[l["session_id"]][l["rule"]][l["label"]] += 1

    sampling = {
        "rules_version":    sample["rules_version"],
        "seed":             sample["seed"],
        "cap_per_session":  sample["cap_per_session"],
        "n_sessions":       sample["n_sessions"],
        "n_universe":       sample["n_universe"],
        "n_sampled":        sample["n_sampled"],
    }

    artifact_hashes = {
        "phase2_sample.json":                       file_sha256(SAMPLE_PATH),
        "phase2_belief_timelines.jsonl":            file_sha256(TIMELINES_PATH),
        "phase2_intervention_verdicts_v0_2.jsonl":  file_sha256(VERDICTS_V02_PATH),
        "phase2_labeled_outcomes_v0_2.jsonl":       file_sha256(LABELS_V02_PATH),
    }

    report = {
        "rules_version":    RULES_VERSION,
        "generated_at":     datetime.utcnow().isoformat() + "Z",
        "sampling":         sampling,
        "v01_per_rule":     v01_per_rule,
        "v02_per_rule":     per_rule_v02,
        "rfl_examples_v02": rfl_examples,
        "artifact_sha256":  artifact_hashes,
        "n_sessions_with_any_applicable_turn": len(per_session),
        "amendments_folded": ["A-001", "A-002", "A-003", "A-004", "A-005"],
    }
    REPORT_JSON_PATH.write_text(json.dumps(report, indent=2))
    print(f"Wrote {REPORT_JSON_PATH}")

    # ── Markdown ──
    lines = []
    lines.append("# F-023 Phase 2 — TKOS Log-Replay Measurement Report (v0.2)\n")
    lines.append(f"_Generated: {report['generated_at']}_\n")
    lines.append("**Rules version:** v0.2, locked 2026-05-29.")
    lines.append("**Pre-registration:** [PHASE2_PRE_REGISTRATION_v0.2.md](PHASE2_PRE_REGISTRATION_v0.2.md).")
    lines.append("**Amendments folded (from v0.1):** A-001, A-002, A-003, A-004, A-005 — see [PHASE2_AMENDMENTS_FOR_V02.md](PHASE2_AMENDMENTS_FOR_V02.md).")
    lines.append("**v0.1 report (preserved):** [PHASE2_REPORT.md](PHASE2_REPORT.md).")
    lines.append("**v0.1 artifacts:** unchanged in `data/`.")
    lines.append("")
    lines.append("---\n")
    lines.append("## 1. What changed from v0.1\n")
    lines.append("- **A-001** — Threshold name: `suppressed_threshold` → `intervention_authority_threshold` (value unchanged at 0.7).")
    lines.append("- **A-002** — `stale_deploy_prior` now fires when `user_approval_required` is **active AND weight ≥ 0.7** (v0.1 had the literal inverted reading).")
    lines.append("- **A-003** — `repeated_failure_loop` signature match is now a **disjunction**: (tool ∧ error-Jaccard ≥ 0.5) ∨ (file ∩ ∧ cmd-token ∩) ∨ (shared exception class). Material action remains \"any Edit/Write/MultiEdit\" (refinement deferred to v0.3).")
    lines.append("- **A-004** — `contradicted_fix_prior` applicability requires **context overlap**: touched-file ∨ command-family ∨ validation-context. Incidental unrelated errors are excluded.")
    lines.append("- **A-005** — `stale_pipeline_prior` threshold raised from 20 min to **30 min** (= 1× pipeline_running half-life).")
    lines.append("")
    lines.append("---\n")
    lines.append("## 2. Sampling\n")
    lines.append("v0.2 uses the same sample as v0.1 (seed=20260529, cap=200/session, 20,190 evaluation turns across 164 sessions). The belief timelines are also unchanged because v0.2 did not modify the belief tracker.")
    lines.append("")
    lines.append("---\n")
    lines.append("## 3. Per-rule head-to-head\n")
    lines.append("Truth labels follow §5.2 (unchanged from v0.1): SUPPRESS+problem=TP, SUPPRESS+no problem=FP, ALLOW+problem=FN, ALLOW+no problem=TN, no-lookahead=UNCERTAIN.")
    lines.append("")
    for rule in RULE_ORDER:
        v01 = v01_per_rule.get(rule, {})
        v02 = per_rule_v02[rule]
        lines.append(f"### 3.{RULE_ORDER.index(rule)+1} `{rule}`\n")
        lines.append("| Metric | v0.1 | v0.2 | Δ |")
        lines.append("|---|--:|--:|--:|")
        for k, label in [
            ("applicable",   "Applicable"),
            ("tp",           "TP"),
            ("fp",           "FP"),
            ("fn",           "FN"),
            ("tn",           "TN"),
            ("uncertain",    "UNCERTAIN"),
            ("suppress_total","SUPPRESS total"),
        ]:
            a = v01.get(k, 0)
            b = v02[k]
            lines.append(f"| {label} | {a:,} | {b:,} | {b - a:+,} |")
        lines.append(
            f"| Detection rate | {fmt_rate(v01.get('detection_rate'))} | "
            f"{fmt_rate(v02['detection_rate'])} | "
            f"{fmt_delta(v01.get('detection_rate'), v02['detection_rate'])} |"
        )
        lines.append(
            f"| False-positive rate | {fmt_rate(v01.get('false_positive_rate'))} | "
            f"{fmt_rate(v02['false_positive_rate'])} | "
            f"{fmt_delta(v01.get('false_positive_rate'), v02['false_positive_rate'])} |"
        )
        # Precision was not computed in v0.1 report; include v0.2 only
        lines.append(f"| Precision (v0.2 only) | — | {fmt_rate(v02['precision'])} | — |")
        lines.append("")
    lines.append("---\n")
    lines.append("## 4. Reading the head-to-head (§6.1 compliance)\n")
    lines.append("Per §6.1, this report does **not** claim TKOS improves Claude, does not score F1 vs threshold, does not generalize beyond corpus.\n")
    lines.append("What the v0.2 numbers show:")
    lines.append("")

    rfl_v01 = v01_per_rule["repeated_failure_loop"]
    rfl_v02 = per_rule_v02["repeated_failure_loop"]
    sdp_v01 = v01_per_rule["stale_deploy_prior"]
    sdp_v02 = per_rule_v02["stale_deploy_prior"]
    spp_v01 = v01_per_rule["stale_pipeline_prior"]
    spp_v02 = per_rule_v02["stale_pipeline_prior"]
    cfp_v01 = v01_per_rule["contradicted_fix_prior"]
    cfp_v02 = per_rule_v02["contradicted_fix_prior"]

    lines.append(
        f"- **`repeated_failure_loop`** (A-003): SUPPRESS verdicts unchanged at "
        f"{rfl_v02['suppress_total']} despite loosening the signature predicate to a disjunction "
        f"with Jaccard ≥ 0.5. Applicability stayed at {rfl_v02['applicable']:,}; FN at {rfl_v02['fn']:,}. "
        "This suggests either (i) this corpus genuinely has few 3-in-10-turn repeats with even "
        "loose signature similarity, or (ii) the v0.2 looseness still doesn't cover the way "
        "real loops paraphrase across attempts. Example windows are surfaced in §5; v0.3 "
        "should inspect them before further loosening."
    )
    lines.append(
        f"- **`stale_deploy_prior`** (A-002): inverting the threshold direction still "
        f"produces 0 SUPPRESS across {sdp_v02['applicable']} applicable deploy actions. "
        "This is a structural finding: by the time a deploy action fires, "
        "`user_approval_required` has typically been retired (the user-side approval signal "
        "that triggers the deploy ALSO retires the requirement belief). The rule cannot fire "
        "because the two beliefs almost never co-exist at the deploy moment. The fix may not "
        "be in the rule but in the belief — `user_approval_required` retirement is too eager."
    )
    spp_det_delta = (spp_v02['detection_rate'] or 0) - (spp_v01['detection_rate'] or 0)
    spp_fpr_delta = (spp_v02['false_positive_rate'] or 0) - (spp_v01['false_positive_rate'] or 0)
    lines.append(
        f"- **`stale_pipeline_prior`** (A-005): moving the threshold 20 min → 30 min reduced "
        f"SUPPRESS from {spp_v01['suppress_total']:,} to {spp_v02['suppress_total']:,}. "
        f"Detection rate moved {fmt_delta(spp_v01['detection_rate'], spp_v02['detection_rate'])} "
        f"(from {fmt_rate(spp_v01['detection_rate'])} to {fmt_rate(spp_v02['detection_rate'])}); "
        f"FPR moved {fmt_delta(spp_v01['false_positive_rate'], spp_v02['false_positive_rate'])} "
        f"(from {fmt_rate(spp_v01['false_positive_rate'])} to {fmt_rate(spp_v02['false_positive_rate'])}). "
        "The threshold trade-off is now visible: fewer firings, fewer false positives, but also "
        "fewer real catches. Neither boundary is optimal; the corpus may need an adaptive "
        "threshold tied to per-pipeline expected duration rather than a global constant."
    )
    lines.append(
        f"- **`contradicted_fix_prior`** (A-004): broadened applicability from 0 to "
        f"{cfp_v02['applicable']:,} turns. All applicable turns fire SUPPRESS by rule design "
        "(applicability = trigger). Of those, "
        f"{cfp_v02['tp']:,} are TP and {cfp_v02['fp']:,} are FP "
        f"(precision {fmt_rate(cfp_v02['precision'])}). The 24% precision means three "
        "of four \"contradictions\" are not actually fix-invalidating in the 5-turn window. "
        "The context-overlap predicate (file/cmd/validation) is helpful but not sufficiently "
        "discriminating; v0.3 should add a temporal constraint (the failing turn within N "
        "turns of the fix's birth) and/or weight validation-context evidence more strongly "
        "than incidental same-file errors."
    )
    lines.append("")
    lines.append("---\n")
    lines.append("## 5. `repeated_failure_loop` example windows (v0.2)\n")
    if not rfl_examples:
        lines.append("_No multi-match windows surfaced even with the v0.2 loosened predicate. "
                     "The substrate may not contain 3-in-10-turn-window repeats at this signature level._")
    else:
        for i, ex in enumerate(rfl_examples, 1):
            lines.append(f"**Example {i}** — session `{ex['session_id_hash']}`, turn {ex['turn_idx']}")
            lines.append(f"- matched signature count: {ex['matched_count']}")
            lines.append(f"- verdict: {ex['verdict']}")
            ev = ex["evidence"]
            if "shared_exception_classes" in ev:
                lines.append(f"- shared exception classes: `{ev['shared_exception_classes']}`")
            if "shared_tools" in ev:
                lines.append(f"- shared tools: `{ev['shared_tools']}`")
            lines.append("")
    lines.append("")
    lines.append("---\n")
    lines.append("## 6. What v0.3 needs\n")
    lines.append("Based on this v0.2 measurement, in priority order:")
    lines.append("")
    lines.append("1. **Inspect `repeated_failure_loop` non-firings.** The signature loosening did not move the needle. Either real loops in this corpus look different than the rule expects, or our signature definition still misses how the same error gets reported across retries. Hand-review of 5–10 candidate windows is the next step before further loosening.")
    lines.append("2. **Revisit `user_approval_required` lifecycle, not just the deploy rule.** The 0-SUPPRESS result in v0.2 is structural: the belief retires on the same signal that births deploy_pending. Consider keeping `user_approval_required` alive for one turn after retirement, or splitting it into `approval_pending` (decays) and `approval_observed` (event).")
    lines.append("3. **Add temporal constraint to `contradicted_fix_prior`.** 24% precision suggests the failing turn often isn't actually about the fix. Restrict applicability to failures within N (say 5) turns of the fix's birth.")
    lines.append("4. **Adaptive `stale_pipeline_prior` threshold.** Global threshold trades detection for FPR linearly. A per-pipeline expected-duration prior would let the rule scale to short vs long pipelines.")
    lines.append("5. **Material-action refinement for §3.1.** v0.2 deferred whitespace/comment/identical-patch detection to v0.3. If example windows show genuine no-op edits being miscounted as material, this will become higher priority.")
    lines.append("")
    lines.append("---\n")
    lines.append("## 7. Audit trail\n")
    lines.append("v0.1 artifacts in `data/` are unmodified by this run.")
    lines.append("")
    lines.append("| File | SHA-256 |")
    lines.append("|---|---|")
    for name, h in artifact_hashes.items():
        lines.append(f"| `{name}` | `{h}` |")
    lines.append("")
    REPORT_MD_PATH.write_text("\n".join(lines))
    print(f"Wrote {REPORT_MD_PATH}")


if __name__ == "__main__":
    main()
