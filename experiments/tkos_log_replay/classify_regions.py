#!/usr/bin/env python3
"""
F-023 Phase 1 step 4: L1 region classifier.

Maps each normalized turn to one of seven typed operational regions (from the
F-023 backlog card), or UNCLASSIFIED:

  data_fetch          — ingesting external data
  pipeline_run        — running multi-step automated workflows
  failure_diagnosis   — investigating an error or unexpected outcome
  validation          — verifying correctness of code/data/state
  deploy_readiness    — preparing for or executing a deploy
  report_generation   — creating output artifacts (reports, briefs, dashboards)
  evidence_sealing    — cryptographic timestamping, signing, audit trails
  UNCLASSIFIED        — does not match any of the above (regular conversation,
                        ambiguous tool calls, framework noise)

# Methodology discipline

The classifier rules ARE PRE-REGISTERED in this file. They were written before
the distribution was inspected, based on (a) the operational typology named
in the F-023 backlog card and (b) general knowledge of the engineering
patterns these regions represent. They are NOT to be tuned to the data
distribution after running.

If the resulting distribution looks "wrong" (e.g., too much UNCLASSIFIED,
too few of one region), the correct response is to document the gap as a
finding, not to retroactively edit these rules. Any future revision should
be a version bump (v0.2 rules), not a silent edit.

Input:  data/sessions_normalized.jsonl
Output: data/sessions_classified.jsonl  — each turn + region label + match reason
        data/region_distribution.json    — aggregate stats
"""

from __future__ import annotations

import json
import pathlib
import re
from collections import Counter
from typing import Iterable

IN_PATH  = pathlib.Path(__file__).resolve().parent / "data" / "sessions_normalized.jsonl"
OUT_PATH = pathlib.Path(__file__).resolve().parent / "data" / "sessions_classified.jsonl"
DIST_PATH = pathlib.Path(__file__).resolve().parent / "data" / "region_distribution.json"

RULES_VERSION = "v0.1"  # pre-registered 2026-05-29; do not silently edit


# ─── Region label constants ──────────────────────────────────────────────────
DATA_FETCH        = "data_fetch"
PIPELINE_RUN      = "pipeline_run"
FAILURE_DIAGNOSIS = "failure_diagnosis"
VALIDATION        = "validation"
DEPLOY_READINESS  = "deploy_readiness"
REPORT_GENERATION = "report_generation"
EVIDENCE_SEALING  = "evidence_sealing"
UNCLASSIFIED      = "UNCLASSIFIED"

REGIONS = [
    DATA_FETCH, PIPELINE_RUN, FAILURE_DIAGNOSIS, VALIDATION,
    DEPLOY_READINESS, REPORT_GENERATION, EVIDENCE_SEALING, UNCLASSIFIED,
]


# ─── Pattern banks (PRE-REGISTERED) ──────────────────────────────────────────

# Slash commands that map directly to a region
SLASH_COMMAND_REGION = {
    "evening":     PIPELINE_RUN,
    "morning":     PIPELINE_RUN,
    "add-actor":   DATA_FETCH,
    "loop":        UNCLASSIFIED,  # autonomous loop ticks
}

# Bash command substrings indicating each region.
# Compiled as case-insensitive regex matches on the input_summary string.
BASH_PATTERNS = {
    DATA_FETCH: [
        r"\bcurl\b", r"\bwget\b",
        r"scripts/fetch_today\.py", r"scripts/fetch_backfill",
        r"\bgh\s+api\b", r"finnhub", r"newsapi",
    ],
    PIPELINE_RUN: [
        r"scripts/run_pipeline\.py",
        r"scripts/build_backtest_history\.py",
        r"scripts/generate_(actor_detail|leaderboard|ai_compass|crypto_leaderboard|master_report)\.py",
        r"scripts/run_shadow_tracking\.py",
        r"build_meta_evaluator_report\.py",
        r"build_comprehensive_report\.py",
        r"generate_sensemaking_case_study\.py",
        r"generate_trace_packets\.py",
        r"governance_field(_risk)?(_silhouette)?\.py",
        r"petri_480_transfer",
    ],
    VALIDATION: [
        r"\bpytest\b", r"\bnpm test\b", r"\btsc\b",
        r"--check\b", r"--validate\b", r"--noEmit\b",
        r"\bgit (status|diff|log)\b",
        r"\bps aux\b", r"\bgrep -c\b",
    ],
    DEPLOY_READINESS: [
        r"\bgit commit\b", r"\bgit push\b",
        r"\bvercel\b.*--prod\b",
    ],
    REPORT_GENERATION: [
        r"build_.*report\.py",
        r"generate_.*report\.py",
        r"narrative-leaderboard\.html",
        r"open .*\.html$",
        r"--print-to-pdf",
    ],
    EVIDENCE_SEALING: [
        r"rfc.?3161", r"\btsa\b", r"timestamp",
        r"freetsa\.org", r"openssl ts",
    ],
}

# Compile patterns once
_COMPILED_BASH = {
    region: [re.compile(p, re.IGNORECASE) for p in pats]
    for region, pats in BASH_PATTERNS.items()
}


# Specific tool names that strongly signal a region regardless of args.
TOOL_NAME_REGION = {
    "WebFetch":   DATA_FETCH,
    "WebSearch":  DATA_FETCH,
}

# Text patterns in assistant prose that suggest failure diagnosis.
DIAGNOSIS_TEXT_PATTERNS = [
    r"\blet me (check|investigate|look at|figure out|see what)\b",
    r"\bwhat'?s (going on|the issue|wrong|happening)\b",
    r"\b(error|failed|exception|traceback)\b",
    r"\bdebug",
    r"\bnot (working|completing|finishing)",
]
_COMPILED_DIAG = [re.compile(p, re.IGNORECASE) for p in DIAGNOSIS_TEXT_PATTERNS]

# User text patterns indicating correction / pushback (also failure_diagnosis).
USER_CORRECTION_PATTERNS = [
    r"\bno,?\s+(that|that's|this|wait)\b",
    r"\bwrong\b",
    r"\bthat'?s not right\b",
    r"\blet me correct\b",
    r"\bactually,?\s+(no|that|i mean)\b",
    r"\bcan you fix\b",
]
_COMPILED_CORRECTION = [re.compile(p, re.IGNORECASE) for p in USER_CORRECTION_PATTERNS]

# User text patterns for deploy intent.
DEPLOY_INTENT_PATTERNS = [
    r"^\s*deploy\s*!?\s*$",
    r"^\s*ship it\s*!?\s*$",
    r"\b(deploy|ship) (it|now|when|please)\b",
]
_COMPILED_DEPLOY = [re.compile(p, re.IGNORECASE) for p in DEPLOY_INTENT_PATTERNS]


# ─── Classifier ──────────────────────────────────────────────────────────────

def _extract_command(text: str) -> str | None:
    """Pull a slash command from a /command meta turn."""
    m = re.search(r"<command-name>/(\w[\w-]*)</command-name>", text)
    if m: return m.group(1).lower()
    m = re.match(r"^/(\w[\w-]*)\s", text or "")
    if m: return m.group(1).lower()
    return None


def classify_turn(turn: dict) -> tuple[str, str]:
    """Return (region, reason). Reason is a short string explaining the match."""
    role = turn["role"]
    text = (turn.get("text") or "")
    tool_uses = turn.get("tool_uses", []) or []
    tool_results = turn.get("tool_results", []) or []

    # --- user-side classification ---
    if role == "user":
        # /command turns
        if turn.get("is_meta") and ("<command-message>" in text or text.startswith("/")):
            cmd = _extract_command(text)
            if cmd is not None:
                region = SLASH_COMMAND_REGION.get(cmd)
                if region is not None:
                    return region, f"slash_command=/{cmd}"
                # Unknown command — UNCLASSIFIED
                return UNCLASSIFIED, f"unknown_slash_command=/{cmd}"

        # System reminders — framework noise
        if turn.get("is_meta") and "<system-reminder>" in text:
            return UNCLASSIFIED, "system_reminder"

        # Deploy intent
        for pat in _COMPILED_DEPLOY:
            if pat.search(text):
                return DEPLOY_READINESS, "user_deploy_intent"

        # User correction → failure_diagnosis
        for pat in _COMPILED_CORRECTION:
            if pat.search(text):
                return FAILURE_DIAGNOSIS, "user_correction"

        # Tool results from previous assistant turn — failure_diagnosis if any errored
        if any(tr.get("is_error") for tr in tool_results):
            return FAILURE_DIAGNOSIS, "tool_error_in_result"

        return UNCLASSIFIED, "user_default"

    # --- assistant-side classification ---
    # Tool-name signals first (strongest)
    for tu in tool_uses:
        name = tu.get("name", "")
        if name in TOOL_NAME_REGION:
            return TOOL_NAME_REGION[name], f"tool_name={name}"

    # Bash command pattern signals
    for tu in tool_uses:
        if tu.get("name") != "Bash":
            continue
        cmd = tu.get("input_summary", "") or ""
        # Check each region's pattern bank in priority order
        for region in (PIPELINE_RUN, EVIDENCE_SEALING, DEPLOY_READINESS,
                       REPORT_GENERATION, DATA_FETCH, VALIDATION):
            for pat in _COMPILED_BASH[region]:
                if pat.search(cmd):
                    return region, f"bash_pattern={region}:{pat.pattern[:40]}"

    # File-write signals → REPORT_GENERATION if it's an HTML/MD/PDF file
    for tu in tool_uses:
        if tu.get("name") in ("Write", "Edit"):
            inp = tu.get("input_summary", "") or ""
            if re.search(r"\.(html|pdf)$", inp) or "report" in inp.lower():
                return REPORT_GENERATION, "write_report_artifact"

    # Diagnosis text patterns
    for pat in _COMPILED_DIAG:
        if pat.search(text):
            return FAILURE_DIAGNOSIS, "assistant_diagnosis_text"

    # Read tool with no other context → VALIDATION (assistant verifying state)
    if any(tu.get("name") == "Read" for tu in tool_uses) and not tool_uses[0:0]:
        # Only if Read is the only tool call (to avoid mis-classifying read-then-edit)
        if all(tu.get("name") == "Read" for tu in tool_uses):
            return VALIDATION, "read_only_inspection"

    return UNCLASSIFIED, "assistant_default"


# ─── Main ────────────────────────────────────────────────────────────────────

def iter_turns(path: pathlib.Path) -> Iterable[dict]:
    with path.open() as f:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def main() -> None:
    region_counts: Counter = Counter()
    reason_counts: Counter = Counter()
    per_session: dict = {}

    n_written = 0

    with OUT_PATH.open("w") as out_f:
        for turn in iter_turns(IN_PATH):
            region, reason = classify_turn(turn)
            turn["l1_region"] = region
            turn["l1_reason"] = reason
            turn["rules_version"] = RULES_VERSION
            out_f.write(json.dumps(turn) + "\n")

            region_counts[region] += 1
            reason_counts[reason] += 1
            sid = turn.get("session_id", "?")
            per_session.setdefault(sid, Counter())[region] += 1
            n_written += 1

    # Save distribution
    total = sum(region_counts.values())
    dist = {
        "rules_version":      RULES_VERSION,
        "input_path":         str(IN_PATH),
        "n_turns_classified": n_written,
        "region_counts": {
            r: {"n": int(region_counts.get(r, 0)),
                "pct": round(region_counts.get(r, 0) / total * 100, 2) if total else 0.0}
            for r in REGIONS
        },
        "reason_counts":      dict(reason_counts.most_common()),
        "per_session_region_counts": {
            sid: dict(c) for sid, c in per_session.items()
        },
    }
    DIST_PATH.write_text(json.dumps(dist, indent=2))

    # Human-readable summary
    print(f"Classified {n_written:,} turns under rules {RULES_VERSION}")
    print()
    print("=" * 72)
    print("L1 REGION DISTRIBUTION (rules v0.1 — pre-registered, locked)")
    print("=" * 72)
    print(f"  {'region':<22s} {'count':>9s} {'pct':>7s}")
    print(f"  {'-'*22} {'-'*9} {'-'*7}")
    for r in REGIONS:
        n = region_counts.get(r, 0)
        pct = n / total * 100 if total else 0.0
        print(f"  {r:<22s} {n:>9,} {pct:>6.2f}%")
    classified = total - region_counts[UNCLASSIFIED]
    print(f"\n  Classified to a region: {classified:,} ({classified/total*100:.1f}%)")
    print(f"  UNCLASSIFIED:           {region_counts[UNCLASSIFIED]:,} ({region_counts[UNCLASSIFIED]/total*100:.1f}%)")

    print()
    print("Top match reasons:")
    for reason, n in reason_counts.most_common(15):
        print(f"    {reason:<48s} {n:>8,}")

    print(f"\nWrote {OUT_PATH}")
    print(f"Wrote {DIST_PATH}")


if __name__ == "__main__":
    main()
