"""
Generate the synthetic events file for the thesis-radar demo.

All content is invented. No real companies, products, teams, or notes.

Re-run with:
    python examples/thesis_radar/generate_synthetic_data.py
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path


# Each theme gets a (train_outcome_pattern, test_outcome_pattern) and a list of
# thesis-snippet templates. The patterns are deliberately mixed - some themes
# stay consistent (-> PROMOTE candidates), some shift (-> WEAKENED / INVERT
# candidates), some are noisy throughout (-> MONITOR / RECLUSTER candidates).
#
# Each snippet is a short, forward-looking *thesis* an organization might track
# over time. The outcome label is the strength of supporting evidence observed
# in that window: high / moderate / quiet.

THEMES = [
    # tag, train (6 outcomes), test (4 outcomes), snippets
    (
        "ai_assisted_development",
        ["high","high","high","high","moderate","high"],
        ["high","high","high","high"],
        [
            "AI pair-programming shortening onboarding time for new engineers",
            "Teams using AI code review catching more regressions pre-merge",
            "Autocomplete adoption correlating with faster feature delivery",
            "AI-generated test scaffolds reducing time-to-first-test",
            "Documentation assistants cutting time spent searching internal wikis",
            "AI triage of error logs speeding incident diagnosis",
            "Refactoring assistants enabling larger safe code changes",
            "Natural-language data queries broadening access across roles",
            "AI design review surfacing edge cases earlier in the cycle",
            "Prompt-driven scaffolding standardizing new-service setup",
        ],
    ),
    (
        "remote_collaboration",
        ["high","high","high","moderate","high","high"],
        ["moderate","moderate","quiet","moderate"],
        [
            "Async standups reducing meeting load without losing alignment",
            "Recorded design reviews improving cross-timezone participation",
            "Shared docs replacing status meetings for routine updates",
            "Virtual whiteboards sustaining ideation quality remotely",
            "Distributed on-call coverage improving incident response times",
            "Written decision logs reducing repeated context-setting",
            "Remote pairing sessions maintaining code-review throughput",
            "Quarterly in-person offsites restoring cross-team rapport",
            "Time-shifted handoffs keeping work moving around the clock",
            "Lightweight check-ins preserving team cohesion remotely",
        ],
    ),
    (
        "platform_reliability",
        ["moderate","moderate","moderate","high","moderate","moderate"],
        ["high","high","high","moderate"],
        [
            "Error-budget policies discouraging risky deploy timing",
            "Progressive rollouts catching regressions before full release",
            "Automated rollback shrinking incident blast radius",
            "Chaos drills surfacing hidden single points of failure",
            "SLO dashboards aligning teams on user-facing reliability",
            "Dependency health checks preventing cascading outages",
            "Load-shedding policies preserving core flows under spikes",
            "Canary analysis flagging latency regressions automatically",
            "Runbook automation cutting mean-time-to-recovery",
            "Capacity headroom reviews preventing saturation incidents",
        ],
    ),
    (
        "data_privacy_caution",
        ["quiet","quiet","moderate","quiet","quiet","moderate"],
        ["quiet","quiet","quiet","moderate"],
        [
            "Teams pausing a data-sharing feature pending policy review",
            "Stricter retention defaults slowing an analytics rollout",
            "Consent-flow rework delaying a personalization launch",
            "Cross-region data rules narrowing a planned integration",
            "Audit requirements deferring a logging expansion",
            "PII-handling review postponing a vendor onboarding",
            "Access-scope tightening pausing an internal data portal",
            "Anonymization work delaying a research dataset release",
            "Policy uncertainty holding back a telemetry change",
            "Review backlog slowing approval of new data joins",
        ],
    ),
    (
        "operations_automation",
        ["moderate","moderate","moderate","high","moderate","moderate"],
        ["high","high","high","high"],
        [
            "Self-service provisioning reducing infra ticket volume",
            "Automated dependency updates lowering the security backlog",
            "Policy-as-code catching misconfigurations pre-deploy",
            "Scheduled cost reviews trimming idle resource spend",
            "Auto-scaling policies smoothing traffic-spike handling",
            "Templated pipelines speeding new-service rollout",
            "Automated access reviews shrinking standing permissions",
            "Drift detection keeping environments reproducible",
            "One-click rollback reducing change-related incidents",
            "Automated runbooks cutting manual on-call toil",
        ],
    ),
    (
        "open_source_adoption",
        ["high","high","high","high","moderate","high"],
        ["high","high","high","moderate"],
        [
            "Adopting a shared OSS framework reducing duplicate tooling",
            "Upstreaming patches lowering long-term maintenance cost",
            "Community plugins covering gaps faster than in-house builds",
            "An OSS observability stack matching commercial feature needs",
            "Standard OSS formats easing cross-team data exchange",
            "Public roadmaps improving planning around dependencies",
            "OSS contribution time strengthening the recruiting pipeline",
            "Shared libraries reducing per-team boilerplate",
            "Vendor-neutral standards reducing lock-in risk",
            "Active maintainer communities shortening bug-fix turnaround",
        ],
    ),
    (
        "emerging_runtime_patterns",
        ["moderate","high","quiet","moderate","quiet","moderate"],
        ["moderate","quiet","moderate","quiet"],
        [
            "Edge inference cutting round-trip latency for some features",
            "Streaming responses improving perceived responsiveness",
            "Local caching layers reducing backend load unevenly",
            "Background pre-fetching helping some flows, hurting others",
            "Speculative execution trimming tail latency inconsistently",
            "On-device models reducing server cost for light tasks",
            "Hybrid retrieval improving answer quality variably",
            "Warm pools reducing cold-start latency at idle cost",
            "Adaptive batching trading throughput against latency",
            "Incremental rendering improving first-paint times",
        ],
    ),
    (
        "security_posture",
        ["moderate","high","moderate","moderate","moderate","high"],
        ["moderate","moderate","moderate","high"],
        [
            "Mandatory MFA reducing account-takeover incidents",
            "Secret scanning catching credential leaks pre-commit",
            "Least-privilege defaults shrinking breach blast radius",
            "Dependency pinning reducing supply-chain exposure",
            "Phishing drills improving report rates over time",
            "Automated patching closing known-CVE windows faster",
            "Threat-model reviews surfacing design-stage risks",
            "Hardware keys reducing successful credential phishing",
            "Egress controls limiting data-exfiltration paths",
            "Continuous access reviews removing stale permissions",
        ],
    ),
]


def main(out_path: Path):
    base_date = datetime(2026, 2, 1, 9, 0, 0)
    # Spread events: theme i, event j -> day = j * 9 + (i % 3) so they interleave
    events: list[dict] = []
    eid = 1
    for theme_idx, (tag, train_o, test_o, snippets) in enumerate(THEMES):
        outcomes = train_o + test_o
        assert len(outcomes) == len(snippets) == 10
        for j, (snippet, outcome) in enumerate(zip(snippets, outcomes)):
            day_offset = j * 9 + (theme_idx % 3)  # 0..81-ish, well inside Feb-Apr window
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
        f.write("# No real companies, products, teams, or notes.\n")
        for e in events:
            f.write(json.dumps(e) + "\n")
    print(f"wrote {len(events)} synthetic events -> {out_path}")


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    main(here / "data" / "synthetic_events.jsonl")
