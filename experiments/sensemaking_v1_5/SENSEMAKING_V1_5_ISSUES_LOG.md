# Sensemaking v1.5 — Implementation issues log (v0.1)

Append-only log of ambiguities encountered during v1.5 implementation. Each entry records what the ambiguity was, what implementation decision was made, and whether the decision should be folded into v0.2 as a rule clarification.

Discipline: implementation does not silently interpret unclear rules. Any judgment call goes here; the v0.1 measurement is then reported with this log attached.

---

## I-001 — `backtest_history.parquet` has three variants per (date, ticker)

**Encountered:** 2026-05-29, during harness inspection.

**Pre-registration text (§5.1):**
> "The state assignment used for the row is the state recorded at T in `backtest_history.parquet` — i.e., the state computed by `generate_leaderboard.py` using data ≤ T. No re-computation. No look-ahead."

**What actually happened:** `backtest_history.parquet` contains three rows per (date, ticker), one per `variant`: `baseline`, `mid_floor`, `low_floor`. The pre-registration did not name a variant. Total rows: 11,328 = 3,776 (date, ticker) pairs × 3 variants.

**Interpretation decision:** Use the **`baseline`** variant exclusively for v0.1. Rationale: `baseline` is the leaderboard's canonical state (no NDS floor applied); the `mid_floor` and `low_floor` variants exist for strategy-lab eligibility experiments, not for the live leaderboard surface. The v1 case study's published state distributions match the `baseline` variant.

**v0.2 amendment candidate:** Pre-registration §5.1 should be amended to explicitly name `variant = "baseline"`. A separate v0.2 measurement could compare across variants if useful, but that is a different question from the locked v1.5 primary.

**Impact:** Primary universe reduces from 11,328 rows to 3,776 (date, ticker) pairs before per-§7 exclusions.

---

## I-002 — Universe gap: 42 actors in actors.json, 32 in backtest_history

**Encountered:** 2026-05-29, during harness inspection.

**Pre-registration text (§2.2):**
> "The 42 actors tracked in v1's `actors.json` snapshot."

**What actually happened:** `actors.json` lists 42 actors today, but `backtest_history.parquet` contains only 32 unique tickers across the window. The 10 missing tickers fall into two groups:

- **Pre-excluded experimentals** (per §2.2): USAR, ODC. Already excluded from primary by name.
- **Non-experimental but absent from backtest_history**: ALAB, CLS, COHR, MELI, SNDK, SOFI, WDC, ZETA. These appear to be post-window additions to actors.json (e.g., MELI was added during the 2026-05-29 evening pipeline). `backtest_history.parquet` was built before they joined the tracked set.

**Interpretation decision:** The v0.1 primary universe is restricted to actors actually present in `backtest_history.parquet` after §2.2 experimental-ticker exclusion. Concretely: **31 tickers** (32 minus MP, which is experimental and present in backtest_history).

This means the v1.5 measurement universe is a strict subset of the v1 case-study's published "42 actors." The discrepancy is real and reportable, not a methodology choice.

**v0.2 amendment candidate:** §2.2 should be amended to say "the actors present in v1's `backtest_history.parquet` snapshot at the start of the v1.5 measurement, excluding §2.2-named experimentals." That makes the universe definition operational and date-stable.

**Impact:** Primary universe = 31 tickers. The 8 non-experimental tickers absent from backtest_history (ALAB, CLS, COHR, MELI, SNDK, SOFI, WDC, ZETA) are excluded from primary and noted in the report's exclusion table. They cannot enter the secondary "experimental-tickers-included" sensitivity (§12.2) either, since the issue is data absence, not a §2.2 inclusion choice. A separate v0.2 measurement could re-build backtest_history including post-window tickers if useful.

---

(Entries appended below as they are encountered.)
