# Belief Stack

**A small, living summary of what's currently true — so an LLM agent doesn't have to re-read its whole history every time it makes a decision.**

> Agents shouldn't have to reconstruct the current state of the world from raw history every time they plan.

---

## The problem

A long-running agent — a coding assistant, a support agent, a workflow bot — makes decisions over hundreds or thousands of turns. At each step it has to know things like: *Did the test suite pass? Has the user approved this? Did the last fix actually work, or is it still pending?*

Most systems answer those questions the same way every time: **stuff the recent raw history back into the prompt and make the model re-derive the current state from scratch.** That's expensive (you re-pay for thousands of tokens every turn), slow (the model reprocesses all of it), and error-prone (the model misreads stale logs and acts on a state that's no longer true — claiming "done" when validation was superseded, acting before approval, retrying a fix that already failed).

We call that the **reconstruction tax**.

## What Belief Stack does

Instead of re-deriving state from raw history each turn, Belief Stack **maintains** it: a compact, always-current list of the beliefs the system holds right now, each with a lifecycle (it can be born, strengthened, weakened, contradicted, retired). The agent reads that list instead of the raw log.

**Before** — what a planner typically sees (truncated; ~2,000 tokens of scrollback):

```
[turn 3201] assistant: running the migration script...
[turn 3202] tool: ...2,300 lines of output...
[turn 3206] assistant: kicking off the test suite
[turn 3228] user: looks good, but did validation actually finish?
[turn 3231] assistant: applying a fix to the failing case
... hundreds more turns the model must re-read and re-interpret ...
```

**After** — the maintained belief overlay it reads instead (~215 tokens):

```
=== belief overlay (current state) ===
[active]       pipeline_running    :: a long-running action is currently executing
[active]       fix_attempted       :: a fix has been applied but not yet validated
[active]       validation_pending  :: validation has not yet been observed for the latest fix
[contradicted] validation_complete :: earlier "validation passed" no longer holds
[active]       action_blocked      :: a precondition blocks the proposed next action
```

Same situation, ~1/10th the tokens — and the state is stated, not buried. The agent reasons against a current view of the world instead of rebuilding one from the pile every turn.

> **When this applies — and when it doesn't.** Belief Stack adds value when a system must track **revisable hypotheses over time**. If all you need is event storage, retrieval, or track reconstruction, a database or temporal graph is usually enough.

## How it works

Belief Stack is a five-layer pipeline. Raw evidence comes in at the bottom; a sparse, current belief view comes out the top.

| Layer | Module | What it does |
|---|---|---|
| **L0 — events** | `events` | Raw, timestamped evidence. Append-only, never edited — the source of truth. |
| **L1 — regions** | `regions` | Group similar evidence together (e.g. cluster by embedding) so beliefs attach to a *region* of evidence, not a single line. |
| **L2 — hypotheses** | `hypotheses` | For each region, form a **belief**: a forward claim about what's true / what comes next, with a confidence. |
| **L3 — lifecycle** | `lifecycle` | As new evidence arrives, move each belief along its lifecycle: **born → strengthened → weakened → contradicted → retired**. This is the part that makes a belief *revisable* rather than a summary that silently overwrites. |
| **L4 — calibration** | `calibration` | Walk-forward check: did the beliefs actually hold against held-out outcomes? Keeps the layer honest. |

The agent (or a human, or a downstream system) consumes a **projection** of the current beliefs — the compact overlay shown above. The raw evidence and full warrants stay in the substrate for audit; the planner only sees the sparse view.

In code, the end-to-end flow is short (condensed from [`examples/thesis_radar/run_demo.py`](examples/thesis_radar/run_demo.py)):

```python
from beliefstack import (
    load_events_jsonl, get_default_embedder, fit_regions, assign_to_regions,
    EmpiricalHypothesisGenerator, walk_forward_calibrate, update_lifecycle, classify_region,
)

events     = load_events_jsonl("events.jsonl")                 # L0  raw evidence
embeddings = get_default_embedder().embed([e.text for e in events])
regions    = fit_regions(embeddings, events, k=8)              # L1  cluster similar evidence
region_ids = assign_to_regions(embeddings, regions).tolist()

gen        = EmpiricalHypothesisGenerator(min_train=2)         # L2  form a belief per region
hypotheses = [h for r in regions if (h := gen.generate(r, train_events, now))]

cals       = walk_forward_calibrate(events, region_ids, hypotheses, split_at)  # L4  did beliefs hold?
# L3: update_lifecycle() compares this run's calibration to the prior run's and
#     emits born / strengthened / weakened / contradicted for each region.
```

Run a full demo end-to-end: see [`examples/thesis_radar/`](examples/thesis_radar/) (generic theses) or [`examples/teams_sensemaking/`](examples/teams_sensemaking/) (synthetic Teams chatter). Both produce an HTML report of the beliefs and how they revised over time.

## Does it work?

Yes — measured, on a pre-registered sequence of experiments over **164 Claude Code session logs**, **75 paired single-next-action planning questions**, **four LLMs from three providers**. A sparse maintained-state overlay used **~1/10th the input tokens** of raw history *while improving* planning correctness:

| | Maintained state | Raw history |
|---|---|---|
| Mean input tokens (4 models) | **241** | 2,502 (~10×) |
| Planning correctness (4 models) | **99.0%** | 89.3% |
| Latency (single model, measured) | **~3× lower** | — |

Follow-on experiments stress-tested *why*: the lift comes from the **substrate transformation** (filtering to currently-held beliefs, clustering, ranking) — not from fancy formatting (v0.4a.1), and not from compression alone (v0.4a.2); it held across four models (v0.4c1). The credibility story is that arc — three pre-registered chances to collapse, and it didn't. Full write-ups in [`experiments/`](experiments/) and the [`paper/`](paper/). One experiment remains before the claim earns full generality: cross-substrate replication (v0.4c2).

---

## Where to go next

| If you want… | Go to |
|---|---|
| **Try the mechanism** | [`examples/thesis_radar/`](examples/thesis_radar/) — run it, read the HTML report |
| **Read the library** | [`beliefstack/`](beliefstack/) — ~1,500 lines, one module per layer |
| **Check fit for your own domain** | [`docs/belief_stack_fit_assessment_kg.md`](docs/belief_stack_fit_assessment_kg.md) |
| **See the evidence** | [`experiments/`](experiments/) — each has a pre-registration + report |
| **Read the paper** | [`paper/`](paper/) |

## Repository map

| Path | What it is |
|---|---|
| [`beliefstack/`](beliefstack/) | **The library** (the mechanism). One module per layer: `events` · `regions` · `hypotheses` · `lifecycle` · `calibration`, plus `decisions`, `warrants`, `embeddings`, `reports`. |
| [`examples/`](examples/) | **Runnable demos** — `thesis_radar/` (generic organizational theses) and `teams_sensemaking/` (synthetic Teams chatter). Two domains, same machinery. |
| [`experiments/`](experiments/) | **The evidence ledger** — pre-registered experiments with reports: operational_belief_v1/v2 · belief_stack_v0_3 · belief_stack_v0_4a · belief_stack_v0_4c1 · stack_grounded_v1 · sensemaking_v1_5 (a markets-substrate bridge) · tkos_log_replay. |
| [`paper/`](paper/) | The manuscript-in-progress — *Reducing the Reconstruction Tax in Long-Running LLM Workflows*. |
| [`tkos_sidecar/`](tkos_sidecar/) | A runtime write-path slice (capture/verify/export of agent traces into the substrate). |
| [`field/`](field/) | The L1 "evidence as a time-enabled semantic field" work; see [`field/gallery/`](field/gallery/) for rendered output. |
| [`methodology/`](methodology/) | The operating discipline (pre-registration, lock-before-run). |
| [`docs/`](docs/) | Reader guides, starting with the fit assessment. |

## Data

Raw experiment data is **not shipped in full** — it derives from real Claude Code session logs (privacy) and market data (redistribution). Results live in each experiment's report; small **sanitized samples** are included where possible. See [`DATA.md`](DATA.md).

## License

- **Code** — Apache License 2.0 ([`LICENSE`](LICENSE)).
- **Paper, reports, and prose** — Creative Commons Attribution 4.0 ([`LICENSE-prose.md`](LICENSE-prose.md)).

## Citation

> Stranburg, S. (2026). *Reducing the Reconstruction Tax in Long-Running LLM Workflows: Maintained State as a Planning Primitive.* Working draft. https://topicspace.ai/research/belief-stack

Code & data: https://github.com/sstranburg/belief-stack
