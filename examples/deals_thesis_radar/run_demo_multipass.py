"""
Deals thesis-radar - multi-pass lifecycle demo.

The single-pass demo (`run_demo.py`) proves the pipeline runs. This script
shows the *belief revision* part: hypotheses change over time, and the
lifecycle layer (L3) records how.

Three chronological eras:

    era 1   Feb 1  - Mar 2     "baseline"      hypotheses born
    era 2   Mar 3  - Apr 1     "first revision" born -> strengthened / weakened
    era 3   Apr 2  - Apr 29    "second revision" -> contradicted / promoted / retired / inverted

Two calibration passes:
    pass A:  hypotheses from era1 train     -> calibrate on era2 test
    pass B:  hypotheses from era1+era2 train -> calibrate on era3 test

After pass A every region's lifecycle event is `born`. After pass B the
lifecycle module compares each region's pass-B top1 against its pass-A top1
and emits a real transition: strengthened, weakened, contradicted, retired,
or inverted.

Run:
    python examples/deals_thesis_radar/run_demo_multipass.py
    open examples/deals_thesis_radar/outputs/region_cards_multipass.html
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# Make the demo work even without `pip install -e .`. See run_demo.py.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np

from beliefstack import (
    CalibrationResult,
    Decision,
    DecisionConfig,
    EmpiricalHypothesisGenerator,
    Event,
    LifecycleEvent,
    Region,
    assign_to_regions,
    classify_region,
    fit_regions,
    get_default_embedder,
    load_events_jsonl,
    render_region_cards_html,
    update_lifecycle,
    walk_forward_calibrate,
)
from beliefstack.lifecycle import LifecycleThresholds


# This synthetic demo has ~80 events across 8 regions and 3 eras, so per-region
# per-era counts are tiny. The lifecycle module's defaults (min_n_active=5,
# delta=0.05) are tuned for production-scale data; lowering them here makes the
# state transitions visible on this toy dataset.
DEMO_THRESHOLDS = LifecycleThresholds(
    min_n_active       = 2,
    reopen_n           = 3,
    strengthened_delta = 0.10,
    weakened_delta     = 0.10,
)


HERE     = Path(__file__).resolve().parent
DATA     = HERE / "data" / "synthetic_events.jsonl"
OUT_HTML = HERE / "outputs" / "region_cards_multipass.html"

ERA_2_START = datetime(2026, 3, 3)
ERA_3_START = datetime(2026, 4, 2)


def _calibrate_pass(
    *,
    events:        list[Event],
    region_ids:    list[int],
    regions:       list[Region],
    train_end:     datetime,
    test_start:    datetime,
    test_end:      datetime | None,
    gen:           EmpiricalHypothesisGenerator,
    timestamp:     datetime,
) -> tuple[list, list[CalibrationResult]]:
    """One walk-forward pass. Returns (hypotheses, calibration_results)."""
    train_events = [e for e in events if e.timestamp <  train_end]
    test_window  = [
        e for e in events
        if test_start <= e.timestamp and (test_end is None or e.timestamp < test_end)
    ]
    # Build hypotheses on train only.
    hypotheses = []
    for r in regions:
        h = gen.generate(r, train_events, timestamp=timestamp)
        if h is not None:
            hypotheses.append(h)
    # Calibrate by passing the test slice as "events with timestamp >= test_start".
    # walk_forward_calibrate uses test_start as its split, and any event past
    # test_end isn't in the input either way.
    pass_events     = train_events + test_window
    pass_region_ids = [region_ids[events.index(e)] for e in pass_events]
    cals = walk_forward_calibrate(
        events     = pass_events,
        region_ids = pass_region_ids,
        hypotheses = hypotheses,
        split_at   = test_start,
    )
    return hypotheses, cals


def main() -> None:
    if not DATA.exists():
        raise SystemExit(
            f"data file not found: {DATA}\n"
            f"run: python {HERE / 'generate_synthetic_data.py'}"
        )

    # 1. L0 - load events
    events: list[Event] = load_events_jsonl(DATA)
    print(f"L0  loaded {len(events)} events  "
          f"({events[0].timestamp.date()} -> {events[-1].timestamp.date()})")

    era1 = [e for e in events if e.timestamp <  ERA_2_START]
    era2 = [e for e in events if ERA_2_START <= e.timestamp <  ERA_3_START]
    era3 = [e for e in events if ERA_3_START <= e.timestamp]
    print(f"--  era1={len(era1)}  era2={len(era2)}  era3={len(era3)}")

    # 2. embed once, cluster once (regions are stable across eras)
    embedder = get_default_embedder()
    print(f"--  embedding with {type(embedder).__name__}")
    embeddings = embedder.embed([e.text for e in events])
    K = 8
    regions = fit_regions(embeddings, events, k=K, random_state=0)
    region_ids_arr = assign_to_regions(embeddings, regions)
    region_ids = region_ids_arr.tolist()
    print(f"L1  fit {len(regions)} regions (target k={K})")

    gen = EmpiricalHypothesisGenerator(min_train=2)
    now = datetime.now()

    # 3. PASS A: train=era1, test=era2 -> first hypotheses + calibration
    print("\nPASS A  train=era1, test=era2")
    hyp_a, cal_a = _calibrate_pass(
        events     = events,
        region_ids = region_ids,
        regions    = regions,
        train_end  = ERA_2_START,
        test_start = ERA_2_START,
        test_end   = ERA_3_START,
        gen        = gen,
        timestamp  = now,
    )
    cal_a_by_id = {c.region_id: c for c in cal_a}

    # 4. PASS A lifecycle: every region 'born' (no prior)
    lifecycle_a: list[LifecycleEvent] = []
    for c in cal_a:
        lc = update_lifecycle(
            region_id    = c.region_id,
            timestamp    = ERA_3_START,    # observed at the start of era3
            prior_state  = None,
            prior_top1   = None,
            current_top1 = c.top1_accuracy,
            current_n    = c.n_test,
            thresholds   = DEMO_THRESHOLDS,
        )
        lifecycle_a.append(lc)
    a_state_by_id = {lc.region_id: lc.to_state for lc in lifecycle_a}

    # 5. PASS B: train=era1+era2, test=era3 -> second hypotheses + calibration
    print("PASS B  train=era1+era2, test=era3")
    hyp_b, cal_b = _calibrate_pass(
        events     = events,
        region_ids = region_ids,
        regions    = regions,
        train_end  = ERA_3_START,
        test_start = ERA_3_START,
        test_end   = None,
        gen        = gen,
        timestamp  = now,
    )

    # 6. PASS B lifecycle: compare against pass A
    lifecycle_b: list[LifecycleEvent] = []
    for c in cal_b:
        prior_cal = cal_a_by_id.get(c.region_id)
        lc = update_lifecycle(
            region_id    = c.region_id,
            timestamp    = now,
            prior_state  = a_state_by_id.get(c.region_id),
            prior_top1   = prior_cal.top1_accuracy if prior_cal else None,
            current_top1 = c.top1_accuracy,
            current_n    = c.n_test,
            thresholds   = DEMO_THRESHOLDS,
        )
        lifecycle_b.append(lc)

    # 7. Decisions on the PASS B view
    cfg = DecisionConfig(
        promote_top1       = 0.65,
        monitor_top1       = 0.40,
        recluster_top1     = 0.20,
        promote_min_n_test = 3,
    )
    region_label_by_id = {r.id: r.label for r in regions}
    lc_by_id           = {lc.region_id: lc for lc in lifecycle_b}
    decisions: list[Decision] = []
    for c in cal_b:
        d = classify_region(
            region_label = region_label_by_id.get(c.region_id, f"region_{c.region_id}"),
            calibration  = c,
            lifecycle    = lc_by_id.get(c.region_id),
            config       = cfg,
        )
        decisions.append(d)

    # 8. Console summary of the transitions
    print("\nLifecycle transitions (pass A -> pass B):")
    transition_counts: Counter = Counter()
    for lc in lifecycle_b:
        cal_a_v = cal_a_by_id.get(lc.region_id)
        prior_top1 = cal_a_v.top1_accuracy if cal_a_v else None
        curr_top1  = next(c for c in cal_b if c.region_id == lc.region_id).top1_accuracy
        label      = region_label_by_id.get(lc.region_id, f"r{lc.region_id}")
        prior_s    = f"{prior_top1:.2f}" if prior_top1 is not None else "  na"
        curr_s     = f"{curr_top1:.2f}"  if curr_top1  is not None else "  na"
        print(f"  r{lc.region_id:>2} {label[:32]:<32}  "
              f"top1 {prior_s} -> {curr_s}   "
              f"{lc.from_state or '-':>14}  ->  {lc.to_state}")
        transition_counts[lc.to_state] += 1
    print(f"\nTransition counts: {dict(transition_counts)}")

    # 9. Render
    out = render_region_cards_html(
        title        = "Deals thesis-radar - multi-pass lifecycle (pass A -> pass B)",
        generated_at = now.isoformat(timespec="seconds"),
        regions      = regions,
        hypotheses   = hyp_b,
        calibrations = cal_b,
        decisions    = decisions,
        lifecycle    = lifecycle_b,
        out_path     = OUT_HTML,
    )
    print(f"\nwrote report -> {out}")
    print("each card now shows: pass A top1 -> pass B top1, "
          "and the lifecycle transition driven by that change.")


if __name__ == "__main__":
    main()
