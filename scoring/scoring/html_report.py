"""
Self-contained HTML report for 3-input BDD behaviour scoring.
Generated-test-first layout with plain-language labels.
"""
from __future__ import annotations

import html
from typing import TYPE_CHECKING

from .report_views import build_detailed, build_simplified

if TYPE_CHECKING:
    from .models import ScoreReport


def _esc(text: object) -> str:
    return html.escape(str(text))


def _score_color(pct: float) -> str:
    if pct >= 75:
        return "#15803d"
    if pct >= 50:
        return "#ca8a04"
    return "#dc2626"


def _score_bg(pct: float) -> str:
    if pct >= 75:
        return "#dcfce7"
    if pct >= 50:
        return "#fef9c3"
    return "#fee2e2"


def _progress_bar(pct: float, *, height: int = 10) -> str:
    color = _score_color(pct)
    return (
        f"<div class='bar-wrap' style='height:{height}px'>"
        f"<div class='bar' style='width:{min(pct, 100):.0f}%;background:{color}'></div>"
        f"</div>"
    )


def _kpi_card(
    question: str,
    count: int,
    total: int,
    pct: float,
    *,
    icon: str,
    hint: str,
) -> str:
    color = _score_color(pct)
    return f"""
    <div class="kpi-card" style="border-color:{color}22;background:{_score_bg(pct)}">
      <div class="kpi-icon">{icon}</div>
      <div class="kpi-q">{_esc(question)}</div>
      <div class="kpi-num" style="color:{color}">{count}<span class="kpi-of"> / {total}</span></div>
      <div class="kpi-pct" style="color:{color}">{pct:.0f}%</div>
      {_progress_bar(pct)}
      <div class="kpi-hint">{_esc(hint)}</div>
    </div>"""


def _wrap_table(table_html: str) -> str:
    return f'<div class="table-scroll">{table_html}</div>'


def _row_missing(rows: str, items) -> str:
    for m in items:
        near = f"{m.best_near_match:.0%}" if m.best_near_match is not None else "n/a"
        nearest = m.nearest_scenario or "—"
        near_class = "near-ok" if m.best_near_match and m.best_near_match >= 0.7 else "near-low"
        rows += (
            f"<tr><td class='cell-text'>{_esc(m.scenario)}</td>"
            f"<td class='cell-text'>{_esc(nearest)}</td>"
            f"<td class='num col-narrow {near_class}'>{near}</td>"
            f"<td class='col-narrow'><span class='tag'>{_esc(m.workflow_stage)}</span> "
            f"<span class='tag tag-{_esc(m.intent)}'>{_esc(m.intent)}</span></td>"
            f"<td class='cell-actions mono'>{_esc(', '.join(m.actions))}</td>"
            f"<td class='cell-why small'>{_esc(m.why_missing)}</td></tr>\n"
        )
    return rows


def _guide_html(has_req: bool, threshold: float) -> str:
    strict = "strict" if threshold >= 0.75 else "moderate" if threshold >= 0.5 else "lenient"
    req_block = ""
    if has_req:
        req_block = """
        <li><strong>Requirement docs</strong> — the behaviour contract from the requirement agent.</li>
        <li><strong>Matches both</strong> — a generated test that aligns with manual <em>and</em> requirements (best case).</li>"""
    return f"""
    <details class="guide" open>
      <summary>How to read this report</summary>
      <div class="guide-body">
        <p>This report scores <strong>generated BDD tests</strong> — not manual tests. Manual tests and requirements are only used as references.</p>
        <ol>
          <li><strong>{threshold:.0%} match threshold ({strict})</strong> — two scenarios must share workflow stage, intent, and enough business actions to count as aligned.</li>
          <li><strong>Manual tests</strong> — ground truth; always treated as correct.</li>{req_block}
          <li><strong>Overall score</strong> — golden-first: weighted blend of <em>manual coverage</em>,
              match quality, coverage efficiency, and suite precision (padding is penalised).
              Requirements are supporting when present.</li>
        </ol>
        <p class="small muted">Lower threshold = more pairs accepted. At 0.9 only near-identical behaviour matches.</p>
      </div>
    </details>"""


def render_html(report: "ScoreReport", title: str = "Generated BDD Quality Report") -> str:
    simple = build_simplified(report)
    detailed = build_detailed(report)
    b = report.breakdown
    overall = simple["overall_score_pct"]
    color = _score_color(overall)
    has_req = report.has_requirements
    h = simple["headline"]

    n_gen = h["generated_scored_scenarios"]
    n_manual_ok = h["generated_aligned_to_manual"]
    pct_manual = h["generated_manual_alignment_pct"]
    pct_recall = h.get("manual_recall_pct", b.manual_recall_pct)
    pct_eff = h.get("coverage_efficiency_pct", b.coverage_efficiency_pct)
    n_req_ok = h.get("generated_aligned_to_requirements", 0)
    pct_req = h.get("generated_requirement_alignment_pct", 0)
    n_both = h.get("generated_triangulated_count", 0)
    pct_both = h.get("triangulation_pct", 0)
    n_not_manual = h["generated_unaligned_manual"]
    n_not_req = h.get("generated_unaligned_requirements", n_gen)

    kpi_manual = _kpi_card(
        "Manual coverage (recall)?",
        int(round(pct_recall / 100.0 * report.manual_scenarios)) if report.manual_scenarios else 0,
        report.manual_scenarios,
        pct_recall,
        icon="&#10003;",
        hint="Share of golden/manual scenarios covered by generated tests.",
    )
    kpi_precision = _kpi_card(
        "Suite precision?",
        n_manual_ok, n_gen, pct_manual,
        icon="&#9878;",
        hint="Share of generated scenarios that align with a manual test (padding hurts this).",
    )
    kpi_eff = _kpi_card(
        "Coverage efficiency?",
        int(round(pct_eff)),
        100,
        pct_eff,
        icon="&#9889;",
        hint="Manuals covered per generated scenario (capped at 100%). Lean suites score higher.",
    )
    kpi_req = ""
    kpi_both = ""
    if has_req:
        kpi_req = _kpi_card(
            "Requirement AC recall?",
            report.matched_requirements, report.requirement_acs or 1,
            b.requirement_ac_coverage_pct,
            icon="&#128196;",
            hint="Share of requirement ACs with a matching generated scenario.",
        )
        kpi_both = _kpi_card(
            "Matches manual AND requirement?",
            n_both, n_gen, pct_both,
            icon="&#9733;",
            hint="Fully aligned — manual ground truth and requirement contract agree.",
        )

    good_news = []
    fix_these = []
    for line in simple.get("highlights", []):
        if "not aligned" in line.lower() or "uncovered" in line.lower() or "missing" in line.lower():
            fix_these.append(line)
        else:
            good_news.append(line)
    for line in simple.get("top_gaps", []):
        if line not in fix_these:
            fix_these.append(line)

    good_html = "".join(f"<li>{_esc(x)}</li>" for x in good_news[:6]) or "<li class='muted'>No strong alignments at this threshold.</li>"
    fix_html = "".join(f"<li>{_esc(x)}</li>" for x in fix_these[:8]) or "<li class='muted'>No major gaps.</li>"

    top_matches_rows = ""
    for m in simple.get("top_matches", []):
        score = m.get("match_score", 0)
        score_s = f"{score:.0%}" if score else ""
        top_matches_rows += (
            f"<tr><td class='cell-text'>{_esc(m['generated_scenario'])}</td>"
            f"<td class='cell-text'>{_esc(m.get('manual_scenario', m['your_scenario']))}</td>"
            f"<td class='col-narrow'><span class='tag'>{_esc(m['area'])}</span></td>"
            f"<td class='num col-narrow match-high'>{score_s}</td></tr>\n"
        )

    tri_rows = ""
    for t in report.triangulation:
        d = t.to_dict() if hasattr(t, "to_dict") else t
        tri_rows += (
            f"<tr><td class='cell-text'>{_esc(d['generated_scenario'])}</td>"
            f"<td class='cell-text'>{_esc(d['manual_scenario'])}</td>"
            f"<td class='cell-wide'>{_esc(d['requirement_ac'])}</td>"
            f"<td class='col-narrow'><span class='tag'>{_esc(d['workflow_stage'])}</span></td>"
            f"<td class='num col-narrow'>{d['manual_score']:.0%} / {d['requirement_score']:.0%}</td></tr>\n"
        )

    matched_rows = ""
    for m in report.matched:
        acts = ", ".join(m.shared_actions) or "none"
        matched_rows += (
            f"<tr><td class='num col-narrow match-high'>{m.match_score:.0%}</td>"
            f"<td class='cell-text'>{_esc(m.generated_scenario)}</td>"
            f"<td class='cell-text'>{_esc(m.manual_scenario)}</td>"
            f"<td class='col-narrow'><span class='tag'>{_esc(m.workflow_stage)}</span> "
            f"<span class='tag tag-{_esc(m.intent)}'>{_esc(m.intent)}</span></td>"
            f"<td class='cell-actions mono'>{_esc(acts)}</td>"
            f"<td class='cell-why small'>{_esc(m.why_matched)}</td></tr>\n"
        )

    req_match_rows = ""
    for m in report.requirement_matches:
        neg = "yes" if m.negative_path else "no"
        req_match_rows += (
            f"<tr><td class='num col-narrow match-high'>{m.match_score:.0%}</td>"
            f"<td class='cell-text'>{_esc(m.generated_scenario)}</td>"
            f"<td class='cell-wide'>{_esc(m.requirement_ac)}</td>"
            f"<td class='cell-text'>{_esc(m.unit_id)}</td>"
            f"<td class='col-narrow'><span class='tag'>{_esc(m.workflow_stage)}</span></td>"
            f"<td class='col-narrow'>{neg}</td>"
            f"<td class='cell-why small'>{_esc(m.why_matched)}</td></tr>\n"
        )

    missing_manual_rows = _row_missing("", report.missing_behaviors)
    missing_req_ac_rows = _row_missing("", report.missing_requirements)
    missing_generated_rows = _row_missing("", report.extra_behaviors)
    misaligned_req_rows = _row_missing("", report.misaligned_generated_vs_requirements)

    unit_rows = ""
    for u in report.unit_traceability:
        d = u.to_dict() if hasattr(u, "to_dict") else u
        unit_rows += (
            f"<tr><td class='cell-text'>{_esc(d['unit_id'])}</td>"
            f"<td class='col-narrow'>{_esc(d['unit_type'])}</td>"
            f"<td class='num col-narrow'>{d['requirement_acs_covered']}/{d['requirement_acs']}</td>"
            f"<td class='num col-narrow'>{d['manual_covered']}/{d['manual_scenarios_near_unit']}</td>"
            f"<td class='cell-wide mono'>{_esc(', '.join(d['generated_scenarios']) or '—')}</td>"
            f"<td class='num col-narrow'>{d['requirement_coverage_pct']:.0f}%</td></tr>\n"
        )

    w = detailed["scoring_weights"]
    metrics = [
        ("Manual coverage (recall)", b.manual_recall_pct or b.behavior_coverage_pct,
         w.get("manual_recall", w.get("behavior_coverage", 0))),
        ("Coverage efficiency", b.coverage_efficiency_pct,
         w.get("coverage_efficiency", 0)),
        ("Suite precision", b.suite_precision_pct or b.generated_manual_alignment_pct,
         w.get("suite_precision", w.get("generated_manual_alignment", 0))),
        ("Actions covered (aligned pairs)", b.action_coverage_pct,
         w.get("manual_action_from_pairs", w.get("manual_action", 0))),
        ("Positive paths (aligned pairs)", b.positive_path_coverage_pct,
         w.get("manual_positive_from_pairs", w.get("manual_positive", 0))),
        ("Negative paths (aligned pairs)", b.negative_path_coverage_pct,
         w.get("manual_negative_from_pairs", w.get("manual_negative", 0))),
        ("Workflow stages (aligned pairs)", b.workflow_stage_coverage_pct,
         w.get("manual_stage_from_pairs", w.get("manual_stage", 0))),
        ("Manual features touched", b.feature_completeness_pct,
         w.get("manual_feature_from_pairs", w.get("manual_feature", 0))),
    ]
    if has_req:
        metrics.extend([
            ("Requirement AC recall", b.requirement_ac_coverage_pct,
             w.get("requirement_recall", w.get("requirement_ac", 0))),
            ("Matches both (triangulated)", b.triangulation_pct,
             w.get("generated_triangulation", w.get("triangulation", 0))),
        ])

    metrics_rows = ""
    for label, val, weight in metrics:
        if weight <= 0:
            continue
        metrics_rows += (
            f"<tr><td>{_esc(label)}</td><td>{_progress_bar(val)}</td>"
            f"<td class='num'>{val:.1f}%</td>"
            f"<td class='num muted'>{weight:.0%}</td></tr>\n"
        )

    explanation = "".join(f"<li>{_esc(line)}</li>" for line in b.explanation)
    guide = _guide_html(has_req, report.threshold)

    flow_extra = ""
    if has_req:
        flow_extra = f"""
        <div class="flow-step"><span class="flow-n">{n_req_ok}</span> cover a requirement ({pct_req:.0f}%)</div>
        <div class="flow-arrow">&#8595;</div>
        <div class="flow-step flow-gold"><span class="flow-n">{n_both}</span> match manual <strong>and</strong> requirement ({pct_both:.0f}%)</div>"""

    req_sections = ""
    if has_req:
        req_sections = f"""
    <details class="section" id="sec-req">
      <summary>Requirement alignments ({len(report.requirement_matches)} generated tests)</summary>
      <p class="section-desc">Generated tests that match a requirement acceptance criterion.</p>
      {_wrap_table(f'''<table>
        <thead><tr><th class="col-narrow">Match</th><th>Generated test</th><th>Requirement AC</th><th>Unit</th><th class="col-narrow">Stage</th><th class="col-narrow">Negative?</th><th>Why</th></tr></thead>
        <tbody>{req_match_rows or '<tr><td colspan="7">None at this threshold</td></tr>'}</tbody>
      </table>''')}
    </details>

    <details class="section" id="sec-req-gaps">
      <summary>Generated tests missing requirement coverage ({n_not_req})</summary>
      {_wrap_table(f'''<table>
        <thead><tr><th>Generated test</th><th>Nearest requirement</th><th class="col-narrow">Near match</th><th class="col-narrow">Stage</th><th>Actions</th><th>Why not aligned</th></tr></thead>
        <tbody>{misaligned_req_rows or '<tr><td colspan="6">None</td></tr>'}</tbody>
      </table>''')}
      <h3 class="sub-h">Requirement ACs still uncovered ({len(report.missing_requirements)})</h3>
      <p class="section-desc muted">Reference only — spec items with no generated test yet.</p>
      {_wrap_table(f'''<table>
        <thead><tr><th>Requirement AC</th><th>Nearest generated</th><th class="col-narrow">Near match</th><th class="col-narrow">Stage</th><th>Actions</th><th>Why</th></tr></thead>
        <tbody>{missing_req_ac_rows or '<tr><td colspan="6">None</td></tr>'}</tbody>
      </table>''')}
    </details>

    <details class="section" id="sec-tri">
      <summary>Matches both manual and requirement ({len(report.triangulation)})</summary>
      {_wrap_table(f'''<table>
        <thead><tr><th>Generated test</th><th>Manual reference</th><th>Requirement AC</th><th class="col-narrow">Stage</th><th class="col-narrow">Scores</th></tr></thead>
        <tbody>{tri_rows or '<tr><td colspan="5">None at this threshold</td></tr>'}</tbody>
      </table>''')}
    </details>

    <details class="section" id="sec-units">
      <summary>Per-unit traceability</summary>
      {_wrap_table(f'''<table>
        <thead><tr><th>Unit</th><th class="col-narrow">Type</th><th class="col-narrow">Req ACs</th><th class="col-narrow">Manual</th><th>Generated</th><th class="col-narrow">Req cov.</th></tr></thead>
        <tbody>{unit_rows or '<tr><td colspan="6">None</td></tr>'}</tbody>
      </table>''')}
    </details>"""

    nav_req = ""
    if has_req:
        nav_req = """
        <a href="#sec-req">Requirements</a>
        <a href="#sec-tri">Both</a>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <style>
    :root {{ --bg:#f1f5f9; --card:#fff; --text:#0f172a; --muted:#64748b; --border:#e2e8f0; --accent:#2563eb; --gold:#b45309; }}
    * {{ box-sizing:border-box; }}
    body {{ font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:var(--text); margin:0; line-height:1.55; }}
    .wrap {{ max-width:1280px; margin:0 auto; padding:20px 16px 56px; }}
    h1 {{ font-size:1.6rem; margin:0 0 4px; font-weight:800; letter-spacing:-.02em; }}
    .header {{ display:flex; flex-wrap:wrap; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:20px; }}
    .badge {{ display:inline-block; font-size:.75rem; font-weight:600; padding:4px 10px; border-radius:999px; background:#e0e7ff; color:#3730a3; }}
    .badge-strict {{ background:#fee2e2; color:#991b1b; }}
    .nav {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }}
    .nav a {{ font-size:.8rem; padding:6px 12px; background:var(--card); border:1px solid var(--border); border-radius:8px; color:var(--accent); text-decoration:none; }}
    .nav a:hover {{ background:#eff6ff; }}
    .card {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:20px 22px; margin-bottom:16px; box-shadow:0 1px 2px rgba(0,0,0,.04); }}
    .hero {{ display:flex; gap:20px; align-items:center; flex-wrap:wrap; }}
    .score-ring {{ width:100px; height:100px; border-radius:50%; border:7px solid {color}; display:flex; align-items:center; justify-content:center; font-size:1.75rem; font-weight:800; color:{color}; flex-shrink:0; }}
    .summary {{ font-size:1.05rem; flex:1; min-width:200px; }}
    .verdict {{ margin-top:10px; padding:10px 14px; background:#f8fafc; border-left:4px solid {color}; border-radius:0 8px 8px 0; font-size:.92rem; }}
    .kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; margin-top:4px; }}
    .kpi-card {{ border:2px solid; border-radius:12px; padding:16px; }}
    .kpi-icon {{ font-size:1.2rem; margin-bottom:4px; }}
    .kpi-q {{ font-size:.85rem; font-weight:700; margin-bottom:8px; line-height:1.3; }}
    .kpi-num {{ font-size:2rem; font-weight:800; line-height:1; }}
    .kpi-of {{ font-size:1rem; font-weight:500; color:var(--muted); }}
    .kpi-pct {{ font-size:1.1rem; font-weight:700; margin:4px 0 8px; }}
    .kpi-hint {{ font-size:.75rem; color:var(--muted); margin-top:8px; }}
    .flow {{ display:flex; flex-direction:column; align-items:center; gap:4px; padding:16px; background:#f8fafc; border-radius:10px; margin-top:12px; }}
    .flow-step {{ background:var(--card); border:1px solid var(--border); border-radius:8px; padding:10px 20px; font-size:.9rem; text-align:center; width:100%; max-width:420px; }}
    .flow-step.flow-gold {{ border-color:var(--gold); background:#fffbeb; }}
    .flow-n {{ font-size:1.4rem; font-weight:800; color:var(--accent); margin-right:6px; }}
    .flow-gold .flow-n {{ color:var(--gold); }}
    .flow-arrow {{ color:var(--muted); font-size:1.2rem; }}
    .two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
    @media(max-width:640px) {{ .two-col {{ grid-template-columns:1fr; }} }}
    .col-good h3 {{ color:#15803d; }}
    .col-fix h3 {{ color:#dc2626; }}
    ul {{ margin:6px 0; padding-left:18px; }}
    li {{ margin-bottom:4px; font-size:.9rem; }}
    table {{ width:100%; border-collapse:collapse; font-size:.85rem; margin:0; table-layout:auto; }}
    th,td {{ text-align:left; padding:10px 12px; border-bottom:1px solid var(--border); vertical-align:top; white-space:normal; word-break:break-word; overflow-wrap:anywhere; }}
    th {{ background:#f8fafc; font-weight:600; color:var(--muted); font-size:.72rem; text-transform:uppercase; letter-spacing:.03em; position:sticky; top:0; z-index:1; }}
    tr:hover td {{ background:#fafafa; }}
    .table-scroll {{ overflow-x:auto; overflow-y:visible; -webkit-overflow-scrolling:touch; max-width:100%; margin-top:8px; border:1px solid var(--border); border-radius:8px; }}
    .card .table-scroll {{ margin-top:12px; }}
    .section .table-scroll {{ margin:12px 18px 18px; }}
    .table-scroll table {{ min-width:720px; }}
    .cell-text {{ min-width:140px; }}
    .cell-wide {{ min-width:200px; }}
    .cell-why {{ min-width:160px; }}
    .cell-actions {{ min-width:100px; }}
    .col-narrow {{ width:1%; white-space:nowrap; }}
    .tag {{ display:inline-block; font-size:.68rem; padding:2px 7px; border-radius:999px; background:#e0e7ff; color:#3730a3; margin-right:3px; }}
    .tag-positive {{ background:#dcfce7; color:#166534; }}
    .tag-negative {{ background:#fee2e2; color:#991b1b; }}
    .tag-neutral {{ background:#f1f5f9; color:#475569; }}
    .mono {{ font-family:ui-monospace,monospace; font-size:.78rem; }}
    .small {{ font-size:.8rem; color:var(--muted); }}
    .num {{ text-align:right; white-space:nowrap; }}
    .match-high {{ color:#15803d; font-weight:700; }}
    .near-ok {{ color:#ca8a04; }}
    .near-low {{ color:#dc2626; }}
    .muted {{ color:var(--muted); }}
    .bar-wrap {{ background:#e2e8f0; border-radius:4px; height:8px; width:100%; }}
    .bar {{ height:100%; border-radius:4px; transition:width .3s; }}
    .guide {{ background:var(--card); border:1px solid var(--border); border-radius:12px; margin-bottom:16px; overflow:hidden; }}
    .guide summary {{ cursor:pointer; padding:14px 18px; font-weight:700; font-size:.9rem; list-style:none; }}
    .guide summary::-webkit-details-marker {{ display:none; }}
    .guide summary::before {{ content:'▸ '; color:var(--accent); }}
    .guide[open] summary::before {{ content:'▾ '; }}
    .guide-body {{ padding:0 18px 16px; font-size:.88rem; border-top:1px solid var(--border); }}
    .guide-body ol {{ padding-left:20px; }}
    .section {{ background:var(--card); border:1px solid var(--border); border-radius:12px; margin-bottom:12px; overflow:visible; }}
    .section summary {{ cursor:pointer; padding:14px 18px; font-weight:600; font-size:.95rem; list-style:none; background:#fafafa; border-bottom:1px solid transparent; }}
    .section[open] summary {{ border-bottom-color:var(--border); }}
    .section summary::-webkit-details-marker {{ display:none; }}
    .section summary::before {{ content:'+ '; color:var(--muted); font-weight:400; }}
    .section[open] summary::before {{ content:'− '; }}
    .section-desc {{ padding:12px 18px 0; margin:0; font-size:.85rem; }}
    .sub-h {{ font-size:.95rem; margin:20px 18px 4px; }}
    .pill {{ display:inline-block; font-size:.65rem; font-weight:700; text-transform:uppercase; letter-spacing:.05em; padding:3px 8px; border-radius:4px; margin-bottom:10px; }}
    .pill-stake {{ background:#dbeafe; color:#1e40af; }}
    .pill-dev {{ background:#f3e8ff; color:#6b21a8; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <div>
        <h1>{_esc(title)}</h1>
        <p class="small muted">Scoring <strong>{n_gen} generated</strong> test scenarios against manual reference ({h['manual_reference_scenarios']}){f" and {h.get('requirement_acs', 0)} requirement ACs" if has_req else ""}.</p>
      </div>
      <span class="badge {'badge-strict' if report.threshold >= 0.75 else ''}">Match threshold: {report.threshold:.0%}</span>
    </div>

    {guide}

    <nav class="nav">
      <a href="#sec-at-glance">At a glance</a>
      <a href="#sec-matches">Matches</a>
      <a href="#sec-gaps">Gaps</a>{nav_req}
      <a href="#sec-breakdown">Breakdown</a>
    </nav>

    <div class="card" id="sec-at-glance">
      <span class="pill pill-stake">At a glance</span>
      <div class="hero">
        <div class="score-ring">{overall:.0f}%</div>
        <div>
          <div class="summary">{_esc(simple['summary'])}</div>
          <div class="verdict"><strong>Verdict:</strong> {_esc(simple['verdict'])}</div>
        </div>
      </div>

      <div class="kpi-grid">
        {kpi_manual}
        {kpi_eff}
        {kpi_precision}
        {kpi_req}
        {kpi_both}
      </div>

      <div class="flow">
        <div class="flow-step"><span class="flow-n">{report.manual_scenarios}</span> manual tests as golden reference</div>
        <div class="flow-arrow">&#8595;</div>
        <div class="flow-step"><span class="flow-n">{pct_recall:.0f}%</span> manual coverage (recall)</div>
        <div class="flow-arrow">&#8595;</div>
        <div class="flow-step"><span class="flow-n">{n_gen}</span> generated scored — precision {pct_manual:.0f}%, efficiency {pct_eff:.0f}%</div>
        {flow_extra}
      </div>
    </div>

    <div class="card">
      <div class="two-col">
        <div class="col-good"><h3>What's working</h3><ul>{good_html}</ul></div>
        <div class="col-fix"><h3>What to fix</h3><ul>{fix_html}</ul></div>
      </div>
    </div>

    <div class="card" id="sec-matches">
      <h2 style="margin:0 0 12px;font-size:1.1rem;">Best generated alignments</h2>
      {_wrap_table(f'''<table>
        <thead><tr><th>Generated test</th><th>Manual reference</th><th class="col-narrow">Stage</th><th class="col-narrow">Match</th></tr></thead>
        <tbody>{top_matches_rows or '<tr><td colspan="4">No matches at this threshold — try lowering it.</td></tr>'}</tbody>
      </table>''')}
    </div>

    <details class="section" id="sec-all-manual">
      <summary>All manual alignments ({len(report.matched)} generated tests)</summary>
      <p class="section-desc">Every generated test accepted as similar to a manual reference test.</p>
      {_wrap_table(f'''<table>
        <thead><tr><th class="col-narrow">Match</th><th>Generated test</th><th>Manual reference</th><th class="col-narrow">Stage / intent</th><th>Shared actions</th><th>Why</th></tr></thead>
        <tbody>{matched_rows or '<tr><td colspan="6">None</td></tr>'}</tbody>
      </table>''')}
    </details>

    {req_sections}

    <details class="section" id="sec-gaps" open>
      <summary>Generated tests not similar to manual ({n_not_manual})</summary>
      <p class="section-desc">Primary gaps — generated tests with no accepted manual pair at {report.threshold:.0%} threshold.</p>
      {_wrap_table(f'''<table>
        <thead><tr><th>Generated test</th><th>Nearest manual</th><th class="col-narrow">Near match</th><th class="col-narrow">Stage</th><th>Actions</th><th>Why not aligned</th></tr></thead>
        <tbody>{missing_generated_rows or '<tr><td colspan="6">None — all generated tests matched manual.</td></tr>'}</tbody>
      </table>''')}
      <h3 class="sub-h">Manual tests without a generated pair ({len(report.missing_behaviors)}) — reference only</h3>
      {_wrap_table(f'''<table>
        <thead><tr><th>Manual test</th><th>Nearest generated</th><th class="col-narrow">Near match</th><th class="col-narrow">Stage</th><th>Actions</th><th>Why</th></tr></thead>
        <tbody>{missing_manual_rows or '<tr><td colspan="6">None</td></tr>'}</tbody>
      </table>''')}
    </details>

    <details class="section" id="sec-breakdown">
      <summary><span class="pill pill-dev">Developer</span> Score breakdown &amp; method</summary>
      {_wrap_table(f'''<table>
        <thead><tr><th>Metric</th><th></th><th class="col-narrow">Score</th><th class="col-narrow">Weight</th></tr></thead>
        <tbody>{metrics_rows}</tbody>
      </table>''')}
      <p class="section-desc muted">
        Granularity {b.granularity_ratio:.2f} &middot; Manual Gherkin {b.golden_gherkin_compliance_pct:.0f}% &middot;
        Generated Gherkin {b.generated_gherkin_compliance_pct:.0f}%
      </p>
      <h3 class="sub-h">Why this score</h3>
      <ul style="padding:0 18px 8px 36px">{explanation}</ul>
      <p class="section-desc muted">{_esc(detailed['method'])}</p>
    </details>
  </div>
</body>
</html>
"""


def write_html(report: "ScoreReport", path: str, title: str = "Generated BDD Quality Report") -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(render_html(report, title=title))
