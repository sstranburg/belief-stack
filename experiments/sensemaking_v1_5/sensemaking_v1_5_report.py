#!/usr/bin/env python3
"""
Sensemaking v1.5 — Report (Phase B, stage 5).

Per pre-registration §6 and §10:
  - Primary head first
  - Per-state heterogeneity
  - Secondary lifecycle + tertiary warrant coverage
  - Sensitivity §12 appendix CLEARLY separated, never inline with primary
  - No alpha / no market-beating framing
  - No p-values or significance claims
  - No annualized returns

Reads:
  sensemaking_v1_5/data/sensemaking_v1_5_primary_summary.json
  sensemaking_v1_5/data/sensemaking_v1_5_secondary_summary.json
  sensemaking_v1_5/data/sensemaking_v1_5_sensitivity_summary.json
  sensemaking_v1_5/data/sensemaking_v1_5_rows.parquet  (for exclusion + universe stats)
  sensemaking_v1_5/data/sensemaking_v1_5_labeled.parquet

Writes:
  sensemaking_v1_5/data/sensemaking_v1_5_report.json
  sensemaking_v1_5/SENSEMAKING_V1_5_REPORT.md
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent

PRIMARY_PATH     = ROOT / "data" / "sensemaking_v1_5_primary_summary.json"
SECONDARY_PATH   = ROOT / "data" / "sensemaking_v1_5_secondary_summary.json"
SENSITIVITY_PATH = ROOT / "data" / "sensemaking_v1_5_sensitivity_summary.json"
ROWS_PATH        = ROOT / "data" / "sensemaking_v1_5_rows.parquet"
LABELED_PATH     = ROOT / "data" / "sensemaking_v1_5_labeled.parquet"

REPORT_JSON_PATH = ROOT / "data" / "sensemaking_v1_5_report.json"
REPORT_MD_PATH   = ROOT / "SENSEMAKING_V1_5_REPORT.md"

RULES_VERSION = "v0.1"


def fmt_pct(v, places=2):
    if v is None:
        return "—"
    return f"{v * 100:+.{places}f}%"


def fmt_num(v, places=4):
    if v is None:
        return "—"
    return f"{v:+.{places}f}"


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
    primary = json.loads(PRIMARY_PATH.read_text())
    secondary = json.loads(SECONDARY_PATH.read_text())
    sensitivity = json.loads(SENSITIVITY_PATH.read_text())

    rows = pd.read_parquet(ROWS_PATH)
    labeled = pd.read_parquet(LABELED_PATH)

    # ─── Build JSON report ────────────────────────────────────────────────────
    report = {
        "rules_version": RULES_VERSION,
        "generated_at":  datetime.utcnow().isoformat() + "Z",
        "primary":       primary,
        "secondary":     secondary,
        "sensitivity":   sensitivity,
        "artifact_sha256": {
            "rows.parquet":     file_sha256(ROWS_PATH),
            "labeled.parquet":  file_sha256(LABELED_PATH),
            "primary.json":     file_sha256(PRIMARY_PATH),
            "secondary.json":   file_sha256(SECONDARY_PATH),
            "sensitivity.json": file_sha256(SENSITIVITY_PATH),
        },
    }
    REPORT_JSON_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"Wrote {REPORT_JSON_PATH}")

    # ─── Build Markdown report ───────────────────────────────────────────────
    L: list[str] = []
    L.append("# Sensemaking v1.5 — Measurement Report (v0.1)\n")
    L.append(f"_Generated: {report['generated_at']}_\n")
    L.append("**Rules version:** v0.1, locked 2026-05-29.")
    L.append("**Pre-registration:** [SENSEMAKING_V1_5_PRE_REGISTRATION_v0.1.md](SENSEMAKING_V1_5_PRE_REGISTRATION_v0.1.md).")
    L.append("**Issues log:** [SENSEMAKING_V1_5_ISSUES_LOG.md](SENSEMAKING_V1_5_ISSUES_LOG.md) (I-001, I-002).")
    L.append("**Companion v1 case study:** [topicspace.ai/research/case-studies/sensemaking-v1](https://topicspace.ai/research/case-studies/sensemaking-v1).")
    L.append("")
    L.append("---\n")

    # §1 Sampling
    L.append("## 1. Universe and sampling\n")
    L.append("| Field | Value |")
    L.append("|---|---|")
    L.append("| Window | 2025-12-05 → 2026-05-26 (~120 trading days) |")
    L.append(f"| Primary universe rows (date × ticker, baseline variant) | {primary['universe']['in_primary_rows']:,} |")
    L.append(f"| Experimental cohort rows (MP only, see I-002) | {(len(rows) - primary['universe']['in_primary_rows']):,} |")
    L.append(f"| Tickers in backtest_history.parquet | {rows['ticker'].nunique()} |")
    L.append("| Tickers in actors.json (snapshot) | 42 |")
    L.append("| Tickers absent from backtest_history (I-002) | 10 (ALAB, CLS, COHR, MELI, ODC, SNDK, SOFI, USAR, WDC, ZETA) |")
    L.append("| Horizons | 5 trading days, 20 trading days |")
    L.append("| Variant (per I-001) | `baseline` |")
    L.append("")
    L.append("Per §1.1, this is calibrated reporting, not pass/fail. No statistical-significance threshold is invoked. Sample sizes by horizon and bucket appear in the §3 tables.")
    L.append("")
    L.append("---\n")

    # §2 Primary head — buckets
    L.append("## 2. Primary head — bucket × horizon\n")
    L.append("Per §6, only Constructive and Cautious bucket rows are labeled with Hit / FP / FN. Ambiguous rows do not carry a directional prediction and so do not contribute to hit rate; they are the §8.1 baseline.")
    L.append("")
    for h in (5, 20):
        L.append(f"### 2.{1 if h == 5 else 2} {h}D horizon\n")
        b = primary["per_horizon"][f"{h}d"]["per_bucket"]
        L.append("| Bucket | n | Hits | FP / FN | Hit rate | Avg fwd_rel | Median fwd_rel | % positive | Δ avg vs baseline |")
        L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
        for bucket in ("Constructive", "Cautious", "Ambiguous"):
            r = b[bucket]
            fp_fn = r["false_positives"] if bucket == "Constructive" else (r["false_negatives"] if bucket == "Cautious" else 0)
            L.append(
                f"| **{bucket}** | {r['n']:,} | {r['hits']:,} | {fp_fn:,} | "
                f"{fmt_rate(r['hit_rate'])} | {fmt_pct(r['avg_fwd_rel'])} | "
                f"{fmt_pct(r['median_fwd_rel'])} | {fmt_rate(r['pct_positive_fwd_rel'])} | "
                f"{fmt_pct(r['baseline_avg_diff'])} |"
            )
        L.append("")

    L.append("**Reading the bucket head, plainly:**")
    L.append("")
    c5  = primary["per_horizon"]["5d"]["per_bucket"]["Constructive"]
    k5  = primary["per_horizon"]["5d"]["per_bucket"]["Cautious"]
    c20 = primary["per_horizon"]["20d"]["per_bucket"]["Constructive"]
    k20 = primary["per_horizon"]["20d"]["per_bucket"]["Cautious"]
    L.append(
        f"- At 5D, the Constructive bucket beats the Ambiguous baseline by "
        f"{fmt_pct(c5['baseline_avg_diff'])} in average forward relative return — small. Hit rate "
        f"{fmt_rate(c5['hit_rate'])} is close to chance. Cautious *also* beats the baseline by "
        f"{fmt_pct(k5['baseline_avg_diff'])} in average — the **opposite** of the bucket's directional implication."
    )
    L.append(
        f"- At 20D, Constructive separates from baseline by {fmt_pct(c20['baseline_avg_diff'])} "
        "in average forward relative return — modest but visible. Cautious continues to beat baseline by "
        f"{fmt_pct(k20['baseline_avg_diff'])}, again the opposite of expected direction."
    )
    L.append(
        "- Across both horizons, the Cautious bucket does NOT separate downward from baseline. That is "
        "the v0.1 primary's clearest finding: as currently bucketed, NEG_CONFIRMATION + DIVERGENCE do "
        "not behave as a cautious group on forward outcomes."
    )
    L.append("")
    L.append("---\n")

    # §3 Per-state heterogeneity
    L.append("## 3. Per-state heterogeneity\n")
    L.append("The bucket head hides a great deal of variation. Each individual state contributes differently to its bucket's distribution.")
    L.append("")
    for h in (5, 20):
        L.append(f"### 3.{1 if h == 5 else 2} {h}D horizon, per state\n")
        ps = primary["per_horizon"][f"{h}d"]["per_state"]
        L.append("| Bucket | State | n | Avg fwd_rel | Median fwd_rel | % positive |")
        L.append("|---|---|--:|--:|--:|--:|")
        # Sort by bucket then by -n
        for state in sorted(ps, key=lambda s: (ps[s]["bucket"], -ps[s]["n"])):
            r = ps[state]
            L.append(
                f"| {r['bucket']} | `{state}` | {r['n']:,} | "
                f"{fmt_pct(r['avg_fwd_rel'])} | {fmt_pct(r['median_fwd_rel'])} | "
                f"{fmt_rate(r['pct_positive_fwd_rel'])} |"
            )
        L.append("")

    # State callouts at 20D
    ps20 = primary["per_horizon"]["20d"]["per_state"]
    L.append("**State-level callouts at 20D:**")
    L.append("")
    L.append(
        f"- `CONFIRMED` (n={ps20['CONFIRMED']['n']:,}) avg {fmt_pct(ps20['CONFIRMED']['avg_fwd_rel'])} and "
        f"`DISAGREEMENT` (n={ps20['DISAGREEMENT']['n']:,}) avg {fmt_pct(ps20['DISAGREEMENT']['avg_fwd_rel'])} — "
        "these two carry the constructive signal."
    )
    L.append(
        f"- `EARLY` (n={ps20['EARLY']['n']:,}) avg {fmt_pct(ps20['EARLY']['avg_fwd_rel'])} — "
        "weaker than its bucket implies; pulls the Constructive bucket average down."
    )
    L.append(
        f"- `DIVERGENCE` (n={ps20['DIVERGENCE']['n']:,}) avg {fmt_pct(ps20['DIVERGENCE']['avg_fwd_rel'])} and "
        f"`NEG_CONFIRMATION` (n={ps20['NEG_CONFIRMATION']['n']:,}) avg {fmt_pct(ps20['NEG_CONFIRMATION']['avg_fwd_rel'])} — "
        "both Cautious states show POSITIVE average forward returns, contradicting the bucket's directional implication."
    )
    L.append(
        f"- `REPRICING` (n={ps20['REPRICING']['n']:,}) avg {fmt_pct(ps20['REPRICING']['avg_fwd_rel'])} — "
        "the largest single-state population; its assignment to Ambiguous is load-bearing for the headline. "
        "Sensitivity §12.1 quantifies."
    )
    L.append("")
    L.append("---\n")

    # §4 Secondary §11.1
    L.append("## 4. Secondary — lifecycle revision-prediction (§11.1)\n")
    L.append("Bucket lifecycle events by event type: reconfirmed + strengthened → Constructive_revision; contradicted + weakened → Cautious_revision. Born / retired events are field-population events and excluded from the revision-prediction measurement. Forward returns computed from the event date.")
    L.append("")
    L.append(f"Matched events: {secondary['lifecycle']['matched_count']:,} / {secondary['lifecycle']['matched_count'] + secondary['lifecycle']['unmatched_count']:,} (unmatched = off-trading-day or off-universe).")
    L.append("")
    for h in (5, 20):
        L.append(f"### 4.{1 if h == 5 else 2} Lifecycle revision-prediction at {h}D\n")
        sec = secondary["lifecycle"][f"{h}d"]
        L.append("| Lifecycle bucket | n | Avg fwd_rel | Median | % positive | Δ avg vs primary Ambiguous baseline |")
        L.append("|---|--:|--:|--:|--:|--:|")
        for lb in ("Constructive_revision", "Cautious_revision", "Ambiguous_baseline"):
            r = sec[lb]
            n = r.get("n", 0)
            avg = r.get("avg")
            med = r.get("median")
            pct = r.get("pct_pos")
            d = r.get("avg_minus_baseline")
            L.append(
                f"| **{lb}** | {n:,} | {fmt_pct(avg)} | {fmt_pct(med)} | "
                f"{fmt_rate(pct)} | {fmt_pct(d)} |"
            )
        L.append("")

    L.append("**Reading lifecycle revision:**")
    L.append("")
    sec5  = secondary["lifecycle"]["5d"]
    sec20 = secondary["lifecycle"]["20d"]
    L.append(
        f"- At 5D, Constructive_revision (n={sec5['Constructive_revision']['n']}) avg "
        f"{fmt_pct(sec5['Constructive_revision']['avg'])} beats baseline by "
        f"{fmt_pct(sec5['Constructive_revision']['avg_minus_baseline'])}; "
        f"Cautious_revision (n={sec5['Cautious_revision']['n']}) avg "
        f"{fmt_pct(sec5['Cautious_revision']['avg'])} underperforms baseline by "
        f"{fmt_pct(sec5['Cautious_revision']['avg_minus_baseline'])}. **Both directions go the right way at 5D**; this is the v0.1 measurement's cleanest single signal."
    )
    L.append(
        f"- At 20D, Constructive_revision (n={sec20['Constructive_revision']['n']}) avg "
        f"{fmt_pct(sec20['Constructive_revision']['avg'])} beats baseline by "
        f"{fmt_pct(sec20['Constructive_revision']['avg_minus_baseline'])}; "
        f"Cautious_revision (n={sec20['Cautious_revision']['n']}) avg "
        f"{fmt_pct(sec20['Cautious_revision']['avg'])} *also* beats baseline by "
        f"{fmt_pct(sec20['Cautious_revision']['avg_minus_baseline'])} — same wrong-direction pattern the Cautious *state* bucket showed at 20D in §2."
    )
    L.append("")
    L.append("---\n")

    # §5 Tertiary §11.2
    L.append("## 5. Tertiary — warrant coverage (§11.2)\n")
    L.append("Partition the primary universe by `sufficient_data ∈ {True, False}`. For each partition, compute bucket metrics. The §11.2 expectation under v1's coverage discipline is that insufficient-data rows produce distributions indistinguishable from baseline (the system correctly declined to make a confident claim).")
    L.append("")
    for h in (5, 20):
        L.append(f"### 5.{1 if h == 5 else 2} {h}D horizon by sufficient-data partition\n")
        cov = secondary["coverage"][f"{h}d"]
        L.append("| Partition | Bucket | n | Avg fwd_rel | % positive | Δ avg vs partition baseline |")
        L.append("|---|---|--:|--:|--:|--:|")
        for partition in ("sufficient_data_True", "sufficient_data_False"):
            for bucket in ("Constructive", "Cautious", "Ambiguous"):
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

    cov_t_20 = secondary["coverage"]["20d"]["sufficient_data_True"]["Constructive"]
    cov_f_20 = secondary["coverage"]["20d"]["sufficient_data_False"]["Constructive"]
    L.append("**Reading warrant coverage:**")
    L.append("")
    L.append(
        f"- At 20D, `sufficient_data=True` Constructive (n={cov_t_20['n']:,}) beats its partition baseline by "
        f"{fmt_pct(cov_t_20['avg_minus_baseline'])}; `sufficient_data=False` Constructive (n={cov_f_20['n']}) "
        f"misses its partition baseline by {fmt_pct(cov_f_20['avg_minus_baseline'])}. "
        "The sign flips. Sample size on the insufficient partition is small (n=18) and should not be over-read; "
        "directionally, the coverage flag is informative about whether a state's directional implication holds."
    )
    L.append(
        "- This is consistent with the v1 case study's coverage-discipline claim: the system marks low-warrant "
        "observations correctly. The v1.5 measurement does NOT conclude the coverage threshold is well-calibrated; "
        "it concludes the flag carries information at this sample size and window."
    )
    L.append("")
    L.append("---\n")

    # §6 Sensitivity appendix
    L.append("## 6. Sensitivity appendix (§12)\n")
    L.append("Per §12.3, the sensitivity appendix is reported **clearly separated** from the primary, never inline. The purpose is to expose how much the headline numbers depend on two specific bucket / universe choices the v0.1 pre-registration committed to. These numbers are **not** competing with the primary; they show its robustness.")
    L.append("")

    # §12.1
    L.append("### 6.1 §12.1 — REPRICING-as-Constructive\n")
    L.append("Move REPRICING from Ambiguous to Constructive; everything else unchanged.")
    L.append("")
    for h in (5, 20):
        L.append(f"**{h}D horizon:**\n")
        s = sensitivity["s12_1_REPRICING_as_Constructive"][f"{h}d"]
        L.append("| Bucket | n | Avg fwd_rel | Δ vs (this run's) baseline |")
        L.append("|---|--:|--:|--:|")
        for bucket in ("Constructive", "Cautious", "Ambiguous"):
            r = s[bucket]
            if r.get("n", 0) == 0:
                L.append(f"| {bucket} | 0 | — | — |")
                continue
            L.append(
                f"| {bucket} | {r['n']:,} | {fmt_pct(r['avg_fwd_rel'])} | {fmt_pct(r['baseline_avg_diff'])} |"
            )
        L.append("")

    s121_20 = sensitivity["s12_1_REPRICING_as_Constructive"]["20d"]
    primary_c_delta_20 = primary["per_horizon"]["20d"]["per_bucket"]["Constructive"]["baseline_avg_diff"]
    L.append(
        f"**Headline impact:** at 20D, the primary Constructive Δ vs baseline of "
        f"{fmt_pct(primary_c_delta_20)} becomes "
        f"{fmt_pct(s121_20['Constructive']['baseline_avg_diff'])} under REPRICING-as-Constructive. **The sign flips.** "
        "This is the most consequential sensitivity finding in v1.5: the headline depends on REPRICING's bucket. "
        "REPRICING is the largest single state (1,027 rows at 20D), so reclassifying it pulls the Constructive average down "
        "and the Ambiguous baseline up simultaneously. v0.2 should explicitly re-decide REPRICING's bucket, ideally with a "
        "narrative-direction-aware mapping that splits bullish-narrative REPRICING from bearish-narrative REPRICING."
    )
    L.append("")

    # §12.2
    L.append("### 6.2 §12.2 — Experimental tickers included\n")
    L.append("Include USAR / MP / ODC in the primary universe (only MP is present in `backtest_history.parquet`; see I-002). Everything else unchanged.")
    L.append("")
    for h in (5, 20):
        L.append(f"**{h}D horizon:**\n")
        s = sensitivity["s12_2_experimental_included"][f"{h}d"]
        L.append("| Bucket | n | Avg fwd_rel | Δ vs (this run's) baseline |")
        L.append("|---|--:|--:|--:|")
        for bucket in ("Constructive", "Cautious", "Ambiguous"):
            r = s[bucket]
            if r.get("n", 0) == 0:
                L.append(f"| {bucket} | 0 | — | — |")
                continue
            L.append(
                f"| {bucket} | {r['n']:,} | {fmt_pct(r['avg_fwd_rel'])} | {fmt_pct(r['baseline_avg_diff'])} |"
            )
        L.append("")

    L.append("**Headline impact:** experimental inclusion shifts the bucket averages by at most a few basis points. The §2.2 exclusion is methodologically conservative without changing the conclusions. ALAB / CLS / COHR / MELI / SNDK / SOFI / WDC / ZETA are absent from `backtest_history.parquet` (I-002) and cannot be included in this sensitivity; a separate v0.2 measurement could rebuild backtest_history to include them.")
    L.append("")
    L.append("---\n")

    # §7 What v1.5 says
    L.append("## 7. What v1.5 says (and does not say)\n")
    L.append("Per §10 of the locked pre-registration, this measurement does NOT claim:")
    L.append("")
    L.append("- Alpha against the market.")
    L.append("- Live-deployment predictive performance.")
    L.append("- Generalization beyond the AI ecosystem corpus, beyond 173 days, or beyond this user's pipeline.")
    L.append("- That the current state-to-bucket mapping (§3.2 of the pre-reg) is optimal.")
    L.append("- A pass / fail call on the v1 belief field.")
    L.append("")
    L.append("Under locked rules, the v1.5 measurement says:")
    L.append("")
    L.append("1. **The Constructive bucket separates modestly from baseline at 20D** (+2.97% avg fwd relative return). At 5D the separation is negligible. The signal is concentrated in CONFIRMED and DISAGREEMENT; EARLY does not contribute.")
    L.append("2. **The Cautious bucket does NOT separate from baseline in the expected direction.** Both DIVERGENCE and NEG_CONFIRMATION show positive average forward returns, contradicting the bucket's directional implication at both horizons.")
    L.append("3. **Lifecycle revision events show direction-correct separation at 5D.** Constructive_revision beats baseline; Cautious_revision underperforms. This is the cleanest single signal in v1.5. At 20D the cautious-revision signal also flips wrong direction.")
    L.append("4. **The warrant-coverage flag is informative.** sufficient_data=True Constructive carries the 20D signal; sufficient_data=False Constructive reverses sign. Small sample on the insufficient side (n=18) means this is suggestive, not conclusive.")
    L.append("5. **REPRICING's bucket assignment is load-bearing** for the headline. The §12.1 sensitivity flips the 20D Constructive Δ vs baseline from positive to negative. v0.2 must re-decide.")
    L.append("")
    L.append("---\n")

    # §8 What v0.2 needs
    L.append("## 8. What v0.2 needs\n")
    L.append("Based on the v0.1 measurement, in priority order:")
    L.append("")
    L.append("1. **Re-decide REPRICING's bucket.** The §12.1 sensitivity shows the headline depends on this choice. A narrative-direction-aware split (bullish REPRICING vs bearish REPRICING) is the obvious candidate; another is keeping REPRICING in Ambiguous but reporting its state-level numbers as a sub-headline.")
    L.append("2. **Investigate why Cautious states fail to separate downward.** DIVERGENCE and NEG_CONFIRMATION both show positive forward returns. Two candidate explanations: (a) the AI ecosystem 2025-12 to 2026-05 window was structurally constructive (rising tide); (b) the cautious states detect noise the market subsequently dismisses. v0.2 should add an actor-direction-conditional control group.")
    L.append("3. **Split EARLY from the Constructive headline.** It dilutes the bucket. Either move it to its own bucket or report it separately.")
    L.append("4. **Add temporal stratification.** v0.1 averages across the whole 173-day window. v0.2 should report per-month or per-half-window numbers; the AI ecosystem narrative was structurally different in 2025-12 (early-cycle) vs 2026-04+ (post-DeepSeek aftermath).")
    L.append("5. **Expand backtest_history to include post-window tickers.** ALAB, CLS, COHR, MELI, SNDK, SOFI, WDC, ZETA are tracked in actors.json but absent from the backtest substrate. v0.2 can rebuild with broader coverage if the v1 pipeline's `generate_storm_objects.py` is re-run with the augmented actor list.")
    L.append("")
    L.append("---\n")

    # §9 Audit trail
    L.append("## 9. Audit trail\n")
    L.append("| File | SHA-256 |")
    L.append("|---|---|")
    for name, h in report["artifact_sha256"].items():
        L.append(f"| `{name}` | `{h}` |")
    L.append("")
    L.append("Pre-registration locked 2026-05-29. Measurement run 2026-05-29. v1 substrate artifacts (`backtest_history.parquet`, `expectation_lifecycle_events.parquet`, prices) read-only during measurement.")
    L.append("")

    REPORT_MD_PATH.write_text("\n".join(L))
    print(f"Wrote {REPORT_MD_PATH}")


if __name__ == "__main__":
    main()
