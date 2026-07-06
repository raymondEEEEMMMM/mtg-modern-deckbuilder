#!/usr/bin/env python3
"""
Render a self-contained dark-themed HTML meta snapshot report from
synthesis + raw meta snapshot dicts produced by the meta-snapshot workflow.

Input shape (dict):
{
    "period_start": "2026-05-18",
    "period_end":   "2026-06-10",
    "top_archetypes":      [{"archetype":..., "count":..., "percentage":..., "trend":...}, ...],
    "new_archetypes":      [...],            # list of strings
    "removed_archetypes":  [...],            # list of strings
    "executive_summary":   "...",
    "meta_snapshot_highlights": [...],
    "source_recommendations": {
        "must_add":     [{"name":..., "url":..., "rationale":..., "integration_effort":...}, ...],
        "nice_to_have": [...],
        "skip":         [...],
    },
    "critical_gaps":     [...],             # optional, surfaces in gap section
    "stats":             {"events": 8, "decks": 97, "top_n": 15, "top_share": 14.43, "matchup_coverage": 0.30},
}

Usage:
    python3 scripts/render_meta_snapshot.py \\
        --in workflow_result.json \\
        --out mtg_modern_data/decks/reports/2026-06-10_meta_snapshot.html

Or import:
    from render_meta_snapshot import render
    render(synthesis_dict, "path/to/out.html")
"""

import argparse
import json
from datetime import date
from html import escape
from pathlib import Path
from typing import Any, Mapping, Union


# ─── Theme (mirrors the reference grixis_deaths_shadow.html dark indigo/slate) ───
CSS = r"""
  :root {
    --bg: #0f172a;
    --card: #1e293b;
    --border: #334155;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --accent: #818cf8;
    --accent2: #6366f1;
    --tier1: #ef4444;
    --tier2: #f59e0b;
    --tier3: #3b82f6;
    --G: #10b981;
    --up: #22c55e;
    --down: #ef4444;
    --stable: #3b82f6;
    --new: #a855f7;
    --gone: #6b7280;
    --must: #ef4444;
    --nice: #f59e0b;
    --skip: #6b7280;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: var(--bg); color: var(--text); line-height: 1.6; }
  .container { max-width: 1200px; margin: 0 auto; padding: 0 20px; }
  .hero { background: linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #1e1b4b 100%);
          padding: 48px 0 36px; border-bottom: 1px solid var(--border); }
  .hero h1 { font-size: 2.4rem; font-weight: 800;
             background: linear-gradient(135deg, #c7d2fe, #818cf8);
             -webkit-background-clip: text; -webkit-text-fill-color: transparent;
             margin-bottom: 8px; }
  .hero .subtitle { color: var(--text-dim); font-size: 1.1rem; }
  .hero .meta-row { display: flex; gap: 24px; margin-top: 20px; flex-wrap: wrap; }
  .hero .meta-item { background: rgba(255,255,255,0.06); border-radius: 8px;
                     padding: 10px 16px; font-size: 0.9rem; }
  .hero .meta-item .label { color: var(--text-dim); font-size: 0.8rem; }
  .hero .meta-item .value { color: var(--accent); font-weight: 600; font-size: 1.1rem; }
  .stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 200px));
               gap: 16px; margin: 32px 0; }
  .stat-card { background: var(--card); border: 1px solid var(--border);
               border-radius: 12px; padding: 20px; text-align: center; }
  .stat-card .stat-value { font-size: 2rem; font-weight: 800; margin-bottom: 4px; }
  .stat-card .stat-label { color: var(--text-dim); font-size: 0.85rem; }
  .section { margin: 40px 0; }
  .section-title { font-size: 1.4rem; font-weight: 700; margin-bottom: 20px;
                   padding-bottom: 8px; border-bottom: 2px solid var(--accent2);
                   display: inline-block; }
  .section-body { color: var(--text); font-size: 0.95rem; line-height: 1.7;
                  background: var(--card); border: 1px solid var(--border);
                  border-radius: 12px; padding: 20px; }
  .archetype-table { width: 100%; border-collapse: collapse; background: var(--card);
                     border-radius: 12px; overflow: hidden; border: 1px solid var(--border); }
  .archetype-table th { background: rgba(99,102,241,0.15); padding: 12px 16px;
                        text-align: left; font-size: 0.8rem; text-transform: uppercase;
                        letter-spacing: 0.05em; color: var(--accent); }
  .archetype-table td { padding: 12px 16px; border-top: 1px solid var(--border); font-size: 0.9rem; }
  .archetype-table tr:hover { background: rgba(255,255,255,0.03); }
  .archetype-table .rank { color: var(--text-dim); font-weight: 700; width: 50px; }
  .archetype-table .archetype-name { font-weight: 600; }
  .archetype-table .count { text-align: right; font-weight: 700; }
  .archetype-table .pct { text-align: right; color: var(--text-dim); }
  .pill { display: inline-block; padding: 3px 10px; border-radius: 4px;
          font-size: 0.75rem; font-weight: 700; color: #fff; }
  .pill-up { background: var(--up); }
  .pill-down { background: var(--down); }
  .pill-stable { background: var(--stable); }
  .pill-new { background: var(--new); }
  .pill-gone { background: var(--gone); }
  .shifts-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .shift-panel { background: var(--card); border: 1px solid var(--border);
                 border-radius: 12px; padding: 20px; }
  .shift-panel h3 { font-size: 1.05rem; margin-bottom: 14px;
                    padding-bottom: 8px; border-bottom: 1px solid var(--border); }
  .shift-panel.new h3 { color: var(--new); }
  .shift-panel.removed h3 { color: var(--gone); }
  .shift-item { display: flex; align-items: center; justify-content: space-between;
                padding: 8px 0; border-bottom: 1px dashed rgba(255,255,255,0.06);
                font-size: 0.9rem; }
  .shift-item:last-child { border-bottom: none; }
  .shift-item .name { color: var(--text); font-weight: 500; }
  .shift-item .meta { color: var(--text-dim); font-size: 0.8rem; }
  .gap-list { display: flex; flex-direction: column; gap: 12px; }
  .gap-item { background: var(--card); border: 1px solid var(--border);
              border-radius: 10px; padding: 14px 18px; border-left: 4px solid var(--tier3);
              display: flex; align-items: flex-start; gap: 12px; }
  .gap-item.high { border-left-color: var(--tier1); }
  .gap-item.medium { border-left-color: var(--tier2); }
  .gap-item .severity { font-size: 0.7rem; text-transform: uppercase;
                        padding: 2px 8px; border-radius: 4px; font-weight: 700;
                        color: #fff; flex-shrink: 0; align-self: flex-start; }
  .gap-item.high .severity { background: var(--tier1); }
  .gap-item.medium .severity { background: var(--tier2); }
  .gap-item .body { flex: 1; }
  .gap-item .body .title { font-weight: 600; margin-bottom: 4px; }
  .gap-item .body .desc { color: var(--text-dim); font-size: 0.85rem; line-height: 1.5; }
  .rec-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
  .rec-card { background: var(--card); border: 1px solid var(--border);
              border-radius: 12px; padding: 18px; border-top: 4px solid var(--border); }
  .rec-card.must_add { border-top-color: var(--must); }
  .rec-card.nice_to_have { border-top-color: var(--nice); }
  .rec-card.skip { border-top-color: var(--skip); }
  .rec-card .rec-tag { display: inline-block; font-size: 0.7rem; font-weight: 700;
                       text-transform: uppercase; padding: 3px 8px; border-radius: 4px;
                       color: #fff; margin-bottom: 10px; }
  .rec-card.must_add .rec-tag { background: var(--must); }
  .rec-card.nice_to_have .rec-tag { background: var(--nice); }
  .rec-card.skip .rec-tag { background: var(--skip); }
  .rec-card .rec-name { font-size: 1.05rem; font-weight: 700; margin-bottom: 8px; }
  .rec-card .rec-url { font-size: 0.8rem; color: var(--accent);
                       word-break: break-all; margin-bottom: 10px; display: block; }
  .rec-card .rec-rationale { color: var(--text-dim); font-size: 0.85rem;
                              line-height: 1.5; margin-bottom: 10px; }
  .rec-card .rec-effort { font-size: 0.75rem; color: var(--text-dim);
                          background: rgba(255,255,255,0.04); padding: 4px 8px;
                          border-radius: 4px; display: inline-block; }
  .rec-card .rec-effort .effort-value { color: var(--accent); font-weight: 700; }
  .highlights { background: var(--card); border: 1px solid var(--border);
                border-radius: 12px; padding: 20px; }
  .highlights ul { list-style: none; }
  .highlights li { padding: 10px 0; border-bottom: 1px dashed rgba(255,255,255,0.06);
                   padding-left: 24px; position: relative; font-size: 0.9rem; line-height: 1.6; }
  .highlights li:last-child { border-bottom: none; }
  .highlights li::before { content: "▸"; position: absolute; left: 0;
                           color: var(--accent); font-weight: 700; }
  footer { text-align: center; padding: 40px 0 20px; color: var(--text-dim);
           font-size: 0.8rem; border-top: 1px solid var(--border); margin-top: 60px; }
"""


TREND_LABELS = {
    "up": ("上升", "pill-up"),
    "down": ("下降", "pill-down"),
    "stable": ("稳定", "pill-stable"),
    "new": ("新出现", "pill-new"),
    "gone": ("消失", "pill-gone"),
}


def _e(s: Any) -> str:
    return escape(str(s)) if s is not None else ""


def _pill(trend: str) -> str:
    label, css = TREND_LABELS.get(trend, (trend or "—", "pill-stable"))
    return f'<span class="pill {css}">{_e(label)}</span>'


def _stat_card(value: str, label: str, color: str) -> str:
    return f"""  <div class="stat-card">
    <div class="stat-value" style="color: {color};">{_e(value)}</div>
    <div class="stat-label">{_e(label)}</div>
  </div>"""


def _archetype_row(rank: int, a: Mapping[str, Any]) -> str:
    pct_text = f"{a.get('percentage', 0):.2f}"
    return (f'      <tr><td class="rank">{rank}</td>'
            f'<td class="archetype-name">{_e(a.get("archetype", ""))}</td>'
            f'<td class="count">{_e(a.get("count", ""))}</td>'
            f'<td class="pct">{_e(pct_text)}%</td>'
            f'<td>{_pill(a.get("trend", ""))}</td></tr>')


def _rec_card(tag: str, rec: Mapping[str, Any]) -> str:
    return f"""    <div class="rec-card {tag}">
      <span class="rec-tag">{_e(tag.replace('_', ' '))}</span>
      <div class="rec-name">{_e(rec.get('name',''))}</div>
      <a class="rec-url" href="{_e(rec.get('url','#'))}">{_e(rec.get('url',''))}</a>
      <div class="rec-rationale">{_e(rec.get('rationale',''))}</div>
      <div class="rec-effort">集成成本:<span class="effort-value">{_e(rec.get('integration_effort',''))}</span></div>
    </div>"""


def render(data: Mapping[str, Any]) -> str:
    period_start = data.get("period_start", "")
    period_end = data.get("period_end", date.today().isoformat())
    top_archetypes = data.get("top_archetypes", [])
    new_archetypes = data.get("new_archetypes", [])
    removed_archetypes = data.get("removed_archetypes", [])
    exec_summary = data.get("executive_summary", "")
    highlights = data.get("meta_snapshot_highlights", [])
    recs = data.get("source_recommendations", {})
    critical_gaps = data.get("critical_gaps", [])
    stats = data.get("stats", {})

    # Defaults for stats
    s_events = stats.get("events", "—")
    s_decks = stats.get("decks", "—")
    s_top_n = stats.get("top_n", len(top_archetypes))
    s_top_share = stats.get("top_share", (top_archetypes[0].get("percentage", 0) if top_archetypes else 0))
    s_matchup = stats.get("matchup_coverage", 0.30)

    # Hero
    cs = data.get("collection_scope", {})
    matchup_window = cs.get("window", "")
    matchup_fetched = cs.get("fetched_at", "")[:10] if cs.get("fetched_at") else ""
    hero = f"""<div class="hero">
  <div class="container">
    <h1>MTG Modern Meta Snapshot</h1>
    <div class="subtitle">数据驱动格式分析 · Period {period_start} ~ {period_end}</div>
    <div class="meta-row">
      <div class="meta-item"><div class="label">报告周期</div><div class="value">{period_start} ~ {period_end}</div></div>
      <div class="meta-item"><div class="label">生成时间</div><div class="value">{date.today().isoformat()}</div></div>
      {f'<div class="meta-item"><div class="label">Matchup 数据窗口</div><div class="value">{_e(matchup_window)}{(" · 抓取 " + _e(matchup_fetched)) if matchup_fetched else ""}</div></div>' if matchup_window else ''}
    </div>
  </div>
</div>"""

    # Stats
    stat_row = "\n".join([
        _stat_card(str(s_events), "赛事场次", "var(--accent)"),
        _stat_card(str(s_decks), "独立套牌", "var(--G)"),
        _stat_card(str(s_top_n), "Top 原型", "var(--new)"),
        _stat_card(f"{s_top_share:.2f}%", "Top1 占比", "var(--tier1)"),
        _stat_card(f"{s_matchup:.2f}", "对局覆盖率", "var(--nice)"),
    ])

    # Top 15 table
    rows = "\n".join(_archetype_row(i + 1, a) for i, a in enumerate(top_archetypes))
    table_section = f"""<div class="section">
  <h2 class="section-title">Top 原型 (Archetypes)</h2>
  <table class="archetype-table">
    <thead><tr><th>排名</th><th>原型</th><th style="text-align: right;">样本数</th>
      <th style="text-align: right;">占比</th><th>趋势</th></tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>
</div>"""

    # Shifts
    def shift_items(items, with_meta=False):
        out = []
        for it in items[:8]:
            name = it if isinstance(it, str) else it.get("name", "")
            meta = "" if isinstance(it, str) else it.get("meta", "")
            meta_html = f'<span class="meta">{_e(meta)}</span>' if meta else ""
            out.append(f'      <div class="shift-item"><span class="name">{_e(name)}</span>{meta_html}</div>')
        return "\n".join(out) if out else '      <div class="shift-item"><span class="name">—</span></div>'

    shifts = f"""<div class="section">
  <h2 class="section-title">环境迁移 (Meta Shifts)</h2>
  <div class="shifts-grid">
    <div class="shift-panel new">
      <h3>新出现原型 (New Archetypes)</h3>
{shift_items(new_archetypes)}
    </div>
    <div class="shift-panel removed">
      <h3>消失原型 (Removed / Faded)</h3>
{shift_items(removed_archetypes[:8])}
    </div>
  </div>
</div>"""

    # Highlights
    if highlights:
        items = "\n".join(f"      <li>{_e(h)}</li>" for h in highlights)
        highlights_html = f"""<div class="section">
  <h2 class="section-title">元快照要点 (Meta Snapshot Highlights)</h2>
  <div class="highlights">
    <ul>
{items}
    </ul>
  </div>
</div>"""
    else:
        highlights_html = ""

    # Collection scope (optional, from matchup_to_synthesis.py)
    cs = data.get("collection_scope")
    collection_html = ""
    if cs:
        passed = cs.get("passed", False)
        gate_results = cs.get("quality_gate_results", {})
        threshold_map = cs.get("quality_gate_thresholds", {})
        low_conf = cs.get("low_confidence", False)
        conf_banner = ""
        if low_conf:
            conf_banner = ('<div style="background: rgba(245,158,11,0.15); border-left: 4px solid var(--nice);'
                           ' padding: 12px 16px; margin: 12px 0; border-radius: 6px; font-size: 0.9rem;">'
                           '⚠ <b>低置信度</b>:Topdeck quality gate 未通过。下面 matchup 数据是探索性参考,'
                           '样本仅来自少数公开 per-player decklist 的事件。</div>')
        else:
            conf_banner = ('<div style="background: rgba(34,197,94,0.15); border-left: 4px solid var(--G);'
                           ' padding: 12px 16px; margin: 12px 0; border-radius: 6px; font-size: 0.9rem;">'
                           '✅ <b>质量门槛已通过</b>:matchup 数据置信度足够用于分析。</div>')

        sm = data.get("stats", {})
        rows = [
            ("数据源", f"{_e(cs.get('source','?'))} API"),
            ("格式", _e(cs.get("format","?"))),
            ("时间窗口", _e(cs.get("window","?"))),
            ("参赛者数过滤", f"≥ {_e(cs.get('participant_min','?'))} 选手"),
            ("Tables 维度", ", ".join(cs.get("tables_columns", [])) or "—"),
            ("Players 维度", ", ".join(cs.get("players_columns", [])) or "—"),
            ("抓取时间", _e(cs.get("fetched_at","?"))),
        ]
        scope_rows = "\n".join(
            f"        <tr><td style='color:var(--text-dim);'>{_e(k)}</td><td>{_e(v)}</td></tr>"
            for k, v in rows
        )

        # Friendly labels for gate keys
        gate_label_map = {
            "completed_events": "完成事件数",
            "classified_match_count": "已分类对局数",
            "classification_coverage": "玩家分类覆盖率",
            "top_pair_sample_count": "最高样本对位",
        }
        def _fmt_threshold(v):
            if isinstance(v, float) and v < 1:
                return f"≥ {v:.0%}"
            return f"≥ {v}"
        gate_rows = "\n".join(
            f"        <tr><td>{_e(gate_label_map.get(k, k))}</td>"
            f"<td style='text-align:right'>{'✅' if v else '❌'}</td>"
            f"<td style='text-align:right;color:var(--text-dim);'>{_e(_fmt_threshold(threshold_map.get(k, '?')))}</td></tr>"
            for k, v in gate_results.items()
        )

        collection_html = f"""<div class="section">
  <h2 class="section-title">数据采集范围 (Collection Scope)</h2>
  {conf_banner}
  <table class="archetype-table">
    <thead><tr><th style="width:30%;">参数</th><th>值</th></tr></thead>
    <tbody>
{scope_rows}
    </tbody>
  </table>
  <h3 style="font-size:1rem; margin: 24px 0 8px; color: var(--accent);">Quality Gate 详情</h3>
  <table class="archetype-table">
    <thead><tr><th>指标</th><th style="text-align:right">状态</th><th style="text-align:right">门槛</th></tr></thead>
    <tbody>
{gate_rows}
    </tbody>
  </table>
</div>"""

    # Winrate + Sideboard insights (optional, from matchup_to_synthesis.py)
    di = data.get("deck_insights")
    deck_html = ""
    if di and (di.get("top_overall_winrate") or di.get("featured_archetypes")):
        # Top 10 by winrate table
        top_wr = di.get("top_overall_winrate", [])
        def _wr_row(r):
            wr = r.get("winrate")
            wr_cell = f"{wr*100:.1f}%" if wr is not None else "—"
            return (f"        <tr><td>{_e(r['archetype'])}</td>"
                    f"<td style='text-align:right'>{_e(r.get('record', '—'))}</td>"
                    f"<td style='text-align:right'>{r.get('wl_record_count', 0)}</td>"
                    f"<td style='text-align:right'>{wr_cell}</td></tr>")
        wr_rows = "\n".join(_wr_row(r) for r in top_wr[:10])

        # Featured archetype cards with sideboard
        feat_cards = []
        for fa in di.get("featured_archetypes", []):
            arch = fa.get("archetype", "")
            wr = fa.get("winrate")
            wr_cell = f"{wr*100:.1f}%" if wr is not None else "—"
            record = fa.get("record", "—")
            top_cut = fa.get("top_cut_finishes", 0)
            sb = fa.get("sideboard_top", [])
            sb_items = "\n".join(
                f"        <li><b>{_e(c['card'])}</b> <span style='color:var(--text-dim);font-size:0.85rem;'>— {c.get('ubiquity',0)*100:.0f}%</span></li>"
                for c in sb[:6]
            )
            if not sb_items:
                sb_items = "        <li style='color:var(--text-dim);'>无足够样本</li>"
            feat_cards.append(f"""    <div class="rec-card" style="border-top-color: var(--accent);">
      <div class="rec-name">{_e(arch)}</div>
      <div style="display:flex; gap:16px; margin-bottom:10px; font-size:0.85rem;">
        <div><span style="color:var(--text-dim);">胜率</span> <b style="color:var(--G);">{wr_cell}</b></div>
        <div><span style="color:var(--text-dim);">战绩</span> <b>{_e(record)}</b></div>
        <div><span style="color:var(--text-dim);">Top 8</span> <b>{top_cut}</b></div>
      </div>
      <div class="rec-rationale" style="font-size:0.85rem; color:var(--text-dim); margin-bottom:6px;">高频备牌:</div>
      <ul class="highlights" style="background:transparent; padding:0; border:none;">
{sb_items}
      </ul>
    </div>""")
        feat_cards_html = "\n".join(feat_cards)

        deck_html = f"""<div class="section">
  <h2 class="section-title">原型表现 (Archetype Performance)</h2>

  <h3 style="font-size:1rem; margin-bottom: 8px; color: var(--G);">Top 10 胜率(全场样本,W-L 记录 ≥10)</h3>
  <table class="archetype-table">
    <thead><tr><th>原型</th><th style="text-align:right">战绩</th><th style="text-align:right">记录数</th><th style="text-align:right">胜率</th></tr></thead>
    <tbody>
{wr_rows}
    </tbody>
  </table>

  <h3 style="font-size:1rem; margin: 28px 0 12px; color: var(--accent);">重点原型备牌指南(基于本期已抓数据聚合)</h3>
  <div class="rec-grid">
{feat_cards_html}
  </div>
</div>"""

    # Matchup insights (optional, from matchup_to_synthesis.py)
    mi = data.get("matchup_insights")
    matchup_html = ""
    if mi and (mi.get("top_pairs_by_sample") or mi.get("polarized_pairs") or mi.get("archetype_summary")):
        low_conf = mi.get("low_confidence", False)
        warn = ('<div style="background: rgba(245,158,11,0.1); border-left: 4px solid var(--nice);'
                ' padding: 10px 16px; margin: 12px 0; border-radius: 6px; font-size: 0.85rem;">'
                '⚠ 低置信度:Topdeck quality gate 未通过,以下 matchup 数据仅作探索参考。</div>'
                if low_conf else "")

        # Top 10 archetype summary table
        def _arch_row(a):
            wr = a.get("winrate")
            wr_cell = f"{wr*100:.1f}%" if wr is not None else "—"
            return (f"        <tr><td>{_e(a['archetype'])}</td>"
                    f"<td style='text-align:right'>{a['games']}</td>"
                    f"<td style='text-align:right'>{wr_cell}</td></tr>")
        arch_rows = "\n".join(
            _arch_row(a) for a in mi.get("archetype_summary", [])[:10]
            if a.get("games", 0) >= 3
        )
        # Polarized pairs
        def _pol_li(p):
            wa = p.get("winrate_a"); wb = p.get("winrate_b")
            wa_s = f"{wa*100:.0f}%" if wa is not None else "—"
            wb_s = f"{wb*100:.0f}%" if wb is not None else "—"
            return (f"        <li><b>{_e(p['a'])}</b> vs <b>{_e(p['b'])}</b>: "
                    f"{p['games']} games, {wa_s} / {wb_s}</li>")
        pol_items = "\n".join(_pol_li(p) for p in mi.get("polarized_pairs", [])[:8])
        if not pol_items:
            pol_items = "        <li>— (无足够样本的对位数据)</li>"

        matchup_html = f"""<div class="section">
  <h2 class="section-title">原型对局数据 (Matchup Data)</h2>
  {warn}
  <h3 style="font-size:1rem; margin: 12px 0 8px; color: var(--accent);">Top 10 原型聚合胜率(样本≥3)</h3>
  <table class="archetype-table">
    <thead><tr><th>原型</th><th style="text-align:right">对局数</th><th style="text-align:right">胜率</th></tr></thead>
    <tbody>
{arch_rows}
    </tbody>
  </table>
  <h3 style="font-size:1rem; margin: 24px 0 8px; color: var(--nice);">极端对位(样本≥3 且胜率≥70% 一方)</h3>
  <div class="highlights"><ul>
{pol_items}
  </ul></div>
</div>"""

    # Gap analysis (only if critical_gaps provided)
    if critical_gaps:
        gap_items = "\n".join(
            f"""    <div class="gap-item high">
      <span class="severity">高优先级</span>
      <div class="body">
        <div class="title">{_e(g.split('—')[0].strip() if '—' in g else g[:60])}</div>
        <div class="desc">{_e(g)}</div>
      </div>
    </div>""" for g in critical_gaps[:5])
        gaps_html = f"""<div class="section">
  <h2 class="section-title">数据源缺口分析 (Data Source Gap Analysis)</h2>
  <div class="gap-list">
{gap_items}
  </div>
</div>"""
    else:
        gaps_html = ""

    # Recommendations
    def rec_block(tag, items):
        if not items:
            return ""
        cards = "\n".join(_rec_card(tag, r) for r in items)
        color = {"must_add": "var(--must)", "nice_to_have": "var(--nice)", "skip": "var(--skip)"}[tag]
        label_zh = {"must_add": "必加 (Must Add)", "nice_to_have": "可选 (Nice to Have)", "skip": "跳过 (Skip)"}[tag]
        return f"""  <h3 style="color: {color}; font-size: 1rem; margin-bottom: 12px;">{label_zh}</h3>
  <div class="rec-grid">
{cards}
  </div>"""

    recs_html_parts = []
    for tag in ("must_add", "nice_to_have", "skip"):
        block = rec_block(tag, recs.get(tag, []))
        if block:
            recs_html_parts.append(block)
    recs_html = ""
    if recs_html_parts:
        recs_html = f"""<div class="section">
  <h2 class="section-title">数据源建议 (Recommendations)</h2>
{chr(10).join(recs_html_parts)}
</div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MTG Modern Meta Snapshot ({period_start} ~ {period_end})</title>
<style>{CSS}</style>
</head>
<body>

{hero}

<div class="container">

<!-- Quick Stats -->
<div class="stats-row">
{stat_row}
</div>

<!-- Executive Summary -->
<div class="section">
  <h2 class="section-title">执行摘要 (Executive Summary)</h2>
  <div class="section-body">{_e(exec_summary)}</div>
</div>

{table_section}
{shifts}
{highlights_html}
{collection_html}
{deck_html}
{matchup_html}
{gaps_html}
{recs_html}

</div>

<footer>
  <div class="container">
    <div>MTG Modern Meta Snapshot · Generated {date.today().isoformat()} · Period {period_start} ~ {period_end}</div>
    <div style="margin-top: 6px;">数据驱动报告 · dark indigo/slate theme · static HTML</div>
  </div>
</footer>

</body>
</html>"""


def render_to_file(data: Mapping[str, Any], out_path: Union[str, Path]) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data), encoding="utf-8")
    return out


def main():
    p = argparse.ArgumentParser(description="Render meta snapshot HTML from synthesis JSON.")
    p.add_argument("--in", dest="in_path", required=True, help="Path to synthesis JSON")
    p.add_argument("--out", required=True, help="Output HTML path")
    p.add_argument("--stats", help="Optional stats JSON file (events, decks, top_n, top_share, matchup_coverage)")
    args = p.parse_args()

    with open(args.in_path, encoding="utf-8") as f:
        data = json.load(f)
    if args.stats:
        with open(args.stats, encoding="utf-8") as f:
            data["stats"] = json.load(f)

    out = render_to_file(data, args.out)
    print(f"Wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
