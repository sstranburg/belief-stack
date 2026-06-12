"""
Reports.

Self-contained HTML region-card report. No external CSS, no external fonts -
opens from disk, prints clean.

This is a deliberately simple template. Adopters who want a richer report
should treat this as a reference and replace it.
"""

from __future__ import annotations

import html
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .calibration import CalibrationResult
from .decisions   import Decision
from .hypotheses  import Hypothesis
from .lifecycle   import LifecycleEvent
from .regions     import Region


_DECISION_COLOR: dict[str, str] = {
    "PROMOTE":   "#15803d",
    "MONITOR":   "#1d4ed8",
    "INTERVENE": "#a06000",
    "RECLUSTER": "#a06000",
    "INVERT":    "#6d28d9",
    "RETIRE":    "#888878",
    "ESCALATE":  "#dc2626",
}

_LIFECYCLE_COLOR: dict[str, str] = {
    "born":         "#888878",
    "strengthened": "#15803d",
    "weakened":     "#a06000",
    "contradicted": "#dc2626",
    "retired":      "#888878",
    "reopened":     "#1d4ed8",
    "inverted":     "#6d28d9",
}


_STATE_COLOR: dict[str, str] = {
    # Substrate-agnostic palette for stateful expectations rendered via
    # Hypothesis.extras. Domain integrators are free to use their own state
    # vocabulary; unknown states fall back to the neutral muted color.
    "ESCALATING": "#dc2626",
    "RESOLVING":  "#15803d",
    "STALLING":   "#a06000",
    "MIXED":      "#1d4ed8",
}


def _render_expectation(extras: dict | None) -> str:
    """Render the TopicSpace-style L2 expectation block on a card.

    Pulls these keys from Hypothesis.extras when present:
      narrative   (1-2 sentence read on the theme)
      state       (categorical, e.g. ESCALATING / RESOLVING / STALLING / MIXED)
      score       (0-100 magnitude)
      direction   (+1, 0, -1)
      conviction  (0.0-1.0)
      read        (one-line forward interpretation)
      predicted_class (bridge to L4; rendered as small label, not the headline)

    The block leads with narrative + state so the *expectation* reads as the
    object on each card. predicted_class is shown as an evaluation handle, not
    as the L2 itself.
    """
    if not extras:
        return ""

    narrative   = extras.get("narrative")
    state       = extras.get("state")
    score       = extras.get("score")
    direction   = extras.get("direction")
    conviction  = extras.get("conviction")
    read        = extras.get("read")
    predicted   = extras.get("predicted_class")

    state_color = _STATE_COLOR.get(state, "#888")
    state_pill  = (
        f"<span class='pill' style='color:{state_color};border-color:{state_color}44;"
        f"background:{state_color}0f'>{html.escape(str(state))}</span>"
        if state else ""
    )

    # Magnitude bar (score 0-100). Falls back to nothing if unavailable.
    score_html = ""
    if isinstance(score, (int, float)):
        pct = max(0, min(100, int(round(float(score)))))
        score_html = (
            f"<div class='score-row'>"
            f"<span class='lbl'>score</span>"
            f"<div class='bar'><div class='fill' style='width:{pct}%;"
            f"background:{state_color}'></div></div>"
            f"<span class='val mono'>{pct}</span>"
            f"</div>"
        )

    # Direction arrow + conviction number.
    dir_str = "&rarr;"
    if direction == 1 or direction == "+1":
        dir_str = "&uarr;"
    elif direction == -1 or direction == "-1":
        dir_str = "&darr;"
    elif direction == 0:
        dir_str = "&middot;"
    conv_str = f"{float(conviction):.2f}" if isinstance(conviction, (int, float)) else "&mdash;"

    pred_html = ""
    if predicted:
        pred_html = (
            f"<div class='exp-pred'>"
            f"<span class='lbl'>predicted next outcome</span>"
            f"<code>{html.escape(str(predicted))}</code>"
            f"<span class='exp-pred-note'>(evaluation bridge)</span>"
            f"</div>"
        )

    return f"""
    <section class='expectation'>
      <div class='exp-head'>
        <span class='exp-tag'>expectation</span>
        {state_pill}
        <span class='exp-meta mono'>{dir_str} &middot; conv {conv_str}</span>
      </div>
      {f"<div class='exp-narrative'>{html.escape(str(narrative))}</div>" if narrative else ""}
      {f"<div class='exp-read'>{html.escape(str(read))}</div>" if read else ""}
      {score_html}
      {pred_html}
    </section>
    """


def _fmt(v: Any, places: int = 2) -> str:
    if v is None:
        return "&mdash;"
    if isinstance(v, float):
        return f"{v:.{places}f}"
    return html.escape(str(v))


def _dist_inline(d: dict[Any, float]) -> str:
    if not d:
        return "<span style='color:#888'>&mdash;</span>"
    items = sorted(d.items(), key=lambda kv: -kv[1])[:3]
    return " &middot; ".join(
        f"<code>{html.escape(str(k))}</code> {v:.0%}" for k, v in items
    )


def render_region_cards_html(
    *,
    title:        str,
    generated_at: str,
    regions:      Iterable[Region],
    hypotheses:   Iterable[Hypothesis],
    calibrations: Iterable[CalibrationResult],
    decisions:    Iterable[Decision],
    lifecycle:    Iterable[LifecycleEvent] | None = None,
    out_path:     str | Path,
) -> Path:
    """
    Render a self-contained HTML region-card report and write it to `out_path`.

    All inputs are keyed by region_id; this function joins them.
    """
    regions_by_id      = {r.id: r for r in regions}
    hypotheses_by_id   = {h.region_id: h for h in hypotheses}
    calibrations_by_id = {c.region_id: c for c in calibrations}
    decisions_by_id    = {d.region_id: d for d in decisions}
    lifecycle_by_id: dict[int, LifecycleEvent] = (
        {l.region_id: l for l in lifecycle} if lifecycle else {}
    )

    ordered_ids = sorted(
        regions_by_id,
        key=lambda rid: (
            # PROMOTE first, then by top1 desc
            0 if decisions_by_id.get(rid) and decisions_by_id[rid].decision_class == "PROMOTE" else 1,
            -1 * (calibrations_by_id.get(rid).top1_accuracy or 0.0)
                 if calibrations_by_id.get(rid) else 0,
        ),
    )

    cards_html = []
    for rid in ordered_ids:
        region = regions_by_id[rid]
        hyp    = hypotheses_by_id.get(rid)
        cal    = calibrations_by_id.get(rid)
        dec    = decisions_by_id.get(rid)
        lc     = lifecycle_by_id.get(rid)

        decision_pill = ""
        if dec is not None:
            color = _DECISION_COLOR.get(dec.decision_class, "#888")
            decision_pill = (
                f"<span class='pill' style='color:{color};border-color:{color}44;"
                f"background:{color}0f'>{dec.decision_class}</span>"
            )

        lifecycle_pill = ""
        lifecycle_traj = ""
        if lc is not None:
            color = _LIFECYCLE_COLOR.get(lc.to_state, "#888")
            from_label = lc.from_state if lc.from_state else "&mdash;"
            lifecycle_pill = (
                f"<span class='pill ghost' style='color:{color};border-color:{color}55'>"
                f"{lc.to_state}</span>"
            )
            # Show prior_top1 -> current_top1 when both are present.
            prior  = lc.metrics.get("prior_top1")
            curr   = lc.metrics.get("current_top1")
            if prior is not None and not (curr != curr):  # not NaN
                lifecycle_traj = (
                    f"<div class='traj'>"
                    f"<span class='lbl'>lifecycle</span>"
                    f"<span class='val'><code>{from_label}</code> "
                    f"&rarr; <code style='color:{color}'>{lc.to_state}</code> "
                    f"&nbsp;<span class='trajnums'>top1 {prior:.2f} &rarr; {curr:.2f}</span>"
                    f"</span></div>"
                )

        expectation_html = _render_expectation(hyp.extras if hyp else None)

        cards_html.append(f"""
        <article class='card'>
          <header>
            <div class='rid'>region {region.id}</div>
            <div class='label'>{html.escape(region.label)}</div>
            <div class='pills'>{decision_pill}{lifecycle_pill}</div>
          </header>
          {expectation_html}
          <section class='stats'>
            <div><span class='lbl'>n train</span><span class='val'>{cal.n_train if cal else region.n_members}</span></div>
            <div><span class='lbl'>n test</span><span class='val'>{_fmt(cal.n_test if cal else None, 0)}</span></div>
            <div><span class='lbl'>top1</span><span class='val'>{_fmt(cal.top1_accuracy if cal else None)}</span></div>
            <div><span class='lbl'>top3</span><span class='val'>{_fmt(cal.top3_accuracy if cal else None)}</span></div>
            <div><span class='lbl'>brier</span><span class='val'>{_fmt(cal.brier_score if cal else None)}</span></div>
          </section>
          <section class='dists'>
            <div class='row'><span class='lbl'>prior</span><span class='val'>{_dist_inline(cal.prior_dist) if cal else "&mdash;"}</span></div>
            <div class='row'><span class='lbl'>actual</span><span class='val'>{_dist_inline(cal.actual_dist) if cal else "&mdash;"}</span></div>
            {lifecycle_traj}
          </section>
          {("<section class='dec'><div class='action'>" + html.escape(dec.recommended_action) + "</div>"
            "<ul class='reasons'>" + "".join(f"<li>{html.escape(r)}</li>" for r in dec.reasons) + "</ul></section>")
            if dec else ""}
        </article>
        """)

    body = "\n".join(cards_html)
    page = _TEMPLATE.format(
        title=html.escape(title),
        generated_at=html.escape(generated_at),
        n_regions=len(ordered_ids),
        cards=body,
    )

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<style>
  :root {{
    --bg:#f9f9f7; --surface:#ffffff; --border:#d0d0c8; --border2:#e4e4dc;
    --text:#1a1a12; --text2:#38382c; --muted:#888878;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:0; background:var(--bg); color:var(--text2);
         font-family:-apple-system,'Helvetica Neue',Arial,sans-serif; line-height:1.5; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:48px 28px 80px; }}
  header.top {{ display:flex; justify-content:space-between; align-items:flex-end;
                border-bottom:2px solid var(--text); padding-bottom:12px; margin-bottom:24px; }}
  header.top h1 {{ margin:0; font-size:22px; color:var(--text); letter-spacing:-0.3px; }}
  .meta {{ font-size:11px; color:var(--muted); letter-spacing:0.16em; text-transform:uppercase; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(340px,1fr)); gap:14px; }}
  .card {{ background:var(--surface); border:1px solid var(--border2); border-radius:6px;
           padding:16px 18px; }}
  .card header {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap;
                  border-bottom:1px solid var(--border2); padding-bottom:10px; margin-bottom:10px; }}
  .rid {{ font-family:ui-monospace,Menlo,monospace; font-size:10px; letter-spacing:0.14em;
          text-transform:uppercase; color:var(--muted); }}
  .label {{ font-weight:700; color:var(--text); font-size:14px; flex:1; }}
  .pills {{ display:flex; gap:6px; }}
  .pill {{ font-family:ui-monospace,Menlo,monospace; font-size:9px; font-weight:700;
           letter-spacing:0.14em; padding:3px 7px; border:1px solid; border-radius:3px;
           background:var(--surface); }}
  .pill.ghost {{ background:transparent; }}
  .stats {{ display:grid; grid-template-columns:repeat(5,1fr); gap:6px; margin-bottom:10px; }}
  .stats div {{ display:flex; flex-direction:column; align-items:flex-start; gap:1px; }}
  .lbl {{ font-family:ui-monospace,Menlo,monospace; font-size:9px; letter-spacing:0.14em;
          text-transform:uppercase; color:var(--muted); }}
  .val {{ font-family:ui-monospace,Menlo,monospace; font-size:13px; color:var(--text);
          font-variant-numeric:tabular-nums; }}
  .dists {{ font-size:11px; padding-top:8px; border-top:1px solid var(--border2); }}
  .dists .row {{ display:flex; gap:8px; padding:3px 0; }}
  .dists .row .lbl {{ width:42px; }}
  .dists .val code {{ background:#f2f2ef; padding:1px 4px; border-radius:2px; }}
  .traj {{ display:flex; gap:8px; padding:6px 0 0; }}
  .traj .lbl {{ width:42px; }}
  .traj code {{ background:#f2f2ef; padding:1px 4px; border-radius:2px;
                font-family:ui-monospace,Menlo,monospace; font-size:11px; }}
  .trajnums {{ color:var(--muted); font-family:ui-monospace,Menlo,monospace; font-size:10.5px; }}
  .dec {{ margin-top:10px; padding-top:10px; border-top:1px solid var(--border2); }}
  .action {{ font-size:12.5px; color:var(--text); margin-bottom:6px; }}
  .reasons {{ margin:0; padding-left:18px; font-size:11px; color:var(--muted); }}
  .reasons li {{ margin-bottom:2px; }}

  /* L2 expectation block (Hypothesis.extras). Rendered above stats so the
     expectation reads as the object, not a footnote. */
  .expectation {{ padding:10px 12px; margin-bottom:10px;
                  border:1px solid var(--border2); border-radius:4px;
                  background:#fbfaf6; }}
  .exp-head {{ display:flex; align-items:center; gap:8px; margin-bottom:6px; }}
  .exp-tag {{ font-family:ui-monospace,Menlo,monospace; font-size:9px;
              letter-spacing:0.16em; text-transform:uppercase; color:var(--muted); }}
  .exp-meta {{ margin-left:auto; font-size:10px; color:var(--muted); }}
  .mono {{ font-family:ui-monospace,Menlo,monospace; font-variant-numeric:tabular-nums; }}
  .exp-narrative {{ font-size:12.5px; color:var(--text); margin-bottom:4px;
                    line-height:1.45; }}
  .exp-read {{ font-size:11.5px; color:var(--text2); font-style:italic;
               margin-bottom:6px; line-height:1.4; }}
  .score-row {{ display:flex; align-items:center; gap:8px; margin:6px 0 4px; }}
  .score-row .lbl {{ width:42px; }}
  .score-row .bar {{ flex:1; height:6px; background:#ececdf;
                     border-radius:3px; overflow:hidden; }}
  .score-row .fill {{ height:100%; }}
  .score-row .val {{ font-size:10.5px; min-width:24px; text-align:right;
                     color:var(--text); }}
  .exp-pred {{ display:flex; align-items:center; gap:6px; font-size:10.5px;
               color:var(--muted); margin-top:4px; }}
  .exp-pred .lbl {{ width:auto; }}
  .exp-pred code {{ background:#f2f2ef; padding:1px 5px; border-radius:2px;
                    color:var(--text); }}
  .exp-pred-note {{ font-style:italic; }}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>{title}</h1>
    <span class="meta">{n_regions} regions &middot; {generated_at}</span>
  </header>
  <div class="grid">
    {cards}
  </div>
</div>
</body>
</html>
"""
