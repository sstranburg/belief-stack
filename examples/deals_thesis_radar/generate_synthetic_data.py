"""
Generate the synthetic events file for the Deals thesis-radar demo.

All content is invented. No real companies, deals, clients, or analyst notes.

Re-run with:
    python examples/deals_thesis_radar/generate_synthetic_data.py
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path


# Each theme gets a (train_outcome_pattern, test_outcome_pattern) and a list of
# thesis-snippet templates. The patterns are deliberately mixed - some themes
# stay consistent (-> PROMOTE candidates), some shift (-> WEAKENED / INVERT
# candidates), some are noisy throughout (-> MONITOR / RECLUSTER candidates).

THEMES = [
    # tag, train (6 outcomes), test (4 outcomes), snippets
    (
        "ai_infra_consolidation",
        ["high","high","high","high","moderate","high"],
        ["high","high","high","high"],
        [
            "GPU supply pressure prompting upstream chipmaker tie-up talks",
            "Hyperscaler said to be exploring captive silicon vendor purchase",
            "Networking switch maker drawing strategic interest from cloud incumbents",
            "Power-distribution vendor for data centers fielding inbound bids",
            "Cooling-systems firm in talks with private equity over majority sale",
            "Optical interconnect designer sees acquisition interest from two hyperscalers",
            "AI training-cluster integrator rumored to be in late-stage merger talks",
            "Storage-fabric startup approached about strategic acquisition",
            "Two regional colo operators discussing combination to serve AI demand",
            "Edge inference appliance vendor preparing for strategic process",
        ],
    ),
    (
        "healthcare_pe_rollups",
        ["high","high","high","moderate","high","high"],
        ["moderate","moderate","quiet","moderate"],
        [
            "Multi-site dermatology platform exploring sale to mid-market sponsor",
            "Outpatient surgery roll-up rumored to be running a process",
            "Specialty pharmacy chain reportedly fielding take-private interest",
            "PE sponsor said to be assembling primary-care clinic platform",
            "Veterinary services consolidator approached by strategic buyer",
            "Behavioral-health network in discussions about majority recap",
            "Home health agency cluster studying merger options",
            "Independent radiology group reviewing strategic alternatives",
            "Senior-living operator weighing take-private offer from PE",
            "Dental services organization said to be in process",
        ],
    ),
    (
        "energy_transition_ma",
        ["moderate","moderate","moderate","high","moderate","moderate"],
        ["high","high","high","moderate"],
        [
            "Battery storage developer rumored to be in talks with utility group",
            "Offshore wind operator fielding bids from infrastructure sponsors",
            "Solar EPC firm exploring strategic combination with rooftop installer",
            "Hydrogen electrolyzer maker drawing interest from industrial gas majors",
            "Grid software vendor said to be in advanced merger discussions",
            "EV-charging network operator in talks with energy retailer",
            "Carbon-capture services firm approached by oilfield services buyer",
            "Renewable developer reviewing partial-sale options for project pipeline",
            "Smart-meter integrator in process with infrastructure fund",
            "Geothermal developer drawing late-stage strategic interest",
        ],
    ),
    (
        "fintech_regulatory_pressure",
        ["quiet","quiet","moderate","quiet","quiet","moderate"],
        ["quiet","quiet","quiet","moderate"],
        [
            "BNPL provider scaling back deal exploration amid agency scrutiny",
            "Crypto-adjacent payments firm paused process after regulator letter",
            "Cross-border remittance startup retreated from sale talks",
            "Neobank reconsidering strategic alternatives after consent decree",
            "Embedded-finance vendor delayed bid timeline citing regulatory uncertainty",
            "Open-banking aggregator pulled from auction process",
            "Earned-wage-access provider postponed take-private talks",
            "Robo-advisor merger talks said to be on hold pending review",
            "Stablecoin-adjacent payments processor pausing strategic process",
            "Consumer lender said to have ended preliminary sale discussions",
        ],
    ),
    (
        "industrial_reshoring",
        ["moderate","moderate","moderate","high","moderate","moderate"],
        ["high","high","high","high"],
        [
            "Specialty metals fabricator drawing strategic interest amid reshoring push",
            "Domestic semiconductor packaging firm in advanced merger discussions",
            "Precision machining roll-up said to be in active process",
            "Automation systems integrator approached by industrial conglomerate",
            "Domestic battery-component supplier fielding bids",
            "Casting and forging operator exploring sale to PE sponsor",
            "Rail-car manufacturer in late-stage take-private talks",
            "Industrial coatings firm said to be in process with strategic buyer",
            "Tool and die consolidator approached by infrastructure fund",
            "Electrical equipment maker discussing combination with peer",
        ],
    ),
    (
        "software_take_privates",
        ["high","high","high","high","moderate","high"],
        ["high","high","high","moderate"],
        [
            "Vertical SaaS leader in talks with large-cap PE sponsor",
            "Application-monitoring vendor rumored to be running a process",
            "Workflow automation platform fielding take-private offers",
            "Field-service management software firm exploring strategic alternatives",
            "Data-integration vendor said to be in advanced take-private discussions",
            "Marketing-automation platform approached by PE consortium",
            "Identity-management vendor in late-stage take-private talks",
            "DevTools company reportedly running auction with select sponsors",
            "Compliance SaaS leader said to be in process",
            "Subscription-billing platform drawing interest from PE buyers",
        ],
    ),
    (
        "crypto_integration",
        ["moderate","high","quiet","moderate","quiet","moderate"],
        ["moderate","quiet","moderate","quiet"],
        [
            "Custody platform exploring acquisition by traditional broker-dealer",
            "On-chain analytics vendor in discussions with payments incumbent",
            "Tokenization infrastructure firm rumored to be in talks with bank",
            "Wallet provider approached by exchange operator",
            "Settlement-rail startup paused strategic process pending clarity",
            "DeFi-adjacent compliance vendor drawing strategic interest",
            "Stablecoin issuer considering combination with payments firm",
            "Mining-services provider exploring sale to energy buyer",
            "Crypto market-data vendor in discussions with financial-data firm",
            "Blockchain-analytics vendor approached by regtech buyer",
        ],
    ),
    (
        "cybersecurity_consolidation",
        ["moderate","high","moderate","moderate","moderate","high"],
        ["moderate","moderate","moderate","high"],
        [
            "Cloud-security vendor said to be running an auction process",
            "Identity-threat detection firm approached by platform vendor",
            "Email-security incumbent rumored to be in take-private talks",
            "Vulnerability-management vendor fielding strategic interest",
            "MDR provider in discussions with broader platform buyer",
            "Application-security testing firm exploring sale",
            "Data-security posture management vendor approached by PE",
            "SOAR vendor said to be in advanced merger discussions",
            "Container-security firm in talks with platform incumbent",
            "Zero-trust networking vendor reviewing strategic alternatives",
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
        f.write("# No real companies, deals, clients, or analyst notes.\n")
        for e in events:
            f.write(json.dumps(e) + "\n")
    print(f"wrote {len(events)} synthetic events -> {out_path}")


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    main(here / "data" / "synthetic_events.jsonl")
