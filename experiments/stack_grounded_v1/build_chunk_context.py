#!/usr/bin/env python3
"""
Stack-Grounded Retrieval v0.1 — Chunk context builder (System A).

For each question in questions.jsonl, retrieves top-K chunks from
chunk_substrate.jsonl using dense embedding similarity, filters to
chunks with timestamp <= evidence_cutoff, and packs into a context
payload bounded by the locked token budget.

Locked parameters (v0.1):
  - Embedding model:        text-embedding-3-small (OpenAI)
  - Embedding dimensions:   1536 (default for the model)
  - Token budget:           6000 tokens (cl100k_base tokenizer)
  - Retrieval pool size:    150 candidates pre-cutoff, then filter
  - Tokenizer:              tiktoken cl100k_base
  - Embedding cache:        stack_grounded_v1/data/chunk_embeddings.npz

The cached embedding matrix is re-used across runs; only the first run
incurs the OpenAI API call. The cache is keyed by chunk_id + model, so
substrate changes invalidate stale entries automatically.

Constraints honored:
  - No LLM generation (no answers produced; only embeddings + ranking).
  - Per-question evidence_cutoff enforced via chunk.timestamp filter
    BEFORE ranking (pre-reg §5.2: architectural, not post-hoc).
  - Identical token budget for both systems (§5.3); System B uses the
    same budget via build_belief_context.py.

Outputs:
  stack_grounded_v1/data/contexts_a.jsonl                (75 per-question contexts)
  stack_grounded_v1/data/chunk_embeddings.npz            (embedding cache)
  stack_grounded_v1/data/context_a_audit.json            (system A audit)
"""

from __future__ import annotations

import json
import os
import pathlib
import time
from collections import Counter

import numpy as np
import tiktoken
from dotenv import load_dotenv
from openai import OpenAI

ROOT       = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent

CHUNKS_PATH    = ROOT / "data" / "chunk_substrate.jsonl"
QUESTIONS_PATH = ROOT / "questions.jsonl"
EMB_CACHE      = ROOT / "data" / "chunk_embeddings.npz"
OUT_CONTEXTS   = ROOT / "data" / "contexts_a.jsonl"
OUT_AUDIT      = ROOT / "data" / "context_a_audit.json"

EMBED_MODEL        = "text-embedding-3-small"
EMBED_DIMS         = 1536
TOKEN_BUDGET       = 6000
TOKENIZER          = "cl100k_base"
PRE_CUTOFF_POOL_K  = 150     # candidates ranked by similarity before cutoff filter
BATCH_SIZE         = 256     # OpenAI batch size for embedding requests

load_dotenv(STORM_ROOT / ".env")


# --- Loaders ----------------------------------------------------------------

def load_chunks() -> list[dict]:
    chunks = []
    with CHUNKS_PATH.open() as f:
        for line in f:
            chunks.append(json.loads(line))
    return chunks


def load_questions() -> list[dict]:
    qs = []
    with QUESTIONS_PATH.open() as f:
        for line in f:
            qs.append(json.loads(line))
    return qs


# --- Embedding cache --------------------------------------------------------

def embed_text_for_chunk(chunk: dict) -> str:
    """The text we embed = title + (optional) text body, both stripped."""
    parts = []
    title = (chunk.get("title") or "").strip()
    if title:
        parts.append(title)
    text = (chunk.get("text") or "").strip()
    if text:
        parts.append(text)
    return "\n".join(parts) or chunk.get("chunk_id", "")


def load_or_build_chunk_embeddings(chunks: list[dict]) -> tuple[np.ndarray, list[str]]:
    """
    Returns (embedding_matrix [N x D], chunk_ids [N]) aligned to the chunks list.
    Uses .npz cache keyed on (chunk_id, model). Missing chunk_ids are embedded
    via the OpenAI API and the cache is updated.
    """
    cache: dict[str, np.ndarray] = {}
    if EMB_CACHE.exists():
        npz = np.load(EMB_CACHE, allow_pickle=True)
        cached_ids = list(npz["chunk_ids"])
        cached_mat = npz["embeddings"]
        cached_model = str(npz["model"]) if "model" in npz else None
        if cached_model == EMBED_MODEL and cached_mat.shape[1] == EMBED_DIMS:
            for i, cid in enumerate(cached_ids):
                cache[str(cid)] = cached_mat[i]
            print(f"  cache: loaded {len(cache):,} embeddings (model={cached_model})")
        else:
            print(f"  cache: stale (model mismatch); rebuilding")

    needed = [c for c in chunks if c["chunk_id"] not in cache]
    print(f"  cache: {len(needed):,} chunks need embedding")

    if needed:
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        t0 = time.time()
        for i in range(0, len(needed), BATCH_SIZE):
            batch = needed[i : i + BATCH_SIZE]
            texts = [embed_text_for_chunk(c) for c in batch]
            # OpenAI rejects empty strings — sub-in chunk_id as filler
            texts = [t if t else c["chunk_id"] for t, c in zip(texts, batch)]
            resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
            for c, item in zip(batch, resp.data):
                cache[c["chunk_id"]] = np.asarray(item.embedding, dtype=np.float32)
            done = min(i + BATCH_SIZE, len(needed))
            rate = done / max(time.time() - t0, 0.01)
            print(f"    embedded {done:,}/{len(needed):,}  ({rate:.0f} chunks/sec)")
        # Persist updated cache
        ids_sorted = sorted(cache.keys())
        mat = np.stack([cache[i] for i in ids_sorted]).astype(np.float32)
        np.savez_compressed(EMB_CACHE,
                            chunk_ids=np.array(ids_sorted, dtype=object),
                            embeddings=mat,
                            model=EMBED_MODEL)
        print(f"  cache: wrote {EMB_CACHE} ({mat.shape[0]:,} rows, {mat.nbytes/1e6:.1f} MB)")

    # Align matrix to incoming chunk order
    matrix = np.stack([cache[c["chunk_id"]] for c in chunks]).astype(np.float32)
    chunk_ids = [c["chunk_id"] for c in chunks]
    return matrix, chunk_ids


def embed_query(client: OpenAI, query: str) -> np.ndarray:
    resp = client.embeddings.create(model=EMBED_MODEL, input=[query])
    return np.asarray(resp.data[0].embedding, dtype=np.float32)


# --- Retrieval --------------------------------------------------------------

def normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    n = np.where(n == 0, 1, n)
    return v / n


def render_chunk(chunk: dict) -> str:
    """
    The chunk's grounding-payload rendering. Compact, source-attributed, no
    instructions. Same shape every time so the LLM can parse uniformly.
    """
    title = (chunk.get("title") or "").strip()
    text  = (chunk.get("text") or "").strip()
    actors = ", ".join(chunk.get("actors_primary") or [])
    ts = (chunk.get("timestamp") or "")[:10]
    src = chunk.get("source", "")
    body = f"[{chunk['chunk_id']} @ {ts} / {src}] \"{title}\"\n  actors: {actors}"
    if text:
        body += f"\n  body: {text}"
    return body


# --- Main -------------------------------------------------------------------

def main() -> None:
    print(f"Loading chunks from {CHUNKS_PATH}…")
    chunks = load_chunks()
    print(f"  {len(chunks):,} chunks")

    print(f"Loading questions from {QUESTIONS_PATH}…")
    questions = load_questions()
    print(f"  {len(questions):,} questions")

    print(f"Building/loading chunk embeddings (model={EMBED_MODEL})…")
    chunk_matrix, chunk_ids = load_or_build_chunk_embeddings(chunks)
    chunk_matrix = normalize(chunk_matrix)
    by_id = {c["chunk_id"]: c for c in chunks}

    enc = tiktoken.get_encoding(TOKENIZER)
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    print(f"Retrieving per-question contexts (budget={TOKEN_BUDGET} tokens)…")
    out_records: list[dict] = []
    token_stats: list[int] = []
    item_stats: list[int] = []
    items_pre_truncate: list[int] = []
    items_post_cutoff: list[int] = []

    for q in questions:
        cutoff = q["evidence_cutoff"]
        # Embed the question text
        q_emb = embed_query(client, q["question"])
        q_emb = normalize(q_emb.reshape(1, -1))[0]

        # Cosine similarity (normalized dot product)
        sims = chunk_matrix @ q_emb
        # Top-K candidates by similarity (before cutoff filter, to ensure
        # enough survive the cutoff)
        top_idx = np.argpartition(-sims, PRE_CUTOFF_POOL_K)[:PRE_CUTOFF_POOL_K]
        top_idx = top_idx[np.argsort(-sims[top_idx])]
        ranked_ids = [chunk_ids[i] for i in top_idx]

        # Apply cutoff filter: chunk.timestamp[:10] <= cutoff
        post_cutoff = [
            cid for cid in ranked_ids
            if (by_id[cid]["timestamp"] or "")[:10] <= cutoff
        ]
        items_post_cutoff.append(len(post_cutoff))

        # Pack into token budget
        items: list[dict] = []
        running_tokens = 0
        for cid in post_cutoff:
            c = by_id[cid]
            rendered = render_chunk(c)
            tok = len(enc.encode(rendered))
            if running_tokens + tok > TOKEN_BUDGET:
                continue  # try a smaller one; do NOT break (some later items may fit)
            items.append({
                "chunk_id":   c["chunk_id"],
                "timestamp":  c["timestamp"],
                "source":     c["source"],
                "title":      c["title"],
                "text":       c["text"],
                "actors_primary": c.get("actors_primary") or [],
                "tokens":     tok,
                "rendered":   rendered,
            })
            running_tokens += tok

        items_pre_truncate.append(len(post_cutoff))
        token_stats.append(running_tokens)
        item_stats.append(len(items))

        out_records.append({
            "question_id":              q["question_id"],
            "question":                 q["question"],
            "category":                 q["category"],
            "ticker":                   q["ticker"],
            "evidence_cutoff":          cutoff,
            "system":                   "A",
            "retrieval_method":         f"openai:{EMBED_MODEL}",
            "ranking":                  "cosine_similarity",
            "token_budget":             TOKEN_BUDGET,
            "token_count":              running_tokens,
            "items_count":              len(items),
            "items_pre_cutoff_pool":    PRE_CUTOFF_POOL_K,
            "items_post_cutoff":        len(post_cutoff),
            "items_truncated_for_budget": max(len(post_cutoff) - len(items), 0),
            "items":                    items,
        })

    # Sort by question_id for stable output
    out_records.sort(key=lambda r: r["question_id"])

    # Write contexts
    OUT_CONTEXTS.parent.mkdir(exist_ok=True)
    with OUT_CONTEXTS.open("w") as f:
        for r in out_records:
            f.write(json.dumps(r) + "\n")
    print(f"\nWrote {OUT_CONTEXTS}")

    # Audit
    audit = {
        "system":               "A",
        "schema_version":       "v0.1",
        "embedding_model":      EMBED_MODEL,
        "embedding_dims":       EMBED_DIMS,
        "tokenizer":            TOKENIZER,
        "token_budget":         TOKEN_BUDGET,
        "pre_cutoff_pool_k":    PRE_CUTOFF_POOL_K,
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
        "items_post_cutoff_stats": {
            "min":  int(min(items_post_cutoff)) if items_post_cutoff else None,
            "mean": float(sum(items_post_cutoff)/len(items_post_cutoff)) if items_post_cutoff else None,
            "max":  int(max(items_post_cutoff)) if items_post_cutoff else None,
        },
        "questions_under_budget": sum(1 for t in token_stats if t < TOKEN_BUDGET * 0.5),
        "questions_at_budget":    sum(1 for t in token_stats if t >= TOKEN_BUDGET * 0.9),
        "cutoff_distribution":    dict(Counter(r["evidence_cutoff"] for r in out_records)),
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"Wrote {OUT_AUDIT}")

    print()
    print(f"  tokens per context  min/mean/max:  {audit['token_stats']['min']} / {audit['token_stats']['mean']:.0f} / {audit['token_stats']['max']}")
    print(f"  items  per context  min/mean/max:  {audit['items_per_context_stats']['min']} / {audit['items_per_context_stats']['mean']:.1f} / {audit['items_per_context_stats']['max']}")
    print(f"  questions at-budget (>=90%):       {audit['questions_at_budget']}")
    print(f"  questions under-budget (<50%):     {audit['questions_under_budget']}")


if __name__ == "__main__":
    main()
