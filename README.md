# Belief Stack

**Maintained state is a planning primitive.**

> Agents shouldn't have to reconstruct current state from raw history every time they plan.

Belief Stack is a **research artifact and reference implementation** for maintained, revisable belief state. Long-running LLM agents pay a *reconstruction tax*: every planning step re-derives the current world model from the same growing pile of interaction history. The cost shows up on three axes at once — input tokens, latency, and planning correctness. Belief Stack maintains belief state explicitly — a substrate of currently-held claims, each with a warrant and a lifecycle — and projects a sparse view of it into the planner's context, so the model reasons against a current view of the world instead of rebuilding one each turn.

This repo holds **both the empirical record and a small reference implementation**. New use cases should start in [`examples/`](examples/), not the experiment directories.

```
Core library = mechanism   ·   examples/ = sensemaking fit tests
experiments/ = evidence     ·   paper/ = the claim
```

---

## Start here — route by intent

| If you want… | Go to |
|---|---|
| **What is this?** — the claim + headline result | this README (below) |
| **Try the mechanism** | [`examples/`](examples/) — [`deals_thesis_radar/`](examples/deals_thesis_radar/) or [`teams_sensemaking/`](examples/teams_sensemaking/) |
| **Test your own domain** | [`docs/belief_stack_fit_assessment_kg.md`](docs/belief_stack_fit_assessment_kg.md) |
| **The evidence** | [`experiments/`](experiments/) |
| **The paper** | [`paper/`](paper/) |

> New to the repo? Read the fit assessment, run an example, skim `beliefstack/`, and only open `experiments/` if you want the evidence.

---

## The headline result

Across a sequence of **pre-registered** experiments on operational workflow traces — **164 Claude Code session logs**, **75 paired single-next-action planning questions**, **four LLMs from three providers** — sparse substrate-derived maintained-state projections reduced input tokens by roughly an order of magnitude *while improving* planning correctness:

| | Maintained state | Raw history |
|---|---|---|
| Mean input tokens (4 models) | **241** | 2,502 (~10×) |
| Planning correctness (4 models) | **99.0%** | 89.3% |
| Latency (single-model, measured) | **~3× lower** | — |

The first experiment (**v0.3**, `gpt-4o-2024-08-06`) showed an 8-point correctness gain (98.7% vs 90.7%) on **14% of the input tokens** at **3.2× lower latency**. Follow-on experiments stress-tested *why* it works:

- **v0.4a.1 (mechanism ablation)** — the lift is **not** from rendering warrant/lifecycle metadata into context. A bare-name projection (`belief_type :: claim`) Pareto-dominated richer renderings at matched budget. The load-bearing work is the *substrate transformation* (filter to held beliefs → dedup-cluster → rank), not the projection format.
- **v0.4a.2 (compression control)** — ruled out "it's just compression." An LLM prose summary at matched budget reached 90.7%, below the 97.3% of substrate-derived projections.
- **v0.4c1 (cross-model)** — every maintained-state arm beat raw history directionally on all four models; the compression-control separation is model-dependent (clear on Opus, partial on GPT-4o, narrower on Gemini/Haiku).

**The credibility story is the arc, not the headline number:** three experiments each gave the thesis a pre-registered chance to collapse, and it didn't. One experiment remains required before the empirical claim earns full generality: **cross-substrate replication** (v0.4c2).

---

## Repository map

| Path | What it is |
|---|---|
| [`beliefstack/`](beliefstack/) | **Core runnable library** — the mechanism. `events` (L0) · `regions` (L1) · `hypotheses` (L2) · `lifecycle` (L3) · `calibration` (L4) · `decisions` · `warrants` · `embeddings` · `reports`. |
| [`examples/`](examples/) | **Use-case demos** — the front door for new domains. `deals_thesis_radar/` (thesis radar) and `teams_sensemaking/` (synthetic Teams chatter). Two domains exercising the same L2 `extras` abstraction. |
| [`experiments/`](experiments/) | **The evidence ledger** — pre-registered experiments, each with a pre-registration, report, scripts, and notes. operational_belief_v1/v2 · belief_stack_v0_3 · stack_grounded_v1 · sensemaking_v1_5 (cross-substrate bridge) · tkos_log_replay. |
| [`paper/`](paper/) | The manuscript-in-progress — *Reducing the Reconstruction Tax in Long-Running LLM Workflows*. Earlier drafts in `paper/drafts/`. |
| [`tkos_sidecar/`](tkos_sidecar/) | TKOS write-path engineering — rules spec, integration pattern, read-path slice (`tkos.py`). |
| [`field/`](field/) | The L1 substrate-geometry work — event/expectation corpus as a time-enabled semantic *field*. Code is markets-coupled (won't run standalone); see [`field/gallery/`](field/gallery/) for rendered output. |
| [`methodology/`](methodology/) | The operating discipline — pre-registration, lock-before-run, the dual-consumer pattern. |
| [`docs/`](docs/) | Reader guides, starting with the Belief Stack fit assessment. |

## Layers

| Layer | Module | Concept |
|---|---|---|
| L0 | `events` | Raw evidence — immutable, append-only |
| L1 | `regions` | Representation — local evidence geometry |
| L2 | `hypotheses` | Beliefs — forward predictions over regions (rich content via `extras`) |
| L3 | `lifecycle` | Lifecycle — born → strengthened → weakened → contradicted → retired |
| L4 | `calibration` | Outcome — did the belief layer measurably help |

## Vocabulary

| Layer | Concept | Role |
|---|---|---|
| Thesis | Maintained state is a planning primitive | the claim |
| Product | Belief Stack | the named layer — the spec |
| Architecture | TKOS (Temporal Knowledge Operating System) | the runtime engineering |
| Belief state | claims · warrants · lifecycle | the mechanism |
| Result | reduced reconstruction tax | the measured outcome |

## Data

Raw experiment data is **not shipped in full** — it derives from real Claude Code session logs (privacy) and market data (redistribution). Each experiment's results are written up in its report; small **sanitized samples** are provided where available. See [`DATA.md`](DATA.md).

## License

- **Code** — Apache License 2.0 ([`LICENSE`](LICENSE)).
- **Paper, reports, and prose** — Creative Commons Attribution 4.0 ([`LICENSE-prose.md`](LICENSE-prose.md)).

## Citation

> Stranburg, S. (2026). *Reducing the Reconstruction Tax in Long-Running LLM Workflows: Maintained State as a Planning Primitive.* Working draft. https://topicspace.ai/research/belief-stack
