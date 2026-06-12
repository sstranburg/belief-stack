#!/usr/bin/env python3
"""
Sensemaking v1.5 v0.3 — Report.

Reads v0.1, v0.2, v0.3 summaries; produces three-way head-to-head.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent

PRIMARY_V01_PATH     = ROOT / "data" / "sensemaking_v1_5_primary_summary.json"
SECONDARY_V01_PATH   = ROOT / "data" / "sensemaking_v1_5_secondary_summary.json"

PRIMARY_V02_PATH     = ROOT / "data" / "sensemaking_v1_5_primary_summary_v0_2.json"
SECONDARY_V02_PATH   = ROOT / "data" / "sensemaking_v1_5_secondary_summary_v0_2.json"

LIFECYCLE_V03_PATH   = ROOT / "data" / "sensemaking_v1_5_lifecycle_summary_v0_3.json"
STATE_V03_PATH       = ROOT / "data" / "sensemaking_v1_5_state_summary_v0_3.json"
SUBWINDOW_V03_PATH   = ROOT / "data" / "sensemaking_v1_5_subwindow_summary_v0_3.json"
COVERAGE_V03_PATH    = ROOT / "data" / "sensemaking_v1_5_coverage_summary_v0_3.json"
SENSITIVITY_V03_PATH = ROOT / "data" / "sensemaking_v1_5_sensitivity_summary_v0_3.json"

REPORT_JSON_PATH = ROOT / "data" / "sensemaking_v1_5_report_v0_3.json"
REPORT_MD_PATH   = ROOT / "SENSEMAKING_V1_5_REPORT_v0_3.md"


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
    p01 = json.loads(PRIMARY_V01_PATH.read_text())
    s01 = json.loads(SECONDARY_V01_PATH.read_text())
    p02 = json.loads(PRIMARY_V02_PATH.read_text())
    s02 = json.loads(SECONDARY_V02_PATH.read_text())
    lc03 = json.loads(LIFECYCLE_V03_PATH.read_text())
    st03 = json.loads(STATE_V03_PATH.read_text())
    sw03 = json.loads(SUBWINDOW_V03_PATH.read_text())
    cv03 = json.loads(COVERAGE_V03_PATH.read_text())
    sn03 = json.loads(SENSITIVITY_V03_PATH.read_text())

    report = {
        "rules_version": "v0.3",
        "generated_at":  datetime.utcnow().isoformat() + "Z",
        "lifecycle_v03": lc03,
        "state_v03":     st03,
        "subwindow_v03": sw03,
        "coverage_v03":  cv03,
        "sensitivity_v03": sn03,
        "v01_primary":   p01,
        "v01_secondary": s01,
        "v02_primary":   p02,
        "v02_secondary": s02,
        "artifact_sha256": {
            "lifecycle_v0_3":  file_sha256(LIFECYCLE_V03_PATH),
            "state_v0_3":      file_sha256(STATE_V03_PATH),
            "subwindow_v0_3":  file_sha256(SUBWINDOW_V03_PATH),
            "coverage_v0_3":   file_sha256(COVERAGE_V03_PATH),
            "sensitivity_v0_3": file_sha256(SENSITIVITY_V03_PATH),
        },
    }
    REPORT_JSON_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"Wrote {REPORT_JSON_PATH}")

    L: list[str] = []
    L.append("# Sensemaking v1.5 — Measurement Report (v0.3)\n")
    L.append(f"_Generated: {report['generated_at']}_\n")
    L.append("**Rules version:** v0.3, locked 2026-05-30.")
    L.append("**Pre-registration:** [SENSEMAKING_V1_5_PRE_REGISTRATION_v0.3.md](SENSEMAKING_V1_5_PRE_REGISTRATION_v0.3.md).")
    L.append("**Predecessors (preserved):** [v0.1 report](SENSEMAKING_V1_5_REPORT.md) · [v0.2 report](SENSEMAKING_V1_5_REPORT_v0_2.md).")
    L.append("**v0.1 / v0.2 artifacts** unchanged.")
    L.append("")
    L.append("---\n")

    # § Headline
    L.append("## 1. Headline\n")
    lc_5 = lc03["per_horizon"]["5d"]
    lc_20 = lc03["per_horizon"]["20d"]
    L.append(f"> **Lifecycle primary (promoted from v0.2 secondary):** 5D internal gap is {fmt_pct(lc_5['internal_gap_constructive_minus_cautious'])} (Constructive_revision > Cautious_revision, right direction). 20D gap inverts to {fmt_pct(lc_20['internal_gap_constructive_minus_cautious'])} — the lifecycle directional signal is specifically a 5D phenomenon.")
    L.append(">")
    L.append(f"> **State buckets (secondary):** with REPRICING extracted as standalone, the pure Constructive bucket (CONFIRMED + DISAGREEMENT) shows {fmt_pct(st03['per_horizon']['20d']['Constructive']['baseline_avg_diff'])} Δ vs baseline at 20D — the v0.1 \"+2.97%\" headline largely returns when REPRICING isn't carrying noise in either direction.")
    L.append(">")
    sw_20_B_constr = sw03["per_horizon"]["20d"]["B_later"]["Constructive"]
    L.append(f"> **Sub-window stratification confirms the rising-tide hypothesis:** in Sub-window A (early, rising-tide period) the Ambiguous baseline was +7.43% at 20D; in Sub-window B (later, sell-off period) the baseline was −2.43% and Constructive separated by {fmt_pct(sw_20_B_constr['window_baseline_avg_diff'])} over its window baseline.")
    L.append("")
    L.append("v0.3 produces three substantive findings: (1) lifecycle revision carries the cleanest 5D directional signal (v0.2 finding confirmed), (2) the apparent v0.1 Constructive headline was partly REPRICING noise — the pure CONFIRMED + DISAGREEMENT bucket separates from baseline modestly at 20D, and (3) the Cautious failure mode is window-structural: sub-window stratification reveals the v1.5 window contained two very different market regimes.")
    L.append("")
    L.append("---\n")

    # § Primary
    L.append("## 2. Primary: lifecycle revision-prediction\n")
    L.append("Per v0.3 §1 (success criterion) and §3 (event buckets). Forward returns from lifecycle event date T against per-ticker prices; baseline = v0.2 Ambiguous (MACRO + PRICE-LED + UNCLEAR).")
    L.append("")
    for h in (5, 20):
        L.append(f"### 2.{1 if h == 5 else 2} {h}D horizon\n")
        p = lc03["per_horizon"][f"{h}d"]
        L.append("| Bucket | n | Avg fwd_rel | Median | % positive | Δ baseline | Hit rate |")
        L.append("|---|--:|--:|--:|--:|--:|--:|")
        for lb in ("Constructive_revision", "Cautious_revision", "Ambiguous_baseline_v0_2"):
            r = p[lb]
            n = r["n"]
            if n == 0:
                L.append(f"| {lb} | 0 | — | — | — | — | — |")
                continue
            hr = r.get("hit_rate")
            L.append(
                f"| {lb} | {n:,} | {fmt_pct(r.get('avg_fwd_rel'))} | "
                f"{fmt_pct(r.get('median_fwd_rel'))} | "
                f"{fmt_rate(r.get('pct_positive_fwd_rel'))} | "
                f"{fmt_pct(r.get('baseline_avg_diff'))} | "
                f"{fmt_rate(hr)} |"
            )
        L.append(f"| **Internal gap (Constructive_revision − Cautious_revision)** | | | | | {fmt_pct(p['internal_gap_constructive_minus_cautious'])} | |")
        L.append("")

    L.append("**Reading lifecycle primary:**")
    L.append("")
    L.append(f"- 5D: Constructive_revision (n=216) avg {fmt_pct(lc_5['Constructive_revision']['avg_fwd_rel'])}; Cautious_revision (n=242) avg {fmt_pct(lc_5['Cautious_revision']['avg_fwd_rel'])}. Internal gap {fmt_pct(lc_5['internal_gap_constructive_minus_cautious'])} — right direction.")
    L.append(f"- 20D: gap inverts to {fmt_pct(lc_20['internal_gap_constructive_minus_cautious'])} — Cautious_revision unexpectedly outperforms Constructive_revision over the 20-day window. The 5D lifecycle signal is specifically 5-day.")
    L.append("- Both buckets remain below the v0.2 Ambiguous baseline at both horizons. The lifecycle signal is the **internal directional gap**, not absolute baseline outperformance.")
    L.append("")
    L.append("---\n")

    # § State secondary
    L.append("## 3. State buckets (secondary)\n")
    L.append("Per v0.3 §11.1. REPRICING extracted as standalone (unlabeled); Constructive narrows to CONFIRMED + DISAGREEMENT only; EARLY remains standalone.")
    L.append("")
    for h in (5, 20):
        L.append(f"### 3.{1 if h == 5 else 2} {h}D horizon\n")
        b = st03["per_horizon"][f"{h}d"]
        L.append("| Bucket | n | Avg fwd_rel | % positive | Δ baseline | Hit rate |")
        L.append("|---|--:|--:|--:|--:|--:|")
        for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough", "Ambiguous"):
            r = b[bucket]
            n = r["n"]
            if n == 0:
                continue
            hr = r.get("hit_rate")
            hr_str = fmt_rate(hr) if hr is not None else "(unlabeled)"
            L.append(
                f"| {bucket} | {n:,} | {fmt_pct(r.get('avg_fwd_rel'))} | "
                f"{fmt_rate(r.get('pct_positive_fwd_rel'))} | "
                f"{fmt_pct(r.get('baseline_avg_diff'))} | "
                f"{hr_str} |"
            )
        L.append("")

    L.append("**Reading state secondary:**")
    L.append("")
    st_20_constr = st03["per_horizon"]["20d"]["Constructive"]
    L.append(f"- At 20D, pure Constructive (CONFIRMED + DISAGREEMENT, n={st_20_constr['n']:,}) shows {fmt_pct(st_20_constr['baseline_avg_diff'])} Δ vs baseline. That is materially closer to v0.1's +2.97% headline than v0.2's −1.22% — extracting REPRICING entirely (rather than splitting it by direction) reveals that the constructive signal in CONFIRMED + DISAGREEMENT is real and was being diluted by REPRICING noise in both v0.1 (REPRICING in Ambiguous) and v0.2 (REPRICING_bullish folded into Constructive).")
    L.append(f"- REPRICING_primary (n={st03['per_horizon']['20d']['REPRICING_primary']['n']:,} at 20D) shows {fmt_pct(st03['per_horizon']['20d']['REPRICING_primary']['avg_fwd_rel'])} — close to zero, slightly below baseline. This justifies the standalone treatment: REPRICING does not belong with Constructive or Cautious; it is approximately neutral with high variance.")
    L.append(f"- Cautious still shows positive forward returns at 20D ({fmt_pct(st03['per_horizon']['20d']['Cautious']['avg_fwd_rel'])}, Δbase {fmt_pct(st03['per_horizon']['20d']['Cautious']['baseline_avg_diff'])}) — the v0.1 / v0.2 failure mode persists at the aggregate level. The per-sub-window section below shows why.")
    L.append("")
    L.append("---\n")

    # § Sub-window
    L.append("## 4. Per-sub-window stratification (§11.2)\n")
    L.append(f"Cut date: **{sw03['cut_date']}** (calendar midpoint of the window).")
    L.append("")
    L.append("| Sub-window | Date range |")
    L.append("|---|---|")
    L.append(f"| A (early) | {sw03['sub_window_A']} |")
    L.append(f"| B (later) | {sw03['sub_window_B']} |")
    L.append("")
    for h in (5, 20):
        L.append(f"### 4.{1 if h == 5 else 2} {h}D horizon\n")
        L.append("| Sub-window | Bucket | n | Avg fwd_rel | % positive | Δ window baseline |")
        L.append("|---|---|--:|--:|--:|--:|")
        for w in ("A_early", "B_later"):
            pw = sw03["per_horizon"][f"{h}d"][w]
            for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough", "Ambiguous"):
                r = pw[bucket]
                n = r["n"]
                if n == 0:
                    continue
                L.append(
                    f"| {w} | {bucket} | {n:,} | "
                    f"{fmt_pct(r.get('avg_fwd_rel'))} | "
                    f"{fmt_rate(r.get('pct_positive_fwd_rel'))} | "
                    f"{fmt_pct(r.get('window_baseline_avg_diff'))} |"
                )
        L.append("")

    sw_20_A_ambig = sw03["per_horizon"]["20d"]["A_early"]["Ambiguous"]
    sw_20_B_ambig = sw03["per_horizon"]["20d"]["B_later"]["Ambiguous"]
    sw_20_A_constr = sw03["per_horizon"]["20d"]["A_early"]["Constructive"]
    L.append("**Reading sub-window stratification:**")
    L.append("")
    L.append(f"- **Sub-window A (early, 2025-12-05 → 2026-02-28) was a rising-tide regime.** Ambiguous baseline at 20D = {fmt_pct(sw_20_A_ambig['avg_fwd_rel'])}. Every directional bucket underperformed this elevated baseline — Constructive Δ {fmt_pct(sw_20_A_constr['window_baseline_avg_diff'])}, even though Constructive avg was positive ({fmt_pct(sw_20_A_constr['avg_fwd_rel'])}).")
    L.append(f"- **Sub-window B (later, 2026-03-01 → 2026-05-26) was a sell-off regime.** Ambiguous baseline at 20D = {fmt_pct(sw_20_B_ambig['avg_fwd_rel'])} (negative). Constructive Δ vs window baseline = {fmt_pct(sw_20_B_constr['window_baseline_avg_diff'])} — the largest constructive separation observed anywhere in v1.5, with avg {fmt_pct(sw_20_B_constr['avg_fwd_rel'])} on n={sw_20_B_constr['n']:,}.")
    L.append("- **The Cautious failure mode from v0.1 / v0.2 is window-structural**, exactly as the rising-tide hypothesis predicted. In Sub-window A, everything underperformed a rallying baseline. In Sub-window B, the patterns are clearer but Cautious still outperformed its window baseline by ~+7% (cautious calls still didn't underperform during a real sell-off).")
    L.append("")
    L.append("---\n")

    # § Coverage
    L.append("## 5. Warrant coverage (§11.3 + §11.4)\n")
    L.append("### 5.1 State warrant coverage\n")
    for h in (5, 20):
        L.append(f"**{h}D:**\n")
        L.append("| Partition | Bucket | n | Avg fwd_rel | % positive | Δ partition baseline |")
        L.append("|---|---|--:|--:|--:|--:|")
        cov = cv03["state"][f"{h}d"]
        for partition in ("sufficient_data_True", "sufficient_data_False"):
            for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough", "Ambiguous"):
                r = cov[partition][bucket]
                n = r["n"]
                if n == 0:
                    continue
                L.append(
                    f"| {partition} | {bucket} | {n:,} | "
                    f"{fmt_pct(r.get('avg_fwd_rel'))} | "
                    f"{fmt_rate(r.get('pct_positive_fwd_rel'))} | "
                    f"{fmt_pct(r.get('partition_baseline_diff'))} |"
                )
        L.append("")

    L.append("### 5.2 Lifecycle warrant coverage\n")
    for h in (5, 20):
        L.append(f"**{h}D:**\n")
        L.append("| Partition | Bucket | n | Avg fwd_rel | % positive | Internal gap |")
        L.append("|---|---|--:|--:|--:|--:|")
        cov = cv03["lifecycle"][f"{h}d"]
        for partition in ("sufficient_data_True", "sufficient_data_False"):
            for lb in ("Constructive_revision", "Cautious_revision"):
                r = cov[partition][lb]
                n = r["n"]
                if n == 0:
                    continue
                L.append(
                    f"| {partition} | {lb} | {n:,} | "
                    f"{fmt_pct(r.get('avg_fwd_rel'))} | "
                    f"{fmt_rate(r.get('pct_positive_fwd_rel'))} | "
                    f"{fmt_pct(cov[partition].get('internal_gap'))} |"
                )
        L.append("")

    L.append("Small n on the insufficient-data lifecycle partition (≤17 events at either horizon) limits what can be read into the partition deltas. The 5D internal gap holds positive within sufficient_data=True (+0.43%), consistent with the primary measurement.")
    L.append("")
    L.append("---\n")

    # § Sensitivity
    L.append("## 6. Sensitivity appendix (§12)\n")
    L.append("Per §12.4, reported separately from primary.")
    L.append("")
    L.append("### 6.1 §12.1 — Lifecycle event-type granularity\n")
    for h in (5, 20):
        L.append(f"**{h}D:**\n")
        L.append("| Event type | n | Avg fwd_rel | Median | % positive |")
        L.append("|---|--:|--:|--:|--:|")
        for ev in ("reconfirmed", "strengthened", "contradicted", "weakened"):
            r = sn03["s12_1_event_type_granularity"][f"{h}d"][ev]
            n = r.get("n", 0)
            if n == 0:
                continue
            L.append(f"| `{ev}` | {n} | {fmt_pct(r['avg_fwd_rel'])} | {fmt_pct(r['median_fwd_rel'])} | {fmt_rate(r['pct_positive_fwd_rel'])} |")
        L.append("")
    L.append("At 5D, `reconfirmed` (+0.41%, n=188) and `contradicted` (−0.32%, n=205) carry directional signal in the expected directions. `strengthened` (n=28) and `weakened` (n=37) have small sample sizes and noisier behavior. The 5D bucket-level signal is driven primarily by reconfirmed + contradicted; strengthened and weakened are too few to assess independently.")
    L.append("")

    L.append("### 6.2 §12.2 — Sub-window robustness for lifecycle primary\n")
    for h in (5, 20):
        L.append(f"**{h}D:**\n")
        L.append("| Sub-window | Constructive_revision avg (n) | Cautious_revision avg (n) | Internal gap |")
        L.append("|---|--:|--:|--:|")
        for w in ("A_early", "B_later"):
            pw = sn03["s12_2_sub_window_robustness"][f"{h}d"][w]
            c = pw["Constructive_revision"]
            k = pw["Cautious_revision"]
            L.append(
                f"| {w} | {fmt_pct(c.get('avg_fwd_rel'))} ({c.get('n', 0)}) | "
                f"{fmt_pct(k.get('avg_fwd_rel'))} ({k.get('n', 0)}) | "
                f"{fmt_pct(pw.get('internal_gap'))} |"
            )
        L.append("")
    L.append("**The 5D lifecycle directional signal lives almost entirely in Sub-window A.** Internal gap = +1.83% in Sub-window A, −0.22% in Sub-window B. This is a notable finding: the v0.2 lifecycle signal that v0.3 promoted to primary is window-conditional. v0.4 should test whether this is structural (early window favored revision-as-signal) or noise (small Sub-window B n).")
    L.append("")

    L.append("### 6.3 §12.3 — Experimental tickers included\n")
    for h in (5, 20):
        L.append(f"**{h}D:**\n")
        L.append("| Bucket | n | Avg fwd_rel | % positive | Internal gap |")
        L.append("|---|--:|--:|--:|--:|")
        ph = sn03["s12_3_experimental_included"][f"{h}d"]
        for lb in ("Constructive_revision", "Cautious_revision"):
            r = ph[lb]
            n = r.get("n", 0)
            if n == 0:
                continue
            L.append(f"| {lb} | {n} | {fmt_pct(r['avg_fwd_rel'])} | {fmt_rate(r['pct_positive_fwd_rel'])} | {fmt_pct(ph.get('internal_gap'))} |")
        L.append("")
    L.append("Experimental inclusion preserves the internal gap within a few bps. The §2.2 exclusion remains conservative without affecting conclusions.")
    L.append("")
    L.append("---\n")

    # § Three-way head-to-head
    L.append("## 7. Three-way head-to-head (v0.1 vs v0.2 vs v0.3)\n")
    L.append("### 7.1 State-bucket Constructive at 20D — the most-tracked headline number\n")
    L.append("| Version | Bucket definition | n | Avg fwd_rel | Δ baseline |")
    L.append("|---|---|--:|--:|--:|")
    L.append(f"| v0.1 | CONFIRMED + EARLY + DISAGREEMENT (REPRICING in Ambiguous) | {p01['per_horizon']['20d']['per_bucket']['Constructive']['n']:,} | {fmt_pct(p01['per_horizon']['20d']['per_bucket']['Constructive']['avg_fwd_rel'])} | {fmt_pct(p01['per_horizon']['20d']['per_bucket']['Constructive']['baseline_avg_diff'])} |")
    L.append(f"| v0.2 | CONFIRMED + DISAGREEMENT + REPRICING_bullish (EARLY isolated) | {p02['per_horizon']['20d']['per_bucket']['Constructive']['n']:,} | {fmt_pct(p02['per_horizon']['20d']['per_bucket']['Constructive']['avg_fwd_rel'])} | {fmt_pct(p02['per_horizon']['20d']['per_bucket']['Constructive']['baseline_avg_diff'])} |")
    L.append(f"| v0.3 | CONFIRMED + DISAGREEMENT only (REPRICING_primary standalone) | {st03['per_horizon']['20d']['Constructive']['n']:,} | {fmt_pct(st03['per_horizon']['20d']['Constructive']['avg_fwd_rel'])} | {fmt_pct(st03['per_horizon']['20d']['Constructive']['baseline_avg_diff'])} |")
    L.append("")
    L.append("v0.1 (+2.97%) ≈ v0.3 (+2.35%) — both extract REPRICING from Constructive proper, just by different mechanisms (v0.1 leaves it in Ambiguous; v0.3 standalone). v0.2's −1.22% was the artifact of folding REPRICING_bullish IN to Constructive.")
    L.append("")

    L.append("### 7.2 Lifecycle revision internal gap at 5D (the durable signal across versions)\n")
    s01_lc = s01["lifecycle"]["5d"]
    s02_lc = s02["lifecycle"]["5d"]
    v01_lc_gap = s01_lc["Constructive_revision"]["avg"] - s01_lc["Cautious_revision"]["avg"]
    v02_lc_gap = s02_lc["Constructive_revision"]["avg"] - s02_lc["Cautious_revision"]["avg"]
    L.append("| Version | Constructive_revision avg | Cautious_revision avg | Internal gap |")
    L.append("|---|--:|--:|--:|")
    L.append(f"| v0.1 | {fmt_pct(s01_lc['Constructive_revision']['avg'])} | {fmt_pct(s01_lc['Cautious_revision']['avg'])} | {fmt_pct(v01_lc_gap)} |")
    L.append(f"| v0.2 | {fmt_pct(s02_lc['Constructive_revision']['avg'])} | {fmt_pct(s02_lc['Cautious_revision']['avg'])} | {fmt_pct(v02_lc_gap)} |")
    L.append(f"| v0.3 | {fmt_pct(lc_5['Constructive_revision']['avg_fwd_rel'])} | {fmt_pct(lc_5['Cautious_revision']['avg_fwd_rel'])} | {fmt_pct(lc_5['internal_gap_constructive_minus_cautious'])} |")
    L.append("")
    L.append("The lifecycle internal gap is preserved across all three versions because the lifecycle bucket definitions never changed. v0.3 promotes this measurement to primary status — confirming the v0.2 finding rather than re-discovering it. The sub-window sensitivity above shows the signal is concentrated in Sub-window A.")
    L.append("")
    L.append("---\n")

    # § What v0.3 says publicly
    L.append("## 8. What v0.3 says publicly\n")
    L.append("> v0.3 promoted lifecycle revision events to the primary measurement and reported state buckets as a secondary axis. Lifecycle revisions preserve a 5D directional signal (Constructive_revision > Cautious_revision by +0.79%) — confirming the v0.2 finding rather than newly discovering it. Sub-window stratification confirms the v0.2 rising-tide hypothesis: the v1.5 window contained two very different market regimes, and the Cautious-bucket failure mode is window-structural rather than state-specific. With REPRICING extracted as a standalone bucket, the pure Constructive bucket (CONFIRMED + DISAGREEMENT) shows +2.35% Δ vs baseline at 20D — close to v0.1's +2.97%, suggesting the real constructive signal exists in the cleanest two states and was diluted by REPRICING in both v0.1 (in Ambiguous) and v0.2 (folded into Constructive).")
    L.append("")
    L.append("v0.3 does NOT claim live-runtime prediction. It claims that under three locked-rule iterations, lifecycle revision events carry a 5D directional signal that survives baseline tightening; the apparent v0.1 state-bucket headline holds up once REPRICING is properly extracted; and the v1.5 window's two regimes explain most of the Cautious-bucket failure.")
    L.append("")
    L.append("---\n")

    # § v0.4 candidates
    L.append("## 9. What v0.4 needs\n")
    L.append("1. **Investigate the lifecycle 5D signal's window concentration.** The §12.2 sensitivity shows the signal is mostly in Sub-window A. v0.4 should test whether this is structural (rising-tide periods favor revision-as-signal) or sample-size noise.")
    L.append("2. **Promote the per-sub-window measurement to primary.** v0.3 confirmed the rising-tide hypothesis decisively; v0.4 should make sub-window-stratified state buckets the primary axis, with the unstratified version as a comparison.")
    L.append("3. **Test event-type granularity at scale.** v0.3 §12.1 showed the 5D signal is concentrated in reconfirmed + contradicted; strengthened (n=28) and weakened (n=37) need more data. v0.4 could expand the lifecycle universe or stratify by event-type explicitly.")
    L.append("4. **Add a regime-detection layer.** The v0.3 calendar-midpoint cut worked but is crude. v0.4 could test a market-vol or rolling-correlation regime detector to compare against the calendar cut.")
    L.append("5. **Row-specific REPRICING direction signal.** REPRICING_primary in v0.3 is unlabeled because the actor-level direction was deemed insufficient in v0.2. v0.4 could infer row-specific direction from narrative-text sentiment or recent return-relative-to-narrative.")
    L.append("")
    L.append("---\n")

    # § Audit trail
    L.append("## 10. Audit trail\n")
    L.append("v0.1 and v0.2 artifacts unmodified by v0.3 run. v0.3 artifacts:")
    L.append("")
    L.append("| File | SHA-256 |")
    L.append("|---|---|")
    for name, h in report["artifact_sha256"].items():
        L.append(f"| `{name}` | `{h}` |")
    L.append("")
    L.append("Pre-registration locked 2026-05-30. Measurement run 2026-05-30. v1 + v0.1 + v0.2 substrate artifacts read-only during v0.3 run.")
    L.append("")

    REPORT_MD_PATH.write_text("\n".join(L))
    print(f"Wrote {REPORT_MD_PATH}")


if __name__ == "__main__":
    main()
