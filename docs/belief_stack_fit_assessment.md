# Belief Stack Fit Assessment for Your Domain

A short brief for evaluating whether the Belief Stack architecture adds value to **your** use case — **before** reading the full spec. The full spec is rich enough that a coding assistant given only the spec will tend to summarize generically. This brief is designed to force a fit evaluation against the actual system in front of you.

It is domain-agnostic. Whatever your substrate — a knowledge graph, a market/narrative feed, support or operations chatter, a monitoring stream, an agent's interaction history — the same questions apply. Examples below are drawn from several domains; substitute your own.

---

## 1. What Belief Stack is, in plain language

Belief Stack tracks **revisable, evidence-backed hypotheses over time**. It separates three things most systems collapse together:

- What was **observed** — immutable, append-only, the source of truth
- What is **represented** — the structured form of that evidence (a graph, a table, a set of clusters, a document store — whatever your system already keeps)
- What the system currently **believes those representations imply** — with provenance, with a lifecycle, and with a contradiction signal

Core thesis: when an agent (or human, or downstream system) has to act, it shouldn't have to re-derive its current view of the world from raw history every time. The maintained belief layer is a *planning primitive* — and equally, an *observability surface* for what the system thinks it knows.

---

## 2. Layer mapping

The five layers are substrate-agnostic. The middle column is the role; the right column shows how it instantiates across different domains — find the row of your domain, or map your own.

| Layer | What lives here | Examples across domains |
|---|---|---|
| **L0** | Raw evidence — immutable, append-only, the source of truth | KG: source documents, ingestion events · Markets: filings, news, price moves · Support/ops: chat, tickets, meeting notes · Monitoring: alerts, metrics, deploy events · Agent: the interaction / tool-call log |
| **L1** | Representation — the structured form of L0 | KG: the graph (entities, edges, timestamps) · Markets: per-actor narrative clusters · Support/ops: theme clusters · Monitoring: per-service grouping · Agent: clustered turns / events |
| **L2** | Beliefs / hypotheses — claims *derived from* L1 about what's currently true or coming next | KG: *"X is currently a supplier to Y,"* *"this relation is strengthening,"* *"this assertion is contradicted by recent evidence"* · Markets: *"price is moving faster than the supporting story"* · Support: *"this account's issue is escalating"* · Monitoring: *"checkout latency is degrading"* |
| **L3** | Lifecycle — each belief's state: **born → strengthened → weakened → contradicted → retired** (or **superseded**). Revisable claims with provenance, *not* summaries that overwrite silently | Any domain: a belief is born on first evidence, strengthens or weakens as evidence accumulates, is contradicted by counter-evidence, retires when stale |
| **L4** | Outcome — did the belief layer measurably improve retrieval, ranking, routing, agent action, or downstream reasoning vs. operating on raw evidence + the representation alone? | Any domain: walk-forward check of beliefs against held-out outcomes |

Note the asymmetry: the representation (L1) and the beliefs (L2) are *the same substrate viewed through different projections*. L1 is what's true structurally; L2 is what's currently held about what those structures imply.

---

## 3. The key fit question

**Does your use case require reasoning about what your data implies, or is the underlying store itself sufficient?**

> **If consumers only query for stored facts or records, Belief Stack is unnecessary overhead.** You have a database / index / graph problem, not a belief problem. Worth saying out loud at the top of the conversation — the architecture is only honest if it's also willing to disqualify itself.

Belief Stack starts adding value when **three or more** of the following apply:

- The system must reason about **what the data implies** beyond what's explicitly stored
- Agents or consumers take **multi-step actions** whose correctness depends on a current interpretation of the data
- Hypotheses about entities, relations, or situations need to be **revised over time** with explicit lifecycle, not silently overwritten on each update
- It matters **why** the system reached a conclusion, and which assumptions it relied on
- Different consumers (planner, human reviewer, audit, downstream service) need **different projections** of the same underlying belief state

If fewer than three apply, your existing store (graph, table, index) is probably the right ceiling.

---

## 4. Failure modes Belief Stack makes visible

A useful frame for whether the architecture earns its weight: what questions go from *hard to answer* to *trivial to answer* once the belief layer exists?

**Without Belief Stack — typically hard:**
- Why did the system reach this conclusion / take this action?
- Which assumptions were driving that decision at the time?
- What changed the system's mind between yesterday and today?
- Which interpretation was contradicted by the new evidence?
- What did the system *almost* believe, and why didn't it?

**With Belief Stack — surfaced by construction:**
- The set of currently active hypotheses is explicit and queryable.
- Each belief carries the evidence (and provenance) that supports it.
- Contradictions are first-class events, not silent overwrites.
- Revision history is traceable — you can replay the belief state at any past time.
- Retired beliefs are auditable, not erased.

If your use case has stakeholders who routinely ask the "without" questions above and currently can't get clean answers, that's a fit signal independent of the planning question. Observability is a structural consequence of maintaining belief state, not a separate feature you build.

---

## 5. Questions for your coding assistant

Work through these against the specific use case in front of you. Generic answers mean the assistant didn't engage with the actual system.

1. **What counts as L0 evidence here?** What is the immutable, append-only source of truth?
2. **What counts as L1 representation?** What does your system store explicitly — the graph, the table, the clusters, the index?
3. **What candidate L2 beliefs naturally arise?** *(This is the diagnostic question. A useful answer looks like: "Vendor X is becoming critical." "Entity Y is likely stale." "Source Z is becoming unreliable." "This account is about to churn." "This service is degrading." An unhelpful answer reduces every belief to "store another row / edge / timestamp / property" — which means the representation is already enough.)* Name 5–10 hypotheses that real consumers of the system would actually use. Be concrete — not "the system has beliefs about X" but the literal sentence form.
4. **Which of those beliefs would change retrieval, ranking, routing, trust scoring, or action?** If none — Belief Stack may not help here.
5. **For each belief, what evidence would strengthen, weaken, contradict, or retire it?** If this can't be articulated for most of them, the lifecycle discipline isn't load-bearing and you'd be paying for machinery you don't use.
6. **What simpler architecture would capture 80% of the value?** Candidates: the store plus materialized views; cached query results with TTLs; embeddings over subsets; a flat fact store with timestamps; periodic batch summaries.
7. **What's the smallest prototype that would test fit?** One belief type, one consumer surface, one week to build, one measurable outcome vs. the simpler baseline from Q6.

---

## 6. The skeptical test

The question that keeps this honest:

> **What simpler architecture could capture 80% of the value, and what does Belief Stack add on top of that 80%?**

If the answer is *"nothing meaningful,"* then this system needs a database, index, or graph — not a Belief Stack.

If the answer is *"explicit hypothesis lifecycle, a contradiction signal, and asymmetric projections of the same belief state into different consumer surfaces,"* then Belief Stack is doing real work and the prototype from Q7 is worth a week.

The most common failure mode of architectures like this is **"belief = summary" collapse** — where the lifecycle vocabulary gets adopted but the implementation is just rolling summaries that silently overwrite. If your prototype can't distinguish *strengthened* from *born-again-each-time*, you're doing summaries, not beliefs.

---

## 7. Next step

If the fit assessment comes back positive, the full spec lives at:
**[topicspace.ai/research/belief-stack](https://topicspace.ai/research/belief-stack)**

Measured evidence to date (substrate: Claude Code session logs — the *pattern* is domain-agnostic; the *measured result* is on this one substrate so far):
- **v0.3** — 285-token maintained belief overlay outperformed a 2,037-token raw log by 8 percentage points (98.7% vs 90.7%) on a 75-question single-next-action planning task, at 3× lower latency and 14% of the input tokens.
- **v0.4c1** — Cross-model replication held; the result was not specific to one foundation model.

If fit is negative, that's also a valid outcome — the brief did its job.
