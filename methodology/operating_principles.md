# Operating Principles

How this project works.

This is a constitution, not a manual. Eight rules. Each takes a sentence. Together they describe the operating discipline that has actually been running on TopicSpace Research — not an aspirational one.

If you are joining — as a contributor, an AI agent, or a reviewer — read this first.

The **substance** of the work (Belief Stack, runtime belief observability, the v0.3 result) lives at [topicspace.ai/research/belief-stack](https://topicspace.ai/research/belief-stack). This document covers **how** that work happens.

---

## The eight

**Nothing important lives only in chat.**
If a decision, experiment, or finding matters beyond the current conversation, it goes into a durable artifact (memory, decision log, backlog, commit message, or `/ops/`) before the conversation moves on.

**Experiment before conclusion.**
Architectural claims earn their weight from pre-registered experiments, not from rhetoric. If a claim has not been tested, name it as a hypothesis.

**Lock before run.**
Pre-registrations, experiment specs, scoring rules, and seeds are locked before any data flows. Amendments are explicit (re-locked, re-versioned), never silent.

**Report failures.**
Negative results are first-class. When Stack-Grounded v0.1 went against the architecture, we shipped that finding as-is. A mature project's archive contains its rejections.

**Evidence outranks intuition.**
When a measured result conflicts with the intuition that motivated it, the result wins. Intuition is then re-examined — sometimes refined, sometimes discarded.

**Name the critique class before responding.**
Critiques fall into classes (matter / generality / mechanism / cost). Classify first; engage second. Matter-critiques would be regression; generality-critiques are progress.

**Backlog is canonical.**
Work that matters lives in `/ops/backlog.md`. If it is not in the backlog, it is not queued — it is an idea in someone's head, and ideas in heads are not project state.

**Decisions require trace.**
Every architectural decision carries its reason and its reversibility. Cheap-to-reverse decisions get made fast; hard-to-reverse decisions get an audit trail.

---

## Where to go next

- **Substance of the work** — [topicspace.ai/research/belief-stack](https://topicspace.ai/research/belief-stack). The Belief Stack spec, with the v0.3 result and the post-v0.3 vocabulary.
- **Current priorities** — `/ops/backlog.md`.
- **Examples of the rhythm in action** — any pre-registration (e.g., [`experiments/belief_stack_v0_3/BELIEF_STACK_PRE_REGISTRATION_v0.3.md`](../experiments/belief_stack_v0_3/BELIEF_STACK_PRE_REGISTRATION_v0.3.md)) paired with its report. The discipline is visible in the artifact pair, not just the result.
- **The AI substrate** (cold-start orientation for Claude / other agents) — `CLAUDE.md`, the AI-facing cold-start file kept in the private research repo.

---

## How this constitution is used

- These principles describe the operating discipline already in practice. If any of the eight starts to drift from what the project actually does, **update the constitution** rather than letting the discipline degrade silently.
- This document is intentionally short. Anything that would expand it past two screens belongs somewhere else (the spec, the experiment ledger, a work order, a memory file).
- The substrate this surfaces sits on top of has two consumers: humans read `/ops/`; AI agents read `CLAUDE.md` and their own working memory. Same source of truth, different surfaces.

---

*Living document. Updated when the principles drift from what the project actually does. Last revision: 2026-06-03 (first deliverable of OPS-001).*
