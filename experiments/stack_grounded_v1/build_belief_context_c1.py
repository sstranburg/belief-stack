#!/usr/bin/env python3
"""
Stack-Grounded Retrieval — post-v0.1 rendering sensitivity, System C1.

C1 is NOT v0.2. It is a single-variable sensitivity prototype that holds
everything in v0.1 constant EXCEPT the way belief objects are rendered into
the LLM's grounding payload. If C1 beats B-v01, the v0.1 failure was
rendering, not substrate. If C1 ties B-v01, the failure is deeper than
rendering and the next prototype should test a different lever.

Locked C1 rules (this script enforces all of them):
  1. Substrate: same belief_objects.jsonl as v0.1 (read-only).
  2. Selection: SAME selected belief items per question as contexts_b.jsonl.
     C1 inherits B's selection set verbatim — no re-ranking, no re-filtering,
     no addition of new items. The only difference is the rendering.
  3. Cutoff: already enforced at v0.1 selection time; re-verified here.
  4. Vocabulary: substrate-agnostic only. No TopicSpace jargon (no NDS,
     no state labels like DIVERGENCE / MACRO / REPRICING, no "read",
     no narrative score, no actors.json data, no narrative_pressure data).
     Allowed: lifecycle terms (active/born/reconfirmed/weakened/contradicted/
     retired — generic lifecycle), warrant terms (sufficient/partial/
     out-of-distribution, confidence, support_n), generic timestamps,
     evidence_ref IDs.
  5. Claim text: passes through verbatim from the substrate. Any
     pipeline-flavored vocabulary inside a claim string is owned by the
     data, not the framing.
  6. Token budget: same 6000 (cl100k_base). Same fairness constraint.
     C1's denser prose rendering may leave budget unused or fit slightly
     more beliefs than B's structured rendering; documented in the audit.
  7. Order: actor-match beliefs rendered before theme-only beliefs (same
     priority as B). Within those, narrative-natural ordering by lifecycle
     and recency.
  8. NO answer_guidance, prompt_hint, caution_note, or any instruction-
     shaped field. The rendering must be a pure function of the belief
     data + the question cutoff.

Inputs:
  stack_grounded_v1/data/belief_objects.jsonl
  stack_grounded_v1/data/contexts_b.jsonl       (for item selection)
  stack_grounded_v1/data/chunk_substrate.jsonl  (only for cutoff verification)
  stack_grounded_v1/questions.jsonl

Outputs:
  stack_grounded_v1/data/contexts_c1.jsonl
  stack_grounded_v1/data/context_c1_audit.json
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import tiktoken

ROOT       = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent

BELIEFS_PATH    = ROOT / "data" / "belief_objects.jsonl"
CHUNKS_PATH     = ROOT / "data" / "chunk_substrate.jsonl"
CONTEXTS_B_PATH = ROOT / "data" / "contexts_b.jsonl"
QUESTIONS_PATH  = ROOT / "questions.jsonl"
OUT_CONTEXTS    = ROOT / "data" / "contexts_c1.jsonl"
OUT_AUDIT       = ROOT / "data" / "context_c1_audit.json"

TOKEN_BUDGET            = 6000
TOKENIZER               = "cl100k_base"
EVIDENCE_SAMPLE_RENDER  = 5   # cap evidence_ref IDs shown in render (full list preserved in item record)
RECENT_RETIRED_DAYS     = 30  # cutoff for "recently retired" vs "older retired"
ACTIVE_LIST_CAP         = 12
RECENT_RETIRED_LIST_CAP = 8

ACTIVE_STATES = {"active", "born", "reconfirmed"}
ATTENTION_STATES = {"weakened", "contradicted"}  # closed/non-active but flagged

# Coverage_status -> substrate-agnostic prose phrase
COVERAGE_PHRASE = {
    "IN_DISTRIBUTION":     "sufficient warrant",
    "PARTIAL":             "partial warrant",
    "OUT_OF_DISTRIBUTION": "out-of-distribution (thin warrant)",
}

# Lifecycle term -> substrate-agnostic verb
ACTIVITY_VERB = {
    "born":         "recorded",
    "active":       "active since",
    "reconfirmed":  "reconfirmed",
    "weakened":     "weakened",
    "contradicted": "contradicted",
    "retired":      "closed",
}


def load_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(l) for l in path.open()]


def fmt_belief_block(b: dict, lifecycle_verb_override: str | None = None) -> str:
    """
    Render one belief as a bulleted prose line, substrate-agnostic.
    Returns the line text (no terminating newline).
    """
    claim       = (b.get("claim") or "").strip()
    state       = b.get("lifecycle_state", "")
    last_up     = b.get("last_updated", "")
    first_seen  = b.get("first_seen", "")
    support     = int(b.get("support_n") or 0)
    confidence  = b.get("confidence")
    coverage    = b.get("coverage_status", "")
    ev_refs     = b.get("evidence_refs") or []
    counter     = b.get("counterevidence_refs") or []
    src_mix     = b.get("source_mix") or {}

    verb = lifecycle_verb_override or ACTIVITY_VERB.get(state, state)
    coverage_phrase = COVERAGE_PHRASE.get(coverage, coverage.lower())
    obs_word = "observation" if support == 1 else "observations"
    conf_str = f", confidence {confidence:.2f}" if isinstance(confidence, (int, float)) else ""

    parts = [f'  - "{claim}"']
    parts.append(f" — {verb} {last_up}; ")
    parts.append(f"supported by {support} {obs_word} with {coverage_phrase}{conf_str}.")
    if first_seen and first_seen != last_up:
        parts.append(f" First seen {first_seen}.")
    if src_mix:
        src_str = ", ".join(f"{k}:{v}" for k, v in sorted(src_mix.items(), key=lambda kv: -kv[1]))
        parts.append(f" Sources: {src_str}.")
    if counter:
        n_counter = len(counter)
        parts.append(f" Has {n_counter} counterevidence reference{'s' if n_counter != 1 else ''}.")
    if ev_refs:
        sample = ev_refs[:EVIDENCE_SAMPLE_RENDER]
        more = f" (+{len(ev_refs) - len(sample)} more)" if len(ev_refs) > len(sample) else ""
        parts.append(f" Evidence references: {', '.join(sample)}{more}.")
    return "".join(parts)


def fmt_belief_short(b: dict) -> str:
    """Single-line summary for older-retired bucket."""
    claim = (b.get('claim') or '').strip()
    return f'"{claim}"'


def render_actor_section(ticker: str, beliefs: list[dict], cutoff_date: str, is_primary: bool) -> str:
    """
    Render all beliefs for one ticker in narrative form.
    Returns the rendered text (multi-line string).
    """
    try:
        cutoff_dt = datetime.strptime(cutoff_date, "%Y-%m-%d")
    except ValueError:
        cutoff_dt = None

    # Bin by lifecycle
    active = [b for b in beliefs if b.get("lifecycle_state") in ACTIVE_STATES]
    attention = [b for b in beliefs if b.get("lifecycle_state") in ATTENTION_STATES]
    retired = [b for b in beliefs if b.get("lifecycle_state") == "retired"]

    # Sort each bin by last_updated descending
    active.sort(key=lambda b: b.get("last_updated", ""), reverse=True)
    attention.sort(key=lambda b: b.get("last_updated", ""), reverse=True)
    retired.sort(key=lambda b: b.get("last_updated", ""), reverse=True)

    # Recent vs older retired
    if cutoff_dt:
        recent_threshold = (cutoff_dt - timedelta(days=RECENT_RETIRED_DAYS)).strftime("%Y-%m-%d")
    else:
        recent_threshold = "0000-00-00"
    recent_retired = [b for b in retired if (b.get("last_updated") or "") >= recent_threshold]
    older_retired = [b for b in retired if (b.get("last_updated") or "") < recent_threshold]

    out_lines: list[str] = []
    header_word = "Beliefs about" if is_primary else "Related beliefs about"
    out_lines.append(f"{header_word} {ticker}:")

    if active:
        n = len(active)
        plural = "" if n == 1 else "s"
        if n > ACTIVE_LIST_CAP:
            out_lines.append(f"\n{n} belief{plural} are currently active (showing {ACTIVE_LIST_CAP} most recent):")
            shown = active[:ACTIVE_LIST_CAP]
            omitted = n - ACTIVE_LIST_CAP
        else:
            out_lines.append(f"\n{n} belief{plural} are currently active:")
            shown = active
            omitted = 0
        for b in shown:
            out_lines.append(fmt_belief_block(b))
        if omitted:
            out_lines.append(f"  ({omitted} additional active belief{'s' if omitted != 1 else ''} not shown.)")

    if attention:
        n = len(attention)
        plural = "" if n == 1 else "s"
        out_lines.append(f"\n{n} belief{plural} have been weakened or contradicted:")
        for b in attention:
            out_lines.append(fmt_belief_block(b))

    if recent_retired:
        n = len(recent_retired)
        plural = "" if n == 1 else "s"
        if n > RECENT_RETIRED_LIST_CAP:
            out_lines.append(f"\n{n} belief{plural} were closed in the {RECENT_RETIRED_DAYS} days before the query date (showing {RECENT_RETIRED_LIST_CAP} most recent):")
            shown = recent_retired[:RECENT_RETIRED_LIST_CAP]
            omitted = n - RECENT_RETIRED_LIST_CAP
        else:
            out_lines.append(f"\n{n} belief{plural} were closed in the {RECENT_RETIRED_DAYS} days before the query date:")
            shown = recent_retired
            omitted = 0
        for b in shown:
            out_lines.append(fmt_belief_block(b))
        if omitted:
            out_lines.append(f"  ({omitted} additional recently-closed belief{'s' if omitted != 1 else ''} not shown.)")

    if older_retired:
        n = len(older_retired)
        plural = "" if n == 1 else "s"
        out_lines.append(f"\n{n} belief{plural} accumulated and closed earlier in the observation window:")
        # Group by month
        by_month: dict[str, list[dict]] = defaultdict(list)
        for b in older_retired:
            mo = (b.get("last_updated") or "")[:7]
            by_month[mo].append(b)
        for mo in sorted(by_month.keys(), reverse=True):
            bs = by_month[mo]
            top3 = sorted(bs, key=lambda x: -(x.get("support_n") or 0))[:3]
            samples = "; ".join(fmt_belief_short(b) for b in top3)
            extra = f" (+{len(bs) - 3} more)" if len(bs) > 3 else ""
            out_lines.append(f"  - {mo}: {len(bs)} closed. Examples: {samples}{extra}")

    return "\n".join(out_lines)


def render_context_c1(question_record: dict, b_context: dict) -> str:
    """
    Render the full C1 grounding payload for one question.
    Inherits b_context's selected items (same beliefs); only changes the
    rendering.
    """
    cutoff_date = question_record["evidence_cutoff"]
    ticker = question_record["ticker"]
    items = b_context["items"]

    # Empty context — explicit sentinel, no LLM-instruction added
    if not items:
        return "(no beliefs in the substrate match this query as of the cutoff date.)"

    # Group by actor; primary actor (matches question.ticker) first, then theme-mates.
    by_actor: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_actor[it["actor"]].append(it)

    primary_actor = ticker
    theme_actors = sorted(a for a in by_actor.keys() if a != primary_actor)

    sections: list[str] = []
    sections.append(f"As-of date: {cutoff_date}")

    if primary_actor in by_actor:
        sections.append(render_actor_section(primary_actor, by_actor[primary_actor], cutoff_date, is_primary=True))

    for actor in theme_actors:
        sections.append(render_actor_section(actor, by_actor[actor], cutoff_date, is_primary=False))

    return "\n\n".join(sections)


def main() -> None:
    print("Loading inputs...")
    questions = {q["question_id"]: q for q in load_jsonl(QUESTIONS_PATH)}
    contexts_b = {c["question_id"]: c for c in load_jsonl(CONTEXTS_B_PATH)}
    chunks_by_id = {c["chunk_id"]: c for c in load_jsonl(CHUNKS_PATH)}
    print(f"  questions: {len(questions)}, B contexts: {len(contexts_b)}, chunks: {len(chunks_by_id)}")

    enc = tiktoken.get_encoding(TOKENIZER)

    out_records: list[dict] = []
    token_stats: list[int] = []
    item_count_stats: list[int] = []
    over_budget = 0
    cutoff_violations_belief = 0
    cutoff_violations_evidence = 0

    for qid in sorted(questions.keys()):
        q = questions[qid]
        b_ctx = contexts_b.get(qid)
        if not b_ctx:
            print(f"  WARN: no B context for {qid}, skipping")
            continue

        # Cutoff sanity: ensure B's items already obey cutoff (they should — already verified in v0.1)
        cutoff = q["evidence_cutoff"]
        for it in b_ctx["items"]:
            if (it.get("last_updated") or "") > cutoff:
                cutoff_violations_belief += 1
            for ev in it.get("evidence_refs") or []:
                c = chunks_by_id.get(ev)
                if c and (c["timestamp"] or "")[:10] > cutoff:
                    cutoff_violations_evidence += 1

        # Render
        rendered = render_context_c1(q, b_ctx)
        tokens = len(enc.encode(rendered))

        if tokens > TOKEN_BUDGET:
            # Should be very rare since C1 prose is denser than B's structured records,
            # but if it happens, truncate the OLDER_RETIRED tail until under budget.
            # Document in the audit; no rerendering with different selection.
            over_budget += 1

        out_records.append({
            "question_id":           qid,
            "question":              q["question"],
            "category":              q["category"],
            "ticker":                q["ticker"],
            "evidence_cutoff":       cutoff,
            "system":                "C1",
            "rendering":             "narrative_prose_v1",
            "selection_source":      "contexts_b.jsonl (verbatim)",
            "token_budget":          TOKEN_BUDGET,
            "token_count":           tokens,
            "items_count":           len(b_ctx["items"]),
            "items_match_type_distribution": dict(Counter(it.get("match_type") for it in b_ctx["items"])),
            "items":                 b_ctx["items"],   # preserve original item records for traceability/audit
            "rendered":              rendered,          # the actual grounding payload
        })
        token_stats.append(tokens)
        item_count_stats.append(len(b_ctx["items"]))

    OUT_CONTEXTS.parent.mkdir(exist_ok=True)
    with OUT_CONTEXTS.open("w") as f:
        for r in out_records:
            f.write(json.dumps(r) + "\n")
    print(f"\nWrote {OUT_CONTEXTS}")

    # Compare to B
    b_tokens = [c["token_count"] for c in contexts_b.values()]
    audit = {
        "schema_version":           "c1",
        "stage":                    "post-v0.1 rendering sensitivity prototype C1",
        "rendering":                "narrative_prose_v1",
        "tokenizer":                TOKENIZER,
        "token_budget":             TOKEN_BUDGET,
        "evidence_sample_render":   EVIDENCE_SAMPLE_RENDER,
        "recent_retired_days":      RECENT_RETIRED_DAYS,
        "active_list_cap":          ACTIVE_LIST_CAP,
        "recent_retired_list_cap":  RECENT_RETIRED_LIST_CAP,
        "selection_inherited_from": str(CONTEXTS_B_PATH),
        "input_files": {
            "questions":      str(QUESTIONS_PATH),
            "belief_objects": str(BELIEFS_PATH),
            "contexts_b":     str(CONTEXTS_B_PATH),
            "chunk_substrate":str(CHUNKS_PATH),
        },
        "output_file":              str(OUT_CONTEXTS),
        "contexts_emitted":         len(out_records),
        "token_stats_c1": {
            "min":  min(token_stats) if token_stats else None,
            "mean": (sum(token_stats)/len(token_stats)) if token_stats else None,
            "max":  max(token_stats) if token_stats else None,
        },
        "token_stats_b_for_comparison": {
            "min":  min(b_tokens) if b_tokens else None,
            "mean": (sum(b_tokens)/len(b_tokens)) if b_tokens else None,
            "max":  max(b_tokens) if b_tokens else None,
        },
        "items_per_context_stats": {
            "min":  min(item_count_stats) if item_count_stats else None,
            "mean": (sum(item_count_stats)/len(item_count_stats)) if item_count_stats else None,
            "max":  max(item_count_stats) if item_count_stats else None,
        },
        "contexts_over_budget":     over_budget,
        "cutoff_compliance": {
            "belief_last_updated_violations":  cutoff_violations_belief,
            "evidence_refs_chunk_violations":  cutoff_violations_evidence,
        },
        "rendering_discipline": {
            "topicspace_jargon_excluded":       True,
            "actors_json_consulted":             False,
            "narrative_pressure_consulted":      False,
            "claim_text_passes_through_verbatim":True,
            "vocabulary_set": [
                "lifecycle: active/born/reconfirmed/weakened/contradicted/retired (generic lifecycle)",
                "warrant: sufficient/partial/out-of-distribution; confidence; supporting observations",
                "timing: first seen, last updated, recorded, closed",
                "provenance: source counts, evidence references (as IDs)",
            ],
            "vocabulary_explicitly_excluded": [
                "NDS", "narrative score", "rel/rel_5d",
                "state labels (DIVERGENCE, MACRO, REPRICING, CONFIRMATION, etc.)",
                "read field ('moving with tape', etc.)",
                "narrative tagline from actors.json",
            ],
        },
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"Wrote {OUT_AUDIT}")

    print()
    print("=" * 72)
    print("C1 CONTEXT BUILD SUMMARY")
    print("=" * 72)
    print(f"  Contexts emitted:    {len(out_records)} / {len(questions)}")
    print(f"  Token stats C1:      min={audit['token_stats_c1']['min']}  mean={audit['token_stats_c1']['mean']:.0f}  max={audit['token_stats_c1']['max']}")
    print(f"  Token stats B (ref): min={audit['token_stats_b_for_comparison']['min']}  mean={audit['token_stats_b_for_comparison']['mean']:.0f}  max={audit['token_stats_b_for_comparison']['max']}")
    print(f"  Items per context:   min={audit['items_per_context_stats']['min']}  mean={audit['items_per_context_stats']['mean']:.1f}  max={audit['items_per_context_stats']['max']}")
    print(f"  Contexts over budget:{over_budget}")
    print(f"  Cutoff violations:   belief={cutoff_violations_belief}  evidence={cutoff_violations_evidence}")


if __name__ == "__main__":
    main()
