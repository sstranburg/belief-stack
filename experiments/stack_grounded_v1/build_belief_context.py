#!/usr/bin/env python3
"""
Stack-Grounded Retrieval v0.1 — Belief context builder (System B).

For each question in questions.jsonl, retrieves belief objects from
belief_objects.jsonl with:
  - actor match (belief.actor == question.ticker), PLUS
  - theme expansion (beliefs sharing stable_cluster_id with actor matches)
Filtered by cutoff (belief.last_updated <= T; evidence_refs further filtered
to chunks with timestamp <= T), ranked by warrant + currency rules, packed
into the same locked token budget as System A.

Locked parameters (v0.1):
  - Token budget:                 6000 tokens (cl100k_base)
  - Tokenizer:                    tiktoken cl100k_base
  - Theme-expansion cap:          50 secondary (theme-only) beliefs per question
  - Evidence_refs per belief in render: up to 5 sample chunk_ids
                                  (full list retained in record for audit)

Ranking (rule-based, documented before answer generation):
  1. Match type:        actor_match > theme_only
  2. Coverage status:   IN_DISTRIBUTION > PARTIAL > OUT_OF_DISTRIBUTION
  3. Lifecycle state:   non-retired > retired
                        EXCEPTION: when question.category == 'stale_assumption',
                        retired beliefs are the target — they get a small
                        boost rather than a penalty.
  4. Recency:           larger last_updated (closer to cutoff) ranks higher
  5. Warrant strength:  support_n * confidence (combined warrant score)

Constraints honored:
  - No LLM generation. No embedding API call (rule-based ranking only).
  - Per-question evidence_cutoff applied to belief.last_updated AND to
    each belief's evidence_refs (chunk join, timestamp <= T).
  - Identical token budget to System A.
  - NO answer_guidance, prompt_hint, caution_note rendered into the payload.
    The belief object's structured fields are presented as-is.

Outputs:
  stack_grounded_v1/data/contexts_b.jsonl
  stack_grounded_v1/data/context_b_audit.json
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter, defaultdict

import tiktoken

ROOT       = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent

BELIEFS_PATH    = ROOT / "data" / "belief_objects.jsonl"
CHUNKS_PATH     = ROOT / "data" / "chunk_substrate.jsonl"
QUESTIONS_PATH  = ROOT / "questions.jsonl"
OUT_CONTEXTS    = ROOT / "data" / "contexts_b.jsonl"
OUT_AUDIT       = ROOT / "data" / "context_b_audit.json"

TOKEN_BUDGET            = 6000
TOKENIZER               = "cl100k_base"
THEME_SECONDARY_CAP     = 50
EVIDENCE_SAMPLE_RENDER  = 5     # how many evidence_refs to include in the rendered block

COVERAGE_RANK = {"IN_DISTRIBUTION": 0, "PARTIAL": 1, "OUT_OF_DISTRIBUTION": 2}
LIFECYCLE_NON_RETIRED = {"born", "active", "reconfirmed", "weakened", "contradicted"}


def load_jsonl(path: pathlib.Path) -> list[dict]:
    out = []
    with path.open() as f:
        for line in f:
            out.append(json.loads(line))
    return out


def index_chunks_by_id(chunks: list[dict]) -> dict[str, dict]:
    return {c["chunk_id"]: c for c in chunks}


def index_beliefs(beliefs: list[dict]):
    """
    Return:
      by_actor:  ticker -> list of beliefs
      by_theme:  stable_cluster_id -> list of beliefs
      by_id:     belief_id -> belief
    """
    by_actor: dict[str, list[dict]] = defaultdict(list)
    by_theme: dict[str, list[dict]] = defaultdict(list)
    by_id: dict[str, dict] = {}
    for b in beliefs:
        by_actor[b["actor"]].append(b)
        theme = b.get("theme", "")
        if theme:
            by_theme[theme].append(b)
        by_id[b["belief_id"]] = b
    return by_actor, by_theme, by_id


def filter_belief_by_cutoff(b: dict, cutoff: str, chunks_by_id: dict[str, dict]) -> dict | None:
    """
    Per pre-reg §5.2: belief.last_updated <= cutoff AND filter evidence_refs
    to chunks whose timestamp <= cutoff. Returns a cutoff-projected copy,
    or None if belief.last_updated > cutoff.
    """
    last_updated = b.get("last_updated") or ""
    if last_updated > cutoff:
        return None
    # Filter evidence_refs by chunk timestamp
    filtered_ev = []
    filtered_counter = []
    for ev_id in b.get("evidence_refs") or []:
        c = chunks_by_id.get(ev_id)
        if c and (c["timestamp"] or "")[:10] <= cutoff:
            filtered_ev.append(ev_id)
    for ev_id in b.get("counterevidence_refs") or []:
        c = chunks_by_id.get(ev_id)
        if c and (c["timestamp"] or "")[:10] <= cutoff:
            filtered_counter.append(ev_id)
    # Recompute source_mix from filtered evidence_refs
    src_mix: dict[str, int] = {}
    for ev_id in filtered_ev:
        c = chunks_by_id.get(ev_id)
        if c:
            src_mix[c["source"]] = src_mix.get(c["source"], 0) + 1
    out = dict(b)
    out["evidence_refs"] = filtered_ev
    out["counterevidence_refs"] = filtered_counter
    out["source_mix"] = src_mix
    out["_support_n_post_cutoff"] = len(filtered_ev)   # informational; not in schema
    return out


def rank_score(b: dict, match_type: str, cutoff: str, category: str) -> tuple:
    """
    Returns a sort key tuple; lower-is-better in Python sort.
    Encodes the documented ranking rules.
    """
    # 1. Match type
    match_rank = 0 if match_type == "actor_match" else 1

    # 2. Coverage status
    cov_rank = COVERAGE_RANK.get(b.get("coverage_status", ""), 99)

    # 3. Lifecycle state — non-retired ranks higher EXCEPT for stale_assumption
    lifecycle = b.get("lifecycle_state", "")
    if category == "stale_assumption":
        # Retired beliefs are the point of stale-assumption questions
        lifecycle_rank = 0 if lifecycle == "retired" else 1
    else:
        lifecycle_rank = 0 if lifecycle in LIFECYCLE_NON_RETIRED else 1

    # 4. Recency — newer last_updated (closer to cutoff) ranks higher.
    # Encode as negative days-until-cutoff so smaller-is-better matches "newer".
    last_updated = b.get("last_updated") or ""
    # Use string sort: lexically larger (later) date should rank higher.
    # Convert to negative ordinal-ish: we want larger last_updated to give
    # smaller sort key. Use cutoff as reference, take days_before_cutoff.
    days_before_cutoff = _days_between(last_updated, cutoff)

    # 5. Warrant strength — support_n * confidence; larger = better.
    support_n  = b.get("support_n") or 0
    confidence = b.get("confidence") or 0.0
    warrant = support_n * confidence
    warrant_rank = -warrant  # negative so larger warrant => smaller key

    return (match_rank, cov_rank, lifecycle_rank, days_before_cutoff, warrant_rank)


def _days_between(d_earlier: str, d_later: str) -> int:
    """Days between two YYYY-MM-DD strings. Returns positive if d_later > d_earlier."""
    from datetime import datetime
    try:
        de = datetime.strptime(d_earlier[:10], "%Y-%m-%d")
        dl = datetime.strptime(d_later[:10], "%Y-%m-%d")
        return (dl - de).days
    except (ValueError, TypeError):
        return 9999


def render_belief(b: dict) -> str:
    """
    Compact structured rendering of a belief object. Includes evidence_refs
    as a count + sample so the LLM can ask for specific chunks if it wants
    (in v0.1 it cannot; this is just substrate transparency). NO instruction
    text, NO answer_guidance.
    """
    actor = b.get("actor", "")
    theme = b.get("theme", "")
    claim = (b.get("claim") or "").strip()
    cov = b.get("coverage_status", "")
    conf = b.get("confidence")
    sup = b.get("support_n", 0)
    state = b.get("lifecycle_state", "")
    first_seen = b.get("first_seen", "")
    last_updated = b.get("last_updated", "")
    ev_refs = b.get("evidence_refs") or []
    counter_refs = b.get("counterevidence_refs") or []
    src_mix = b.get("source_mix") or {}

    line = f"BELIEF [{b['belief_id']}] {actor} (theme={theme}) — \"{claim}\""
    line += f"\n  warrant: {cov} (confidence={conf:.2f}, support_n={sup})"
    line += f"\n  state:   {state} (first_seen {first_seen}, last_updated {last_updated})"
    if src_mix:
        src_line = ", ".join(f"{k}:{v}" for k, v in sorted(src_mix.items(), key=lambda kv: -kv[1]))
        line += f"\n  sources: {src_line}"
    if ev_refs:
        sample = ev_refs[:EVIDENCE_SAMPLE_RENDER]
        more = f" (+{len(ev_refs) - len(sample)} more)" if len(ev_refs) > len(sample) else ""
        line += f"\n  evidence_refs ({len(ev_refs)}): {', '.join(sample)}{more}"
    else:
        line += f"\n  evidence_refs: none"
    if counter_refs:
        sample = counter_refs[:EVIDENCE_SAMPLE_RENDER]
        more = f" (+{len(counter_refs) - len(sample)} more)" if len(counter_refs) > len(sample) else ""
        line += f"\n  counterevidence ({len(counter_refs)}): {', '.join(sample)}{more}"
    return line


def main() -> None:
    print(f"Loading beliefs from {BELIEFS_PATH}…")
    beliefs = load_jsonl(BELIEFS_PATH)
    print(f"  {len(beliefs):,} beliefs")

    print(f"Loading chunks from {CHUNKS_PATH}…")
    chunks = load_jsonl(CHUNKS_PATH)
    chunks_by_id = index_chunks_by_id(chunks)
    print(f"  {len(chunks):,} chunks indexed")

    print(f"Loading questions from {QUESTIONS_PATH}…")
    questions = load_jsonl(QUESTIONS_PATH)
    print(f"  {len(questions):,} questions")

    by_actor, by_theme, by_id = index_beliefs(beliefs)

    enc = tiktoken.get_encoding(TOKENIZER)

    out_records: list[dict] = []
    token_stats: list[int] = []
    item_stats: list[int] = []
    actor_match_pool_stats: list[int] = []
    theme_match_pool_stats: list[int] = []
    items_post_cutoff_stats: list[int] = []

    for q in questions:
        cutoff = q["evidence_cutoff"]
        ticker = q["ticker"]
        category = q["category"]

        # 1. Actor matches
        actor_candidates = list(by_actor.get(ticker, []))
        actor_match_pool_stats.append(len(actor_candidates))

        # 2. Theme expansion — themes drawn from actor matches, excluding
        # beliefs already in the actor set
        themes = {b["theme"] for b in actor_candidates if b.get("theme")}
        actor_belief_ids = {b["belief_id"] for b in actor_candidates}
        theme_candidates: list[dict] = []
        for theme in themes:
            for b in by_theme.get(theme, []):
                if b["belief_id"] in actor_belief_ids:
                    continue
                theme_candidates.append(b)
        # Dedupe theme matches by belief_id, cap to THEME_SECONDARY_CAP
        seen_theme: set[str] = set()
        deduped_theme: list[dict] = []
        for b in theme_candidates:
            if b["belief_id"] in seen_theme:
                continue
            seen_theme.add(b["belief_id"])
            deduped_theme.append(b)
        theme_candidates = deduped_theme[:THEME_SECONDARY_CAP]
        theme_match_pool_stats.append(len(theme_candidates))

        # 3. Apply cutoff to both pools
        cutoff_filtered: list[tuple[dict, str]] = []  # (belief, match_type)
        for b in actor_candidates:
            proj = filter_belief_by_cutoff(b, cutoff, chunks_by_id)
            if proj is not None:
                cutoff_filtered.append((proj, "actor_match"))
        for b in theme_candidates:
            proj = filter_belief_by_cutoff(b, cutoff, chunks_by_id)
            if proj is not None:
                cutoff_filtered.append((proj, "theme_only"))
        items_post_cutoff_stats.append(len(cutoff_filtered))

        # 4. Rank
        cutoff_filtered.sort(key=lambda bm: rank_score(bm[0], bm[1], cutoff, category))

        # 5. Pack into token budget
        items: list[dict] = []
        running_tokens = 0
        for b, mt in cutoff_filtered:
            rendered = render_belief(b)
            tok = len(enc.encode(rendered))
            if running_tokens + tok > TOKEN_BUDGET:
                continue
            # Build the per-item record; preserve full evidence_refs for audit
            items.append({
                "belief_id":            b["belief_id"],
                "actor":                b["actor"],
                "theme":                b.get("theme", ""),
                "claim":                b["claim"],
                "coverage_status":      b["coverage_status"],
                "confidence":           b["confidence"],
                "support_n":            b["support_n"],
                "lifecycle_state":      b["lifecycle_state"],
                "first_seen":           b["first_seen"],
                "last_updated":         b["last_updated"],
                "evidence_refs":        b["evidence_refs"],
                "counterevidence_refs": b["counterevidence_refs"],
                "source_mix":           b["source_mix"],
                "match_type":           mt,
                "tokens":               tok,
                "rendered":             rendered,
            })
            running_tokens += tok

        token_stats.append(running_tokens)
        item_stats.append(len(items))

        out_records.append({
            "question_id":                 q["question_id"],
            "question":                    q["question"],
            "category":                    q["category"],
            "ticker":                      q["ticker"],
            "evidence_cutoff":             cutoff,
            "system":                      "B",
            "retrieval_method":            "rule_based",
            "ranking":                     "match_type > coverage > lifecycle(category-aware) > recency > warrant",
            "token_budget":                TOKEN_BUDGET,
            "token_count":                 running_tokens,
            "items_count":                 len(items),
            "actor_match_pool":            len(actor_candidates),
            "theme_secondary_pool":        len(theme_candidates),
            "items_post_cutoff":           len(cutoff_filtered),
            "items_truncated_for_budget":  max(len(cutoff_filtered) - len(items), 0),
            "items":                       items,
        })

    out_records.sort(key=lambda r: r["question_id"])

    OUT_CONTEXTS.parent.mkdir(exist_ok=True)
    with OUT_CONTEXTS.open("w") as f:
        for r in out_records:
            f.write(json.dumps(r) + "\n")
    print(f"\nWrote {OUT_CONTEXTS}")

    audit = {
        "system":               "B",
        "schema_version":       "v0.1",
        "tokenizer":            TOKENIZER,
        "token_budget":         TOKEN_BUDGET,
        "theme_secondary_cap":  THEME_SECONDARY_CAP,
        "evidence_sample_render": EVIDENCE_SAMPLE_RENDER,
        "ranking_rules": [
            "1. match_type:        actor_match > theme_only",
            "2. coverage_status:   IN_DISTRIBUTION > PARTIAL > OUT_OF_DISTRIBUTION",
            "3. lifecycle_state:   non-retired > retired (INVERTED for stale_assumption category)",
            "4. recency:           closer last_updated to cutoff ranks higher",
            "5. warrant_strength:  support_n * confidence (descending)",
        ],
        "questions_processed":  len(out_records),
        "token_stats": {
            "min":  int(min(token_stats)) if token_stats else None,
            "mean": float(sum(token_stats)/len(token_stats)) if token_stats else None,
            "max":  int(max(token_stats)) if token_stats else None,
            "p50":  int(sorted(token_stats)[len(token_stats)//2]) if token_stats else None,
        },
        "items_per_context_stats": {
            "min":  int(min(item_stats)) if item_stats else None,
            "mean": float(sum(item_stats)/len(item_stats)) if item_stats else None,
            "max":  int(max(item_stats)) if item_stats else None,
        },
        "actor_match_pool_stats": {
            "min":  int(min(actor_match_pool_stats)) if actor_match_pool_stats else None,
            "mean": float(sum(actor_match_pool_stats)/len(actor_match_pool_stats)) if actor_match_pool_stats else None,
            "max":  int(max(actor_match_pool_stats)) if actor_match_pool_stats else None,
        },
        "theme_secondary_pool_stats": {
            "min":  int(min(theme_match_pool_stats)) if theme_match_pool_stats else None,
            "mean": float(sum(theme_match_pool_stats)/len(theme_match_pool_stats)) if theme_match_pool_stats else None,
            "max":  int(max(theme_match_pool_stats)) if theme_match_pool_stats else None,
        },
        "items_post_cutoff_stats": {
            "min":  int(min(items_post_cutoff_stats)) if items_post_cutoff_stats else None,
            "mean": float(sum(items_post_cutoff_stats)/len(items_post_cutoff_stats)) if items_post_cutoff_stats else None,
            "max":  int(max(items_post_cutoff_stats)) if items_post_cutoff_stats else None,
        },
        "questions_under_budget":   sum(1 for t in token_stats if t < TOKEN_BUDGET * 0.5),
        "questions_at_budget":      sum(1 for t in token_stats if t >= TOKEN_BUDGET * 0.9),
        "cutoff_distribution":      dict(Counter(r["evidence_cutoff"] for r in out_records)),
        "category_distribution":    dict(Counter(r["category"] for r in out_records)),
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"Wrote {OUT_AUDIT}")

    print()
    print(f"  tokens per context  min/mean/max:  {audit['token_stats']['min']} / {audit['token_stats']['mean']:.0f} / {audit['token_stats']['max']}")
    print(f"  items  per context  min/mean/max:  {audit['items_per_context_stats']['min']} / {audit['items_per_context_stats']['mean']:.1f} / {audit['items_per_context_stats']['max']}")
    print(f"  actor pool          min/mean/max:  {audit['actor_match_pool_stats']['min']} / {audit['actor_match_pool_stats']['mean']:.1f} / {audit['actor_match_pool_stats']['max']}")
    print(f"  theme pool          min/mean/max:  {audit['theme_secondary_pool_stats']['min']} / {audit['theme_secondary_pool_stats']['mean']:.1f} / {audit['theme_secondary_pool_stats']['max']}")
    print(f"  questions at-budget (>=90%):       {audit['questions_at_budget']}")
    print(f"  questions under-budget (<50%):     {audit['questions_under_budget']}")


if __name__ == "__main__":
    main()
