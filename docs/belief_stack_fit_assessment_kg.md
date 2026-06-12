# Belief Stack Fit Assessment for Temporal Knowledge Graph Reasoning

A short brief for evaluating whether the Belief Stack architecture adds value to a temporal knowledge graph (KG) use case — **before** reading the full spec. The full spec is rich enough that a coding assistant given only the spec will tend to summarize generically. This brief is designed to force a fit evaluation against the actual use case in front of you.

---

## 1. What Belief Stack is, in plain language

Belief Stack tracks **revisable, evidence-backed hypotheses over time**. It separates three things most systems collapse together:

- What was **observed** — immutable, append-only, the source of truth
- What is **represented** — structured knowledge about entities, relations, time
- What the system currently **believes those representations imply** — with provenance, with a lifecycle, and with a contradiction signal

Core thesis: when an agent (or human, or downstream system) has to act, it shouldn't have to re-derive its current view of the world from raw history every time. The maintained belief layer is a *planning primitive* — and equally, an *observability surface* for what the system thinks it knows.

---

## 2. Layer mapping for a KG use case

| Layer | What lives here | Example in a KG system |
|---|---|---|
| **L0** | Raw evidence | Source documents, logs, ingestion events, tool outputs, sensor data — the unchanging append-only truth |
| **L1** | Representation | The temporal knowledge graph itself — entities, edges, provenance, timestamps. The structured form of L0 |
| **L2** | Beliefs / hypotheses | Claims *derived from* the graph: *"X is currently a supplier to Y,"* *"this relation is strengthening,"* *"this entity's role is changing,"* *"this assertion is contradicted by recent evidence"* |
| **L3** | Lifecycle | Each L2 belief has a state: **born → strengthened → weakened → contradicted → retired** (or **superseded** by a newer belief). Beliefs are revisable claims with provenance, *not* summaries that overwrite silently |
| **L4** | Outcome | Did the belief layer measurably improve retrieval, ranking, routing, agent action, or downstream reasoning vs. operating on the raw graph + history? |

Note the asymmetry: the KG (L1) and the beliefs (L2) are *the same substrate viewed through different projections*. The graph is what's true structurally; the beliefs are what's currently held about what those structures imply.

---

## 3. The key fit question

**Does this KG use case require reasoning about what the graph implies, or is the graph itself sufficient?**

> **If consumers only query the graph for stored facts, Belief Stack is unnecessary overhead.** You have a database problem, not a belief problem. Worth saying out loud at the top of the conversation — the architecture is only honest if it's also willing to disqualify itself.

Belief Stack starts adding value when **three or more** of the following apply:

- The system must reason about **what the graph implies** beyond what's explicitly encoded
- Agents take **multi-step actions** whose correctness depends on a current interpretation of the graph
- Hypotheses about entities or relations need to be **revised over time** with explicit lifecycle, not silently overwritten on each ingest
- It matters **why** the system took a path through the graph, and which assumptions it relied on
- Different consumers (planner, human reviewer, audit, downstream service) need **different projections** of the same underlying belief state

If fewer than three apply, the KG itself is probably the right ceiling.

---

## 4. Failure modes Belief Stack makes visible

A useful frame for whether the architecture earns its weight: what questions go from *hard to answer* to *trivial to answer* once the belief layer exists?

**Without Belief Stack — typically hard:**
- Why did the agent choose this path through the graph?
- Which assumptions were driving that action at decision time?
- What changed the system's mind between yesterday and today?
- Which interpretation was contradicted by the new evidence?
- What did the system *almost* believe, and why didn't it?

**With Belief Stack — surfaced by construction:**
- The set of currently active hypotheses is explicit and queryable.
- Each belief carries the evidence (and provenance) that supports it.
- Contradictions are first-class events, not silent overwrites.
- Revision history is traceable — you can replay the belief state at any past time.
- Retired beliefs are auditable, not erased.

If the KG use case has stakeholders who routinely ask the "without" questions above and currently can't get clean answers, that's a fit signal independent of the planning question. Observability is a structural consequence of maintaining belief state, not a separate feature you build.

---

## 5. Questions for your coding assistant

Work through these against the specific KG use case in front of you. Generic answers mean the assistant didn't engage with the actual system.

1. **What counts as L0 evidence here?** What is the immutable, append-only source of truth?
2. **What counts as L1 graph structure?** What does the temporal KG store explicitly?
3. **What candidate L2 beliefs naturally arise?** *(This is the diagnostic question. A useful answer looks like: "Vendor X is becoming critical." "Entity Y is likely stale." "Source Z is becoming unreliable." "Relationship A→B is strengthening." An unhelpful answer reduces every belief to "store another edge / another timestamp / another property" — which means the graph is already enough.)* Name 5–10 hypotheses that real consumers of the system would actually use. Be concrete — not "the system has beliefs about X" but the literal sentence form.
4. **Which of those beliefs would change retrieval, ranking, routing, trust scoring, or agent action?** If none — Belief Stack may not help here.
5. **For each belief, what evidence would strengthen, weaken, contradict, or retire it?** If this can't be articulated for most of them, the lifecycle discipline isn't load-bearing and you'd be paying for machinery you don't use.
6. **What simpler architecture would capture 80% of the value?** Candidates: graph + materialized views; cached query results with TTLs; embeddings over graph subgraphs; a flat fact store with timestamps; periodic batch summaries.
7. **What's the smallest prototype that would test fit?** One belief type, one consumer surface, one week to build, one measurable outcome vs. the simpler baseline from Q6.

---

## 6. The skeptical test

The question that keeps this honest:

> **What simpler architecture could capture 80% of the value, and what does Belief Stack add on top of that 80%?**

If the answer is *"nothing meaningful,"* then this system needs a graph, not a Belief Stack.

If the answer is *"explicit hypothesis lifecycle, a contradiction signal, and asymmetric projections of the same belief state into different consumer surfaces,"* then Belief Stack is doing real work and the prototype from Q7 is worth a week.

The most common failure mode of architectures like this is **"belief = summary" collapse** — where the lifecycle vocabulary gets adopted but the implementation is just rolling summaries that silently overwrite. If your prototype can't distinguish *strengthened* from *born-again-each-time*, you're doing summaries, not beliefs.

---

## 7. Next step

If the fit assessment comes back positive, the full spec lives at:
**[topicspace.ai/research/belief-stack](https://topicspace.ai/research/belief-stack)**

Measured evidence to date:
- **v0.3** — 285-token maintained belief overlay outperformed a 2,037-token raw log by 8 percentage points (98.7% vs 90.7%) on a 75-question single-next-action planning task, at 3× lower latency and 14% of the input tokens. (Substrate: Claude Code session logs.)
- **v0.4c1** — Cross-model replication held; the result was not specific to one foundation model.

If fit is negative, that's also a valid outcome — the brief did its job.
