"""
Generate the synthetic MS Teams chatter file for the synthetic-themes demo.

Uses the configured LLM (OPENAI_API_KEY + OPENAI_MODEL from env) to produce
realistic-sounding internal Teams chatter across eight organizational
sensemaking themes. The snippets are short paraphrased meeting notes / chat
messages / standup callouts. All content is invented; the generator does not
see or pull from any real source.

Each theme has a planned train/test outcome pattern designed to seed a mix
of lifecycle transitions in the multi-pass demo:

    - some themes stay consistent  (-> PROMOTE candidates)
    - some shift modal outcome     (-> STRENGTHENED / WEAKENED / INVERTED)
    - some are noisy throughout    (-> MONITOR / RECLUSTER)

Output JSONL conforms to the Event schema:
    {id, timestamp, text, metadata{tag, source}, outcome}

The LLM is called once per theme (8 calls total). Each call returns a JSON
object containing 10 snippets, one per pre-assigned outcome. Cached to JSONL;
the demo reads from the cache and does not re-call the LLM.

Re-run with:
    export OPENAI_API_KEY=sk-...
    python examples/teams_sensemaking/generate_synthetic_data.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Make this script runnable directly (without `pip install -e .`).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Local helper (sibling module).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _llm_client import chat_model, get_client


# Outcome label space for this substrate.
#   escalated - theme moved up in priority / drew formal attention
#   resolved  - theme was addressed and closed out
#   stalled   - theme went dormant without resolution

# Eight cross-functional organizational themes that recur in Teams chatter.
# tag, train (6 outcomes), test (4 outcomes), human description for the LLM.
THEMES = [
    (
        "customer_escalation_pattern",
        ["escalated","escalated","escalated","escalated","resolved","escalated"],
        ["escalated","escalated","escalated","escalated"],
        "A cluster of customer-side escalation signals coming through sales, "
        "support, CSMs, and exec channels. Things like ticket spikes, account "
        "risk callouts, executive-sponsor requests, incident triage calls.",
    ),
    (
        "vendor_renewal_friction",
        ["escalated","escalated","escalated","resolved","escalated","escalated"],
        ["resolved","resolved","stalled","resolved"],
        "Contract / renewal friction with an external vendor. Procurement, "
        "legal, finance, and engineering chatter about contract terms, "
        "switching cost, alternative providers, renewal decision.",
    ),
    (
        "platform_migration_concerns",
        ["resolved","resolved","resolved","escalated","resolved","resolved"],
        ["escalated","escalated","escalated","resolved"],
        "A migration to a new platform / system. SRE, architecture, pilot "
        "users, and engineering managers raising concerns and resolutions "
        "across the rollout window.",
    ),
    (
        "budget_pressure_signals",
        ["stalled","stalled","resolved","stalled","stalled","resolved"],
        ["stalled","stalled","stalled","resolved"],
        "Budget-pressure signals from Finance and Procurement. Spend "
        "forecast requests, approval-flow friction, cancelled meetings, "
        "budget-freeze rumors that quietly stagnate without official action.",
    ),
    (
        "staffing_capacity_pressure",
        ["resolved","resolved","resolved","escalated","resolved","resolved"],
        ["escalated","escalated","escalated","escalated"],
        "Staffing capacity signals. Open req gaps, on-call burnout, attrition "
        "risk, hiring-manager and recruiting chatter, skip-levels surfacing "
        "team-load concerns.",
    ),
    (
        "compliance_audit_findings",
        ["escalated","escalated","escalated","escalated","resolved","escalated"],
        ["escalated","escalated","escalated","resolved"],
        "An external compliance / audit cycle producing findings. Compliance "
        "officer, legal, audit-team, and engineering chatter about gaps, "
        "remediation plans, severity, briefings.",
    ),
    (
        "team_restructure_signals",
        ["resolved","escalated","stalled","resolved","stalled","escalated"],
        ["resolved","stalled","resolved","stalled"],
        "Reorganization / restructure signals around an org-chart change. "
        "Leadership announcements, HR listening sessions, manager 1:1s, "
        "internal-forum reactions, mixed clarity on reporting lines.",
    ),
    (
        "product_launch_readiness",
        ["resolved","escalated","resolved","resolved","resolved","escalated"],
        ["resolved","resolved","resolved","escalated"],
        "Pre-GA product launch readiness. P1 blockers, marketing/PM/eng "
        "coordination, launch-readiness review meetings, signoffs and "
        "remaining issues in the run-up to go-live.",
    ),
]


_SYSTEM_PROMPT = (
    "You generate short paraphrased snippets of internal MS Teams chatter at "
    "a mid-sized tech company. Each snippet reads like a meeting note, chat "
    "message, or standup callout. You avoid named real entities, do not use "
    "quotes, and keep snippets to one sentence (12-22 words). You vary "
    "speaker roles (engineering lead, PM, finance director, CSM, support "
    "manager, VP, HR partner, etc.) across the set so they do not sound "
    "repetitive."
)


def _build_user_prompt(tag: str, description: str, outcomes: list[str]) -> str:
    listing = "\n".join(
        f"  {i+1}. outcome={o!r}" for i, o in enumerate(outcomes)
    )
    return f"""Theme: {tag}
Description: {description}

Generate exactly 10 snippets for this theme. Each has a pre-assigned outcome
label that describes what actually happened to the theme in the period after
that signal was observed:

  escalated  - theme moved up in priority / drew formal attention
  resolved   - theme was addressed and closed out
  stalled    - theme went dormant without resolution

The outcomes in order are:
{listing}

The snippet text itself describes a moment in the theme's chatter; it does
NOT need to literally narrate the outcome. (A snippet labeled `resolved` can
read like a problem report; the outcome reflects what came next.)

Return JSON with this shape (and no extra fields):

{{
  "snippets": [
    {{"i": 1, "outcome": "<assigned label>", "text": "<single-sentence snippet>"}},
    ...
    {{"i": 10, "outcome": "<assigned label>", "text": "<single-sentence snippet>"}}
  ]
}}

Do not prefix snippet text with quotes or with "Synthetic:"."""


def _llm_generate_snippets(tag: str, description: str, outcomes: list[str]) -> list[str]:
    """One LLM call -> 10 snippets for this theme."""
    client = get_client()
    resp = client.chat.completions.create(
        model           = chat_model(),
        response_format = {"type": "json_object"},
        temperature     = 0.8,
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": _build_user_prompt(tag, description, outcomes)},
        ],
    )
    raw = resp.choices[0].message.content or "{}"
    payload = json.loads(raw)
    items = payload.get("snippets", [])
    if len(items) < 10:
        raise RuntimeError(
            f"theme {tag!r}: LLM returned {len(items)} snippets, expected 10"
        )
    # Trust the order; fall back to enumeration if `i` is missing.
    items_sorted = sorted(items, key=lambda x: x.get("i", 0))[:10]
    return [str(x.get("text", "")).strip() for x in items_sorted]


def main(out_path: Path):
    base_date = datetime(2026, 2, 1, 9, 0, 0)
    events: list[dict] = []
    eid = 1

    print(f"generating snippets via {chat_model()}  (8 themes x 10 = 80 snippets, "
          f"8 LLM calls total)")
    for theme_idx, (tag, train_o, test_o, description) in enumerate(THEMES):
        outcomes = train_o + test_o
        assert len(outcomes) == 10
        print(f"  [{theme_idx+1}/8] {tag} ...", end=" ", flush=True)
        snippets = _llm_generate_snippets(tag, description, outcomes)
        print(f"ok ({len(snippets)})")
        for j, (snippet, outcome) in enumerate(zip(snippets, outcomes)):
            day_offset = j * 9 + (theme_idx % 3)
            ts = base_date + timedelta(days=day_offset, hours=(theme_idx * 2) % 8)
            events.append({
                "id":        f"synth-{eid:03d}",
                "timestamp": ts.isoformat(timespec="seconds"),
                "text":      f"SYNTHETIC: {snippet}",
                "metadata":  {"tag": tag, "source": "synthetic_generator"},
                "outcome":   outcome,
            })
            eid += 1

    events.sort(key=lambda d: d["timestamp"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        f.write("# SYNTHETIC DATA - generated by generate_synthetic_data.py\n")
        f.write("# Substrate: invented MS Teams chatter. No real entities appear.\n")
        for e in events:
            f.write(json.dumps(e) + "\n")
    print(f"\nwrote {len(events)} synthetic events -> {out_path}")


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    main(here / "data" / "synthetic_events.jsonl")
