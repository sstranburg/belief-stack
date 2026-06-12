# Data

## Policy

This repository ships **code, pre-registrations, reports, and small sanitized samples** — not the full raw datasets. Two reasons:

1. **Privacy.** The operational experiments (`operational_belief_*`, `belief_stack_v0_3`, `tkos_log_replay`) are derived from real Claude Code session logs. The raw contexts and answers contain file paths, code, and project content from live development work and are not redistributable as-is.
2. **Redistribution.** The `sensemaking_v1_5` bridge is derived from market data that cannot be republished under its source terms.

The **results** are fully reported in each experiment's `*_REPORT*.md`. Where a sanitized sample is provided, it lives in that experiment's `data/sample/` directory and is a small, privacy-reviewed slice — enough to make the code legible and run on a toy input, not a reproduction set.

## What is excluded

Per experiment, the following are **withheld** (kept in the private research repo):

- Full `contexts_*.jsonl`, `answers_*.jsonl`, `*_substrate.jsonl`, embeddings (`*.npz`), and labeled parquet
- Raw normalized/classified session corpora (`sessions_*.jsonl`, `reasoning_ledger.jsonl`)
- Audit JSONs that embed raw context

## Reproducing

The experiments run against your own data:

- **Operational / log-replay experiments** — point the build scripts at your own Claude Code session logs (`~/.claude/projects/.../*.jsonl`). The construction notes in each experiment directory document the substrate-building steps.
- **Embeddings + answers** — set `OPENAI_API_KEY` (the scripts read it via `python-dotenv`); some scripts also use other providers per the cross-model experiments.
- **Sensemaking bridge** — requires a market-data substrate not provided here.

Sanitized samples, where present, are illustrative only and will not reproduce the reported numbers.
