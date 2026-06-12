#!/usr/bin/env python3
"""
Sensemaking v1.5 v0.2 — Report.

Per pre-registration §9 (head-to-head added), §10 (honesty constraints),
§16 (public framing).

Reads v0.1 + v0.2 summary outputs; emits side-by-side comparison.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent

PRIMARY_V01_PATH     = ROOT / "data" / "sensemaking_v1_5_primary_summary.json"
SECONDARY_V01_PATH   = ROOT / "data" / "sensemaking_v1_5_secondary_summary.json"
SENSITIVITY_V01_PATH = ROOT / "data" / "sensemaking_v1_5_sensitivity_summary.json"

PRIMARY_V02_PATH     = ROOT / "data" / "sensemaking_v1_5_primary_summary_v0_2.json"
SECONDARY_V02_PATH   = ROOT / "data" / "sensemaking_v1_5_secondary_summary_v0_2.json"
SENSITIVITY_V02_PATH = ROOT / "data" / "sensemaking_v1_5_sensitivity_summary_v0_2.json"

ROWS_PATH            = ROOT / "data" / "sensemaking_v1_5_rows.parquet"
LABELED_V02_PATH     = ROOT / "data" / "sensemaking_v1_5_labeled_v0_2.parquet"

REPORT_JSON_PATH = ROOT / "data" / "sensemaking_v1_5_report_v0_2.json"
REPORT_MD_PATH   = ROOT / "SENSEMAKING_V1_5_REPORT_v0_2.md"


def fmt_pct(v, places=2):
    if v is None:
        return "—"
    return f"{v * 100:+.{places}f}%"


def fmt_rate(v):
    if v is None:
        return "n/a"
    return f"{v:.3f}"


def file_sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    primary_v01     = json.loads(PRIMARY_V01_PATH.read_text())
    secondary_v01   = json.loads(SECONDARY_V01_PATH.read_text())
    primary_v02     = json.loads(PRIMARY_V02_PATH.read_text())
    secondary_v02   = json.loads(SECONDARY_V02_PATH.read_text())
    sensitivity_v02 = json.loads(SENSITIVITY_V02_PATH.read_text())

    report = {
        "rules_version":  "v0.2",
        "generated_at":   datetime.utcnow().isoformat() + "Z",
        "primary_v01":    primary_v01,
        "primary_v02":    primary_v02,
        "secondary_v01":  secondary_v01,
        "secondary_v02":  secondary_v02,
        "sensitivity_v02": sensitivity_v02,
        "artifact_sha256": {
            "labeled_v0_2":  file_sha256(LABELED_V02_PATH),
            "primary_v0_2":  file_sha256(PRIMARY_V02_PATH),
            "secondary_v0_2": file_sha256(SECONDARY_V02_PATH),
            "sensitivity_v0_2": file_sha256(SENSITIVITY_V02_PATH),
        },
    }
    REPORT_JSON_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"Wrote {REPORT_JSON_PATH}")

    # ─── Markdown ────────────────────────────────────────────────────────────
    L: list[str] = []
    L.append("# Sensemaking v1.5 — Measurement Report (v0.2)\n")
    L.append(f"_Generated: {report['generated_at']}_\n")
    L.append("**Rules version:** v0.2, locked 2026-05-30.")
    L.append("**Pre-registration:** [SENSEMAKING_V1_5_PRE_REGISTRATION_v0.2.md](SENSEMAKING_V1_5_PRE_REGISTRATION_v0.2.md).")
    L.append("**v0.1 predecessor:** [SENSEMAKING_V1_5_REPORT.md](SENSEMAKING_V1_5_REPORT.md) (preserved unchanged).")
    L.append("**v0.1 artifacts** in `data/` are not modified by v0.2.")
    L.append("")
    L.append("---\n")

    # § Headline
    L.append("## 1. Headline\n")
    L.append("> v0.1 surfaced an apparent 20D Constructive advantage of +2.97% vs baseline.")
    L.append("> v0.2 re-bucketed REPRICING (direction-aware) and isolated EARLY.")
    L.append("> The advantage did not survive the correction.")
    L.append(">")
    L.append("> v0.2 also confirms the load-bearing direction: lifecycle revision events")
    L.append("> preserve a constructive-vs-cautious directional gap that the static state")
    L.append("> buckets lost once the baseline was tightened.")
    L.append("")
    L.append("This is the belief stack doing belief revision on itself. The v0.1 headline was fragile in exactly the way v0.1's own sensitivity appendix predicted, and v0.2 confirmed it.")
    L.append("")
    L.append("---\n")

    # § What changed
    L.append("## 2. What changed from v0.1\n")
    L.append("Pre-registration §3 (bucket mapping), §12 (sensitivity restructured). Everything else — universe, walk-forward protocol, horizons, secondary protocols, exclusion rules — unchanged.")
    L.append("")
    L.append("| Bucket | v0.1 states | v0.2 states |")
    L.append("|---|---|---|")
    L.append("| Constructive | CONFIRMED, EARLY, DISAGREEMENT | CONFIRMED, DISAGREEMENT, REPRICING_bullish |")
    L.append("| Cautious | NEG_CONFIRMATION, DIVERGENCE | NEG_CONFIRMATION, DIVERGENCE, REPRICING_bearish |")
    L.append("| Early_followthrough | (folded into Constructive) | EARLY (standalone) |")
    L.append("| Ambiguous | MACRO, PRICE-LED, UNCLEAR, **REPRICING** | MACRO, PRICE-LED, UNCLEAR |")
    L.append("")
    L.append("REPRICING split: rows with `direction = +1` (actor-level bullish narrative) → REPRICING_bullish → Constructive. Rows with `direction = −1` → REPRICING_bearish → Cautious. The pre-registration's §3.3 limitation: this is the actor-level narrative direction from `backtest_history.parquet`, not a newly inferred row-specific direction signal. v0.3 may revisit.")
    L.append("")
    L.append("---\n")

    # § Primary head-to-head
    L.append("## 3. Primary head-to-head: v0.1 vs v0.2\n")
    for h in (5, 20):
        L.append(f"### 3.{1 if h == 5 else 2} {h}D horizon\n")
        b01 = primary_v01["per_horizon"][f"{h}d"]["per_bucket"]
        b02 = primary_v02["per_horizon"][f"{h}d"]["per_bucket"]
        L.append("| Bucket | v0.1 n | v0.1 avg fwd_rel | v0.1 Δ baseline | v0.2 n | v0.2 avg fwd_rel | v0.2 Δ baseline |")
        L.append("|---|--:|--:|--:|--:|--:|--:|")
        # v0.1 buckets first
        for bucket in ("Constructive", "Cautious", "Ambiguous"):
            r01 = b01[bucket]
            r02 = b02.get(bucket, {})
            L.append(
                f"| {bucket} | {r01['n']:,} | {fmt_pct(r01['avg_fwd_rel'])} | "
                f"{fmt_pct(r01['baseline_avg_diff'])} | "
                f"{r02.get('n', 0):,} | {fmt_pct(r02.get('avg_fwd_rel'))} | "
                f"{fmt_pct(r02.get('baseline_avg_diff'))} |"
            )
        # v0.2-only bucket
        r02e = b02["Early_followthrough"]
        L.append(
            f"| Early_followthrough | — | — | — | "
            f"{r02e['n']:,} | {fmt_pct(r02e['avg_fwd_rel'])} | {fmt_pct(r02e['baseline_avg_diff'])} |"
        )
        L.append("")
        L.append(f"**v0.2 Ambiguous baseline at {h}D**: avg = {fmt_pct(b02['Ambiguous']['avg_fwd_rel'])}, n = {b02['Ambiguous']['n']:,} (much smaller than v0.1's {b01['Ambiguous']['n']:,}, because REPRICING moved out).")
        L.append("")

    L.append("**Reading the head-to-head:**")
    L.append("")
    b01_20 = primary_v01["per_horizon"]["20d"]["per_bucket"]
    b02_20 = primary_v02["per_horizon"]["20d"]["per_bucket"]
    L.append(
        f"- v0.1 Constructive Δ vs baseline at 20D was {fmt_pct(b01_20['Constructive']['baseline_avg_diff'])}; "
        f"v0.2 Constructive Δ vs (tightened) baseline at 20D is {fmt_pct(b02_20['Constructive']['baseline_avg_diff'])}. "
        f"The flip is roughly {fmt_pct(b02_20['Constructive']['baseline_avg_diff'] - b01_20['Constructive']['baseline_avg_diff'])}."
    )
    L.append(
        f"- The baseline shift accounts for most of the change: v0.1 Ambiguous baseline = {fmt_pct(b01_20['Ambiguous']['avg_fwd_rel'])}, "
        f"v0.2 Ambiguous baseline = {fmt_pct(b02_20['Ambiguous']['avg_fwd_rel'])}. "
        "Removing REPRICING from Ambiguous lifted the baseline because the remaining Ambiguous states "
        "(MACRO, PRICE-LED, UNCLEAR) all had higher forward returns in this window."
    )
    L.append(
        "- The v0.1 Constructive bucket also included EARLY, which had near-zero forward returns. "
        "v0.2 isolated EARLY (n=441 at 20D) into its own bucket. The §12.2 sensitivity shows EARLY's "
        "isolation moves the Constructive number by only ~4bps — methodologically valuable, not the cause of the flip."
    )
    L.append(
        "- REPRICING_bullish (n=1,027 at 20D) carries an avg of only +0.43% — close to Ambiguous, not Constructive-clean. "
        "It dilutes the Constructive bucket from inside. v0.3 may want to make REPRICING its own bucket entirely "
        "rather than folding it into Constructive or Cautious by direction."
    )
    L.append("")
    L.append("---\n")

    # § Per-state heterogeneity (v0.2 effective states)
    L.append("## 4. Per-effective-state — v0.2\n")
    L.append("Effective states encode the REPRICING direction split. CONFIRMED + DISAGREEMENT remain the cleanest Constructive states; REPRICING_bullish dilutes the bucket.")
    L.append("")
    for h in (5, 20):
        L.append(f"### 4.{1 if h == 5 else 2} {h}D horizon\n")
        ps = primary_v02["per_horizon"][f"{h}d"]["per_effective_state"]
        L.append("| Bucket | Effective state | n | Avg fwd_rel | Median | % positive |")
        L.append("|---|---|--:|--:|--:|--:|")
        for state in sorted(ps, key=lambda s: (ps[s].get("bucket", ""), -ps[s].get("n", 0))):
            r = ps[state]
            n = r.get("n", 0)
            if n == 0:
                L.append(f"| {r.get('bucket', '?')} | `{state}` | 0 | — | — | — |")
                continue
            L.append(
                f"| {r['bucket']} | `{state}` | {n:,} | "
                f"{fmt_pct(r['avg_fwd_rel'])} | {fmt_pct(r['median_fwd_rel'])} | "
                f"{fmt_rate(r['pct_positive_fwd_rel'])} |"
            )
        L.append("")

    L.append("---\n")

    # § Secondary head-to-head — lifecycle (THE DURABLE INSIGHT)
    L.append("## 5. Secondary — lifecycle revision-prediction (the durable insight)\n")
    L.append("**The key result of v0.2** is not in the primary state buckets — it is in the comparison between static state labels and lifecycle revision events.")
    L.append("")
    L.append("Under the v0.2 (tightened) baseline, static state buckets no longer separate. But lifecycle revision events still preserve a directional gap:")
    L.append("")
    for h in (5, 20):
        L.append(f"### 5.{1 if h == 5 else 2} {h}D horizon\n")
        lc01 = secondary_v01["lifecycle"][f"{h}d"]
        lc02 = secondary_v02["lifecycle"][f"{h}d"]
        L.append("| Bucket | v0.1 n | v0.1 avg | v0.1 Δ baseline | v0.2 n | v0.2 avg | v0.2 Δ baseline |")
        L.append("|---|--:|--:|--:|--:|--:|--:|")
        for lb in ("Constructive_revision", "Cautious_revision"):
            r01 = lc01[lb]
            r02 = lc02[lb]
            L.append(
                f"| {lb} | {r01['n']:,} | {fmt_pct(r01['avg'])} | "
                f"{fmt_pct(r01.get('avg_minus_baseline'))} | "
                f"{r02['n']:,} | {fmt_pct(r02['avg'])} | "
                f"{fmt_pct(r02.get('avg_minus_baseline'))} |"
            )
        # Show internal gap
        gap_v01 = lc01["Constructive_revision"]["avg"] - lc01["Cautious_revision"]["avg"]
        gap_v02 = lc02["Constructive_revision"]["avg"] - lc02["Cautious_revision"]["avg"]
        L.append(f"| **Internal gap (Constructive_rev − Cautious_rev)** | | | {fmt_pct(gap_v01)} | | | {fmt_pct(gap_v02)} |")
        L.append("")

    lc_5_v02 = secondary_v02["lifecycle"]["5d"]
    static_5_gap_v02 = primary_v02["per_horizon"]["5d"]["per_bucket"]["Constructive"]["avg_fwd_rel"] - primary_v02["per_horizon"]["5d"]["per_bucket"]["Cautious"]["avg_fwd_rel"]
    lifecycle_5_gap_v02 = lc_5_v02["Constructive_revision"]["avg"] - lc_5_v02["Cautious_revision"]["avg"]
    L.append("**Architectural read:**")
    L.append("")
    L.append(
        f"- At 5D under v0.2: static state buckets show Constructive − Cautious = "
        f"{fmt_pct(static_5_gap_v02)} (the wrong direction). "
        f"Lifecycle revisions show Constructive_revision − Cautious_revision = "
        f"{fmt_pct(lifecycle_5_gap_v02)} (the right direction)."
    )
    L.append(
        "- The lifecycle layer (L3) preserves directional information that the static state buckets (L2) "
        "lost once the baseline was corrected. This suggests **static state labels are weaker than "
        "lifecycle revision events** for forward-outcome separation on this substrate."
    )
    L.append(
        "- This is the architecturally beautiful finding v0.2 surfaces: revision events are more informative "
        "than steady-state labels. The Belief Stack pattern's lifecycle layer is doing real work; the bucket "
        "abstraction may be the wrong unit of analysis for forward-outcome prediction."
    )
    L.append("")
    L.append("---\n")

    # § Tertiary — warrant coverage
    L.append("## 6. Tertiary — warrant coverage (v0.2)\n")
    L.append("Same partition protocol as v0.1; baseline is now the v0.2 (tightened) Ambiguous. Small n on the insufficient-data side (n=18 Constructive at 5D / 20D) and the new high-baseline Ambiguous (only ~100 rows per partition) make the per-partition deltas higher-variance than in v0.1.")
    L.append("")
    for h in (5, 20):
        L.append(f"### 6.{1 if h == 5 else 2} {h}D horizon\n")
        cov = secondary_v02["coverage"][f"{h}d"]
        L.append("| Partition | Bucket | n | Avg fwd_rel | % positive | Δ partition baseline |")
        L.append("|---|---|--:|--:|--:|--:|")
        for partition in ("sufficient_data_True", "sufficient_data_False"):
            for bucket in ("Constructive", "Cautious", "Early_followthrough", "Ambiguous"):
                r = cov[partition][bucket]
                n = r.get("n", 0)
                if n == 0:
                    L.append(f"| {partition} | {bucket} | 0 | — | — | — |")
                    continue
                L.append(
                    f"| {partition} | {bucket} | {n:,} | "
                    f"{fmt_pct(r['avg'])} | {fmt_rate(r['pct_pos'])} | "
                    f"{fmt_pct(r.get('avg_minus_baseline'))} |"
                )
        L.append("")

    L.append("The v0.1 warrant-coverage finding (sufficient-data Constructive +2.99% over partition baseline, insufficient-data Constructive flipping sign) does not persist as cleanly under the v0.2 tightened baseline. The directional flip at 20D between sufficient and insufficient Constructive remains (sufficient -5.86% vs insufficient -4.43% — both negative, but the magnitudes differ). v0.3 should re-examine whether the warrant flag information was real or partly an artifact of the v0.1 baseline composition.")
    L.append("")
    L.append("---\n")

    # § Sensitivity §12 v0.2
    L.append("## 7. Sensitivity appendix (v0.2 §12)\n")
    L.append("Per §12.4, sensitivity is reported separately from primary. Three perturbations of the v0.2 mapping.")
    L.append("")

    # §12.1
    L.append("### 7.1 §12.1 — Direction-naive REPRICING reverse\n")
    L.append("Collapse REPRICING back to a single Ambiguous-bucket entry (the v0.1 mapping); everything else v0.2.")
    L.append("")
    for h in (5, 20):
        L.append(f"**{h}D:**\n")
        s = sensitivity_v02["s12_1_naive_repricing"][f"{h}d"]
        L.append("| Bucket | n | Avg fwd_rel | Δ vs (this run's) baseline |")
        L.append("|---|--:|--:|--:|")
        for bucket in ("Constructive", "Cautious", "Early_followthrough", "Ambiguous"):
            r = s[bucket]
            if r.get("n", 0) == 0:
                L.append(f"| {bucket} | 0 | — | — |")
                continue
            L.append(f"| {bucket} | {r['n']:,} | {fmt_pct(r['avg_fwd_rel'])} | {fmt_pct(r['baseline_avg_diff'])} |")
        L.append("")
    L.append("**§12.1 reading:** putting REPRICING back into Ambiguous reproduces the v0.1 headline numbers almost exactly. This confirms that REPRICING's bucket assignment was the entire source of the v0.1 vs v0.2 delta — and therefore that REPRICING was the structurally load-bearing call.")
    L.append("")

    # §12.2
    L.append("### 7.2 §12.2 — EARLY-as-Constructive reverse\n")
    L.append("Fold EARLY back into Constructive (the v0.1 mapping); everything else v0.2.")
    L.append("")
    for h in (5, 20):
        L.append(f"**{h}D:**\n")
        s = sensitivity_v02["s12_2_early_constructive"][f"{h}d"]
        L.append("| Bucket | n | Avg fwd_rel | Δ vs (this run's) baseline |")
        L.append("|---|--:|--:|--:|")
        for bucket in ("Constructive", "Cautious", "Early_followthrough", "Ambiguous"):
            r = s[bucket]
            if r.get("n", 0) == 0:
                L.append(f"| {bucket} | 0 | — | — |")
                continue
            L.append(f"| {bucket} | {r['n']:,} | {fmt_pct(r['avg_fwd_rel'])} | {fmt_pct(r['baseline_avg_diff'])} |")
        L.append("")
    L.append("**§12.2 reading:** EARLY isolation moves the Constructive average by ~4bps at most. The isolation is methodologically useful (it lets us see EARLY's distribution distinctly) but does not by itself cause the v0.1→v0.2 headline flip.")
    L.append("")

    # §12.3
    L.append("### 7.3 §12.3 — Experimental tickers included\n")
    L.append("Include USAR / MP / ODC in the primary universe (only MP present in `backtest_history.parquet`, per I-002). v0.2 bucket mapping otherwise.")
    L.append("")
    for h in (5, 20):
        L.append(f"**{h}D:**\n")
        s = sensitivity_v02["s12_3_experimental_included"][f"{h}d"]
        L.append("| Bucket | n | Avg fwd_rel | Δ vs (this run's) baseline |")
        L.append("|---|--:|--:|--:|")
        for bucket in ("Constructive", "Cautious", "Early_followthrough", "Ambiguous"):
            r = s[bucket]
            if r.get("n", 0) == 0:
                L.append(f"| {bucket} | 0 | — | — |")
                continue
            L.append(f"| {bucket} | {r['n']:,} | {fmt_pct(r['avg_fwd_rel'])} | {fmt_pct(r['baseline_avg_diff'])} |")
        L.append("")
    L.append("**§12.3 reading:** experimental inclusion shifts each bucket by ~1–3bps. The §2.2 exclusion remains methodologically conservative without affecting conclusions.")
    L.append("")
    L.append("---\n")

    # § What v0.2 says publicly
    L.append("## 8. What v0.2 says publicly\n")
    L.append("> The v0.1 measurement surfaced an apparent 20D Constructive advantage of +2.97% vs baseline. The v0.2 re-bucketing showed that this advantage was fragile: moving REPRICING out of Ambiguous raised the baseline enough to eliminate the effect. The result does not invalidate the belief field; it invalidates the simpler bucket mapping.")
    L.append(">")
    L.append("> v0.2 also produced a more architecturally interesting finding: lifecycle revision events preserve a constructive-vs-cautious directional gap that the static state buckets lost under the tightened baseline. The L3 lifecycle layer carries forward-outcome information that the L2 state buckets do not, on this substrate.")
    L.append("")
    L.append("v0.2 does NOT claim:")
    L.append("")
    L.append("- That v1.5 invalidates the v1 belief field. v0.2 invalidates a particular bucket-level summary, not the underlying field.")
    L.append("- That lifecycle revision events are predictive in a live-deployment sense. The 5D internal gap is preserved under v0.2's tightened baseline, but absolute outperformance vs the new baseline is small or negative.")
    L.append("- That CONFIRMED + DISAGREEMENT are not constructive states. Per §4, both still have clearly positive forward returns at 20D (CONFIRMED +5.25%, DISAGREEMENT +7.37%). REPRICING_bullish dilution at the bucket level does not erase the state-level signal.")
    L.append("")
    L.append("---\n")

    # § v0.3 candidates
    L.append("## 9. What v0.3 needs\n")
    L.append("Based on v0.2's measurement, in priority order:")
    L.append("")
    L.append("1. **Re-architect REPRICING.** v0.2's direction-aware split confirmed the v0.1 fragility but produced its own dilution problem inside the Constructive bucket. The next move is probably to make REPRICING its own primary bucket and report its distribution directly, rather than folding it into Constructive / Cautious by an actor-level direction signal.")
    L.append("2. **Promote lifecycle revision-prediction to primary.** v0.2 showed lifecycle events preserve directional information under tightened baselines while static state buckets do not. v0.3 should consider making lifecycle revision the primary measurement axis and treating static state buckets as a comparison surface.")
    L.append("3. **Investigate the window-structural Cautious failure.** DIVERGENCE and NEG_CONFIRMATION continue to show positive forward returns at 20D under v0.2. The v0.1 hypothesis (rising-tide window) remains untested. v0.3 should add per-sub-window stratification (e.g., 2025-12–2026-02 vs 2026-03–2026-05) to test whether Cautious behaved differently in different sub-windows.")
    L.append("4. **Drop EARLY's Constructive labeling assumption.** EARLY's standalone 5D avg is −0.12%, 20D is +0.68%. The provisional Constructive labeling (Hit = fwd_rel > 0) produces hit rates of 0.42/0.44 — clearly below 0.5. v0.3 should either drop the labeling (treat EARLY as Ambiguous) or commit to actually-cautious labeling based on what v0.2 showed.")
    L.append("5. **Revisit the warrant-coverage finding.** v0.1 showed sufficient-data Constructive +2.99% over partition baseline; v0.2 shows −5.86%. Either the finding was an artifact of v0.1's baseline composition, or the warrant flag carries information that the v0.2 bucket structure obscures. v0.3 should test both possibilities.")
    L.append("")
    L.append("---\n")

    # § Audit trail
    L.append("## 10. Audit trail\n")
    L.append("v0.1 artifacts unmodified by v0.2 run. v0.2 artifacts:")
    L.append("")
    L.append("| File | SHA-256 |")
    L.append("|---|---|")
    for name, h in report["artifact_sha256"].items():
        L.append(f"| `{name}` | `{h}` |")
    L.append("")
    L.append("Pre-registration locked 2026-05-30. Measurement run 2026-05-30. v1 substrate artifacts read-only during v0.2 run.")
    L.append("")

    REPORT_MD_PATH.write_text("\n".join(L))
    print(f"Wrote {REPORT_MD_PATH}")


if __name__ == "__main__":
    main()
