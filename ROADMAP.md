# Roadmap

This document tracks the major **open questions and planned work** for the Belief Stack research program. The items below are research directions, not commitments — and several are framed as *what would have to be true* for the current claims to extend or fail.

For where the evidence stands today, see [`experiments/`](experiments/) and the [`paper/`](paper/). For whether the pattern fits a domain you care about, see [`docs/belief_stack_fit_assessment.md`](docs/belief_stack_fit_assessment.md).

---

## v0.4c2 — Cross-substrate replication

Current evidence comes from coding-assistant session logs. The next major question is whether the maintained-belief-state pattern transfers to other substrates that contain evolving hypotheses and revision dynamics.

**Success criterion**
- Replicate the maintained-state advantage on at least one additional substrate.
- Measure outcome quality, latency, and token efficiency using the same evaluation discipline.

**Why it matters**
The strongest current claim is substrate-specific. Cross-substrate replication is required before making broader generality claims.

---

## v0.4b — Cost and net value

The current experiments demonstrate planning benefits. The next question is economic:

> When does maintaining belief state cost less than repeatedly reconstructing state from history?

**Areas of investigation**
- LLM cost
- Latency
- Storage
- Maintenance overhead
- Operational complexity

**Success criterion**
- Quantify the conditions under which maintained belief state provides net value.

---

## Reference library hardening

Continue improving the reference implementation while keeping the core architecture intentionally small.

**Areas of focus**
- Additional example domains
- Documentation
- Evaluation tooling
- Reproducibility

**Success criterion**
- A new domain can be evaluated with minimal custom code and a clear fit-assessment process.

---

## Open principle

The project favors **empirical validation over architectural expansion**. New abstractions should be introduced only when supported by measured results or repeated patterns across multiple substrates.
