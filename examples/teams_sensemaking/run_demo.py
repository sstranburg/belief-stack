"""
Synthetic-themes demo: end-to-end L0 -> L4 -> region cards.

Substrate: synthetic internal MS Teams chatter across eight organizational
sensemaking themes. LLM-generated, cached to JSONL.

What this shows:
    L0 events (LLM-synthesized Teams snippets)
        -> L1 regions (clusters of similar content; OpenAI embeddings from env)
        -> L2 stateful expectation per region (LLM-generated, lives in
           Hypothesis.extras: narrative / state / score / direction /
           conviction / read; `predicted_class` is the L4 bridge)
        -> L3 lifecycle (born on first pass; transitions in run_demo_multipass)
        -> L4 calibration (walk-forward against held-out outcomes)
        -> decisions (PROMOTE / MONITOR / RECLUSTER / RETIRE / ...)
        -> outputs/region_cards.html

Requires OPENAI_API_KEY in env. The demo fails fast if the key is missing.

Run:
    export OPENAI_API_KEY=sk-...
    pip install -e ".[openai]"
    python examples/synthetic_themes/run_demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# Make the demo work even if `pip install -e .` hasn't been run (e.g. a fresh
# clone where someone wants to read the example before installing). Adds the
# project root to sys.path so `import beliefstack` resolves from source.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Local example helper (sibling module).
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from beliefstack import (
    CalibrationResult,
    Decision,
    DecisionConfig,
    Event,
    Region,
    assign_to_regions,
    classify_region,
    fit_regions,
    load_events_jsonl,
    render_region_cards_html,
    update_lifecycle,
    walk_forward_calibrate,
)
from beliefstack.embeddings import OpenAIEmbedder
from _llm_client import embed_model, require_openai_key
from teams_expectation_generator import LLMTeamsExpectationGenerator


HERE     = Path(__file__).resolve().parent
DATA     = HERE / "data" / "synthetic_events.jsonl"
OUT_HTML = HERE / "outputs" / "region_cards.html"


def main() -> None:
    # Fail fast if the LLM-driven path can't run.
    require_openai_key()

    if not DATA.exists():
        raise SystemExit(
            f"data file not found: {DATA}\n"
            f"run: python {HERE / 'generate_synthetic_data.py'}"
        )

    # 1. L0 - load synthetic events
    events: list[Event] = load_events_jsonl(DATA)
    print(f"L0  loaded {len(events)} events  "
          f"({events[0].timestamp.date()} -> {events[-1].timestamp.date()})")

    # 2. embed via OpenAI embeddings from env
    embedder = OpenAIEmbedder(model=embed_model())
    print(f"--  embedding with OpenAIEmbedder(model={embed_model()})")
    embeddings = embedder.embed([e.text for e in events])

    # 3. L1 - cluster into regions
    K = 8
    regions: list[Region] = fit_regions(embeddings, events, k=K, random_state=0)
    print(f"L1  fit {len(regions)} regions (target k={K})")
    region_ids = assign_to_regions(embeddings, regions).tolist()

    # 4. chronological split for walk-forward
    sorted_ts = sorted(e.timestamp for e in events)
    split_at  = sorted_ts[int(len(sorted_ts) * 0.7)]
    print(f"--  walk-forward split at {split_at.isoformat(timespec='minutes')}")

    train_events = [e for e in events if e.timestamp <  split_at]
    test_events  = [e for e in events if e.timestamp >= split_at]
    print(f"--  train={len(train_events)}  test={len(test_events)}")

    # 5. L2 - LLM-generated stateful expectation per region
    #     Each call emits a multi-dimensional expectation (narrative / state /
    #     score / direction / conviction / read) plus a predicted_class bridge.
    #     The expectation lives in Hypothesis.extras; predicted_class is also
    #     mirrored into Hypothesis.direction for L3/L4 compatibility.
    gen = LLMTeamsExpectationGenerator(min_train=2)
    hypotheses = []
    now = datetime.now()
    print(f"L2  generating expectations via LLM (one call per region) ...")
    for r in regions:
        h = gen.generate(r, train_events, timestamp=now)
        if h is not None:
            hypotheses.append(h)
            ext = h.extras or {}
            print(f"    r{r.id:>2} {r.label[:30]:<30}  "
                  f"state={ext.get('state','?'):<10}  "
                  f"score={ext.get('score','?'):>3}  "
                  f"pred={ext.get('predicted_class','?')}")
    print(f"L2  generated {len(hypotheses)} expectations "
          f"(skipped {len(regions) - len(hypotheses)} with insufficient train support)")

    # 6. L4 - walk-forward calibration
    cals: list[CalibrationResult] = walk_forward_calibrate(
        events     = events,
        region_ids = region_ids,
        hypotheses = hypotheses,
        split_at   = split_at,
    )
    n_scored = sum(1 for c in cals if c.top1_accuracy is not None)
    print(f"L4  calibrated {len(cals)} regions ({n_scored} with labeled test data)")

    # 7. L3 - lifecycle (first observation -> 'born' for every region)
    lifecycle_events = []
    for c in cals:
        lc = update_lifecycle(
            region_id     = c.region_id,
            timestamp     = now,
            prior_state   = None,
            prior_top1    = None,
            current_top1  = c.top1_accuracy,
            current_n     = c.n_test,
        )
        lifecycle_events.append(lc)
    print(f"L3  emitted {len(lifecycle_events)} lifecycle events (all 'born' on first pass)")

    # 8. decisions
    cfg = DecisionConfig(
        promote_top1       = 0.65,
        monitor_top1       = 0.40,
        recluster_top1     = 0.20,
        promote_min_n_test = 4,
    )
    region_label_by_id = {r.id: r.label for r in regions}
    lifecycle_by_id    = {lc.region_id: lc for lc in lifecycle_events}
    decisions: list[Decision] = []
    for c in cals:
        d = classify_region(
            region_label = region_label_by_id.get(c.region_id, f"region_{c.region_id}"),
            calibration  = c,
            lifecycle    = lifecycle_by_id.get(c.region_id),
            config       = cfg,
        )
        decisions.append(d)

    # Quick text summary to console
    print("\nDecisions:")
    for d in decisions:
        cal = next(c for c in cals if c.region_id == d.region_id)
        label = region_label_by_id.get(d.region_id, f"r{d.region_id}")
        top1  = "  na" if cal.top1_accuracy is None else f"{cal.top1_accuracy:.2f}"
        print(f"  r{d.region_id:>2} {label[:34]:<34}  top1={top1}  n={cal.n_test:>2}  "
              f"-> {d.decision_class}")

    # 9. render the region-card report
    out = render_region_cards_html(
        title        = "Synthetic themes - L0 to L4 demo",
        generated_at = now.isoformat(timespec="seconds"),
        regions      = regions,
        hypotheses   = hypotheses,
        calibrations = cals,
        decisions    = decisions,
        lifecycle    = lifecycle_events,
        out_path     = OUT_HTML,
    )
    print(f"\nwrote report -> {out}")
    print("open it in a browser to review the region cards.")


if __name__ == "__main__":
    main()
