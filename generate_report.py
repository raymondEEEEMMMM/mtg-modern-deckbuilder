#!/usr/bin/env python3
"""Generate Modern Metagame HTML Report from evaluation data."""

import json
import os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "mtg_modern_data", "decks")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def tier_color(tier):
    return {
        "Tier 1": "#ef4444",
        "Tier 2": "#f59e0b",
        "Tier 3": "#3b82f6",
        "Tier 4": "#6b7280",
    }.get(tier, "#6b7280")


def category_icon(cat):
    return {
        "aggro": "&#9876;",
        "control": "&#128737;",
        "combo": "&#9889;",
        "tempo": "&#127919;",
        "unknown": "&#10068;",
    }.get(cat, "&#10068;")


def category_label(cat):
    return {
        "aggro": "Aggro",
        "control": "Control",
        "combo": "Combo",
        "tempo": "Tempo",
        "unknown": "Other",
    }.get(cat, "Other")


def share_bar_pct(share, max_share):
    if max_share == 0:
        return 0
    return min(100, (share / max_share) * 100)


def generate_html():
    fused = load_json(os.path.join(DATA_DIR, "processed", "fused_archetypes.json"))
    top_n = load_json(os.path.join(DATA_DIR, "top_n", "top_decks.json"))
    config = load_json(os.path.join(DATA_DIR, "fusion_config.json"))

    archetypes = fused["archetypes"]
    max_share = max(a["fused_metagame_share"] for a in archetypes)

    # Tier distribution
    tier_dist = fused["tier_distribution"]
    cat_dist = fused["category_distribution"]

    # Top 10 for hero section
    top10 = top_n["decks"]

    # Category breakdown data
    categories = {}
    for a in archetypes:
        cat = a["category"]
        if cat not in categories:
            categories[cat] = {"total_share": 0, "count": 0, "decks": []}
        categories[cat]["total_share"] += a["fused_metagame_share"]
        categories[cat]["count"] += 1
        categories[cat]["decks"].append(a)

    # Source coverage
    both_count = sum(1 for a in archetypes if a["sources"].get("mtgtop8") and a["sources"].get("goldfish"))
    top8_only = sum(1 for a in archetypes if a["sources"].get("mtgtop8") and not a["sources"].get("goldfish"))
    gf_only = sum(1 for a in archetypes if not a["sources"].get("mtgtop8") and a["sources"].get("goldfish"))

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Modern Metagame Report - {fused['generated_date']}</title>
<style>
  :root {{
    --bg: #0f172a;
    --card: #1e293b;
    --card-hover: #334155;
    --border: #334155;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --accent: #818cf8;
    --accent2: #6366f1;
    --tier1: #ef4444;
    --tier2: #f59e0b;
    --tier3: #3b82f6;
    --tier4: #6b7280;
    --aggro: #f97316;
    --combo: #a855f7;
    --control: #06b6d4;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
  }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 0 20px; }}

  /* Hero */
  .hero {{
    background: linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #1e1b4b 100%);
    padding: 48px 0 36px;
    border-bottom: 1px solid var(--border);
  }}
  .hero h1 {{
    font-size: 2.4rem;
    font-weight: 800;
    background: linear-gradient(135deg, #c7d2fe, #818cf8);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 8px;
  }}
  .hero .subtitle {{ color: var(--text-dim); font-size: 1.1rem; }}
  .hero .meta-row {{
    display: flex;
    gap: 24px;
    margin-top: 20px;
    flex-wrap: wrap;
  }}
  .hero .meta-item {{
    background: rgba(255,255,255,0.06);
    border-radius: 8px;
    padding: 10px 16px;
    font-size: 0.9rem;
  }}
  .hero .meta-item .label {{ color: var(--text-dim); font-size: 0.8rem; }}
  .hero .meta-item .value {{ color: var(--accent); font-weight: 600; font-size: 1.1rem; }}

  /* Stats Row */
  .stats-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin: 32px 0;
  }}
  .stat-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    text-align: center;
  }}
  .stat-card .stat-value {{
    font-size: 2rem;
    font-weight: 800;
    margin-bottom: 4px;
  }}
  .stat-card .stat-label {{ color: var(--text-dim); font-size: 0.85rem; }}

  /* Section */
  .section {{ margin: 40px 0; }}
  .section-title {{
    font-size: 1.4rem;
    font-weight: 700;
    margin-bottom: 20px;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--accent2);
    display: inline-block;
  }}

  /* Tier Table */
  .tier-table {{
    width: 100%;
    border-collapse: collapse;
    background: var(--card);
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid var(--border);
  }}
  .tier-table th {{
    background: rgba(99,102,241,0.15);
    padding: 12px 16px;
    text-align: left;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--accent);
  }}
  .tier-table td {{
    padding: 12px 16px;
    border-top: 1px solid var(--border);
    font-size: 0.9rem;
  }}
  .tier-table tr:hover {{ background: var(--card-hover); }}
  .tier-badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 700;
    color: #fff;
  }}
  .cat-badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
  }}
  .share-bar-bg {{
    background: rgba(255,255,255,0.08);
    border-radius: 4px;
    height: 20px;
    width: 100%;
    position: relative;
    overflow: hidden;
  }}
  .share-bar-fill {{
    height: 100%;
    border-radius: 4px;
    transition: width 0.5s ease;
  }}
  .share-bar-text {{
    position: absolute;
    right: 6px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 0.7rem;
    font-weight: 600;
    color: #fff;
    text-shadow: 0 1px 2px rgba(0,0,0,0.5);
  }}
  .key-cards {{ display: flex; gap: 4px; flex-wrap: wrap; }}
  .key-card-tag {{
    background: rgba(168,85,247,0.15);
    border: 1px solid rgba(168,85,247,0.3);
    color: #c084fc;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.7rem;
  }}
  .source-dot {{
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-right: 2px;
  }}

  /* Pie-like visual */
  .dist-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
  }}
  .dist-panel {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
  }}
  .dist-panel h3 {{
    font-size: 1rem;
    margin-bottom: 16px;
    color: var(--accent);
  }}
  .dist-bar-item {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 10px;
  }}
  .dist-bar-label {{
    width: 100px;
    font-size: 0.85rem;
    text-align: right;
    flex-shrink: 0;
  }}
  .dist-bar-track {{
    flex: 1;
    background: rgba(255,255,255,0.06);
    border-radius: 6px;
    height: 24px;
    overflow: hidden;
    position: relative;
  }}
  .dist-bar-val {{
    height: 100%;
    border-radius: 6px;
    display: flex;
    align-items: center;
    padding-left: 8px;
    font-size: 0.75rem;
    font-weight: 600;
    color: #fff;
  }}
  .dist-bar-pct {{
    color: var(--text-dim);
    font-size: 0.8rem;
    width: 50px;
    text-align: right;
    flex-shrink: 0;
  }}

  /* Source coverage */
  .source-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    margin-top: 16px;
  }}
  .source-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    text-align: center;
  }}
  .source-card .sc-value {{ font-size: 1.8rem; font-weight: 800; }}
  .source-card .sc-label {{ color: var(--text-dim); font-size: 0.85rem; margin-top: 4px; }}

  /* Fusion formula */
  .formula-box {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
    margin: 20px 0;
  }}
  .formula-box code {{
    display: block;
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.95rem;
    color: #a5f3fc;
    margin: 8px 0;
    padding: 8px 12px;
    background: rgba(0,0,0,0.3);
    border-radius: 6px;
  }}

  /* Top 10 Hero Cards */
  .top10-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px;
  }}
  .deck-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    position: relative;
    transition: border-color 0.2s;
  }}
  .deck-card:hover {{ border-color: var(--accent); }}
  .deck-card .rank {{
    position: absolute;
    top: -8px;
    right: 16px;
    font-size: 2.4rem;
    font-weight: 900;
    opacity: 0.15;
    color: var(--accent);
  }}
  .deck-card .deck-name {{
    font-size: 1.1rem;
    font-weight: 700;
    margin-bottom: 6px;
  }}
  .deck-card .deck-score {{
    font-size: 1.8rem;
    font-weight: 800;
    margin: 4px 0;
  }}
  .deck-card .deck-meta {{
    display: flex;
    gap: 8px;
    margin-bottom: 10px;
    flex-wrap: wrap;
  }}
  .deck-card .deck-share {{
    color: var(--text-dim);
    font-size: 0.85rem;
    margin-top: 4px;
  }}
  .deck-card .mini-bar-bg {{
    background: rgba(255,255,255,0.06);
    border-radius: 3px;
    height: 6px;
    margin-top: 6px;
    overflow: hidden;
  }}
  .deck-card .mini-bar-fill {{
    height: 100%;
    border-radius: 3px;
  }}

  footer {{
    text-align: center;
    padding: 32px 0;
    color: var(--text-dim);
    font-size: 0.8rem;
    border-top: 1px solid var(--border);
    margin-top: 48px;
  }}

  @media (max-width: 768px) {{
    .dist-grid {{ grid-template-columns: 1fr; }}
    .source-grid {{ grid-template-columns: 1fr; }}
    .hero h1 {{ font-size: 1.8rem; }}
  }}
</style>
</head>
<body>

<!-- Hero -->
<div class="hero">
  <div class="container">
    <h1>Modern Metagame Report</h1>
    <div class="subtitle">MTG Modern 赛制环境强度评估报告</div>
    <div class="meta-row">
      <div class="meta-item">
        <div class="label">数据日期</div>
        <div class="value">{fused['generated_date']}</div>
      </div>
      <div class="meta-item">
        <div class="label">统计周期</div>
        <div class="value">{fused['period_start']} ~ {fused['generated_date']}</div>
      </div>
      <div class="meta-item">
        <div class="label">总 Archetype</div>
        <div class="value">{fused['total_archetypes']}</div>
      </div>
      <div class="meta-item">
        <div class="label">数据源</div>
        <div class="value">MTGTop8 + MTGGoldfish</div>
      </div>
    </div>
  </div>
</div>

<div class="container">

<!-- Summary Stats -->
<div class="stats-row">
  <div class="stat-card">
    <div class="stat-value" style="color: var(--tier1)">{tier_dist.get('Tier 1', 0)}</div>
    <div class="stat-label">Tier 1 套牌</div>
  </div>
  <div class="stat-card">
    <div class="stat-value" style="color: var(--tier2)">{tier_dist.get('Tier 2', 0)}</div>
    <div class="stat-label">Tier 2 套牌</div>
  </div>
  <div class="stat-card">
    <div class="stat-value" style="color: var(--tier3)">{tier_dist.get('Tier 3', 0)}</div>
    <div class="stat-label">Tier 3 套牌</div>
  </div>
  <div class="stat-card">
    <div class="stat-value" style="color: var(--tier4)">{tier_dist.get('Tier 4', 0)}</div>
    <div class="stat-label">Tier 4 套牌</div>
  </div>
</div>

<!-- Formula -->
<div class="section">
  <div class="section-title">评估模型</div>
  <div class="formula-box">
    <div style="color: var(--text-dim); font-size:0.85rem;">强度评分公式：</div>
    <code>strength = 0.40 × 融合出场率 + 0.35 × 名次表现 + 0.15 × 样本置信度 + 0.10 × 冠军指标</code>
    <div style="color: var(--text-dim); font-size:0.85rem; margin-top:8px;">融合出场率：</div>
    <code>fused_share = 0.6 × Top8_share + 0.4 × Goldfish_corrected_share</code>
    <div style="color: var(--text-dim); font-size:0.85rem; margin-top:8px;">League膨胀修正：</div>
    <code>corrected_share = raw_share × (1 - 0.35) &nbsp;&nbsp;<!-- League占60%样本但置信度仅0.3 --></code>
  </div>
</div>

<!-- Top 10 Cards -->
<div class="section">
  <div class="section-title">Top 10 强势套牌</div>
  <div class="top10-grid">
"""

    for a in top10:
        tc = tier_color(a["tier"])
        cat_clr = {"aggro": "var(--aggro)", "combo": "var(--combo)", "control": "var(--control)"}.get(a["category"], "var(--text-dim)")
        bar_pct = share_bar_pct(a["fused_metagame_share"], max_share)
        bar_color = tc

        key_cards_html = ""
        for kc in a.get("key_cards", []):
            key_cards_html += f'<span class="key-card-tag">{kc}</span>'

        html += f"""
    <div class="deck-card">
      <div class="rank">{a['rank']}</div>
      <div class="deck-name">{a['name']}</div>
      <div class="deck-meta">
        <span class="tier-badge" style="background:{tc}">{a['tier']}</span>
        <span class="cat-badge" style="background:{cat_clr}; color:#fff">{category_icon(a['category'])} {category_label(a['category'])}</span>
      </div>
      <div class="deck-score" style="color:{tc}">{a['strength_score']}</div>
      <div class="deck-share">出场率 {a['fused_metagame_share']*100:.1f}% &nbsp;|&nbsp; 名次分 {a['performance_score']:.3f}</div>
      <div class="mini-bar-bg">
        <div class="mini-bar-fill" style="width:{bar_pct}%; background:{bar_color};"></div>
      </div>
      {'<div class="key-cards" style="margin-top:10px">' + key_cards_html + '</div>' if key_cards_html else ''}
    </div>"""

    html += f"""
  </div>
</div>

<!-- Full Table -->
<div class="section">
  <div class="section-title">全量 Archetype 排名</div>
  <table class="tier-table">
    <thead>
      <tr>
        <th>#</th>
        <th>套牌</th>
        <th>Tier</th>
        <th>分类</th>
        <th>强度评分</th>
        <th>融合出场率</th>
        <th>出场率分布</th>
        <th>名次分</th>
        <th>核心卡牌</th>
        <th>数据源</th>
      </tr>
    </thead>
    <tbody>
"""

    for i, a in enumerate(archetypes, 1):
        tc = tier_color(a["tier"])
        cat_clr = {"aggro": "var(--aggro)", "combo": "var(--combo)", "control": "var(--control)"}.get(a["category"], "var(--text-dim)")
        bar_pct = share_bar_pct(a["fused_metagame_share"], max_share)

        key_cards_html = ""
        for kc in a.get("key_cards", []):
            if kc:
                key_cards_html += f'<span class="key-card-tag">{kc}</span>'

        # Source dots
        has_top8 = a["sources"].get("mtgtop8") is not None
        has_gf = a["sources"].get("goldfish") is not None
        src_html = ""
        if has_top8:
            src_html += '<span class="source-dot" style="background:#22d3ee" title="MTGTop8"></span>'
        if has_gf:
            src_html += '<span class="source-dot" style="background:#a855f7" title="Goldfish"></span>'

        html += f"""
      <tr>
        <td style="font-weight:700; color:var(--text-dim)">{i}</td>
        <td style="font-weight:600">{a['name']}</td>
        <td><span class="tier-badge" style="background:{tc}">{a['tier']}</span></td>
        <td><span class="cat-badge" style="background:{cat_clr}; color:#fff; font-size:0.7rem">{category_icon(a['category'])} {category_label(a['category'])}</span></td>
        <td style="font-weight:700; color:{tc}">{a['strength_score']}</td>
        <td>{a['fused_metagame_share']*100:.2f}%</td>
        <td style="min-width:120px">
          <div class="share-bar-bg">
            <div class="share-bar-fill" style="width:{bar_pct}%; background:{tc}"></div>
            <span class="share-bar-text">{a['fused_metagame_share']*100:.1f}%</span>
          </div>
        </td>
        <td>{a['performance']['score']:.3f}</td>
        <td><div class="key-cards">{key_cards_html or '<span style="color:var(--text-dim);font-size:0.75rem">-</span>'}</div></td>
        <td>{src_html}</td>
      </tr>"""

    html += f"""
    </tbody>
  </table>
</div>

<!-- Distribution -->
<div class="section">
  <div class="section-title">环境分布</div>
  <div class="dist-grid">
    <div class="dist-panel">
      <h3>Tier 分布</h3>
"""

    tier_colors_map = {"Tier 1": "#ef4444", "Tier 2": "#f59e0b", "Tier 3": "#3b82f6", "Tier 4": "#6b7280"}
    total_decks_in_dist = sum(tier_dist.values())
    for tier_name, count in tier_dist.items():
        pct = count / total_decks_in_dist * 100 if total_decks_in_dist else 0
        clr = tier_colors_map.get(tier_name, "#6b7280")
        html += f"""
      <div class="dist-bar-item">
        <div class="dist-bar-label" style="color:{clr}">{tier_name}</div>
        <div class="dist-bar-track">
          <div class="dist-bar-val" style="width:{pct}%; background:{clr}">{count}</div>
        </div>
        <div class="dist-bar-pct">{pct:.0f}%</div>
      </div>"""

    html += """
    </div>
    <div class="dist-panel">
      <h3>分类分布</h3>
"""

    cat_colors_map = {"aggro": "#f97316", "combo": "#a855f7", "control": "#06b6d4", "tempo": "#22c55e", "unknown": "#6b7280"}
    total_in_cat = sum(cat_dist.values())
    for cat_name, count in cat_dist.items():
        pct = count / total_in_cat * 100 if total_in_cat else 0
        clr = cat_colors_map.get(cat_name, "#6b7280")
        html += f"""
      <div class="dist-bar-item">
        <div class="dist-bar-label" style="color:{clr}">{category_icon(cat_name)} {category_label(cat_name)}</div>
        <div class="dist-bar-track">
          <div class="dist-bar-val" style="width:{pct}%; background:{clr}">{count}</div>
        </div>
        <div class="dist-bar-pct">{pct:.0f}%</div>
      </div>"""

    html += f"""
    </div>
  </div>
</div>

<!-- Source Coverage -->
<div class="section">
  <div class="section-title">数据源覆盖</div>
  <div class="source-grid">
    <div class="source-card">
      <div class="sc-value" style="color:#22d3ee">{both_count}</div>
      <div class="sc-label">双源覆盖</div>
      <div style="margin-top:8px">
        <span class="source-dot" style="background:#22d3ee"></span>
        <span class="source-dot" style="background:#a855f7"></span>
      </div>
    </div>
    <div class="source-card">
      <div class="sc-value" style="color:#22d3ee">{top8_only}</div>
      <div class="sc-label">仅 MTGTop8</div>
      <div style="margin-top:8px">
        <span class="source-dot" style="background:#22d3ee"></span>
      </div>
    </div>
    <div class="source-card">
      <div class="sc-value" style="color:#a855f7">{gf_only}</div>
      <div class="sc-label">仅 Goldfish</div>
      <div style="margin-top:8px">
        <span class="source-dot" style="background:#a855f7"></span>
      </div>
    </div>
  </div>
</div>

<!-- Top 3 Category Leaders -->
<div class="section">
  <div class="section-title">各分类领军套牌</div>
  <table class="tier-table">
    <thead>
      <tr><th>分类</th><th>领军套牌</th><th>强度</th><th>出场率</th><th>名次分</th><th>核心卡牌</th></tr>
    </thead>
    <tbody>
"""

    for cat in ["aggro", "combo", "control"]:
        if cat in categories:
            leader = categories[cat]["decks"][0]
            cat_clr = cat_colors_map.get(cat, "#6b7280")
            kc_html = "".join(f'<span class="key-card-tag">{kc}</span>' for kc in leader.get("key_cards", []) if kc)
            html += f"""
      <tr>
        <td><span class="cat-badge" style="background:{cat_clr}; color:#fff">{category_icon(cat)} {category_label(cat)}</span></td>
        <td style="font-weight:700">{leader['name']}</td>
        <td style="font-weight:700; color:{tier_color(leader['tier'])}">{leader['strength_score']}</td>
        <td>{leader['fused_metagame_share']*100:.2f}%</td>
        <td>{leader['performance']['score']:.3f}</td>
        <td><div class="key-cards">{kc_html or '-'}</div></td>
      </tr>"""

    html += f"""
    </tbody>
  </table>
</div>

<!-- Fusion Config Notes -->
<div class="section">
  <div class="section-title">方法论备注</div>
  <div class="formula-box" style="font-size:0.9rem;">
    <div style="margin-bottom:12px;"><strong style="color:var(--accent)">数据源权重</strong></div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px;">
      <div>
        <span style="color:#22d3ee; font-weight:600;">MTGTop8 (0.6)</span>
        <div style="color:var(--text-dim); font-size:0.8rem;">完整archetype覆盖 | 预分类标签 | 聚合不透明</div>
      </div>
      <div>
        <span style="color:#a855f7; font-weight:600;">MTGGoldfish (0.4)</span>
        <div style="color:var(--text-dim); font-size:0.8rem;">名次数据 | 核心卡牌验证 | League膨胀 | 只Top15</div>
      </div>
    </div>
    <div style="margin-bottom:12px;"><strong style="color:var(--accent)">League膨胀修正</strong></div>
    <div style="color:var(--text-dim); font-size:0.85rem;">
      Goldfish的metagame_share中League 5-0占总样本约60%，但只展示全胜战绩，存在严重选择偏差。<br>
      修正系数0.35：Affinity修正后10.7% ≈ Top8的12%，验证修正合理。
    </div>
    <div style="margin-top:12px; margin-bottom:12px;"><strong style="color:var(--accent)">Tier分级标准</strong></div>
    <div style="color:var(--text-dim); font-size:0.85rem;">
      Tier 1: score ≥ 50 或 share ≥ 8% &nbsp;|&nbsp;
      Tier 2: score ≥ 25 或 share ≥ 3% &nbsp;|&nbsp;
      Tier 3: score ≥ 10 或 share ≥ 1% &nbsp;|&nbsp;
      Tier 4: 其余
    </div>
    <div style="margin-top:12px;"><strong style="color:var(--accent)">命名映射</strong>（Goldfish → Top8）</div>
    <div style="color:var(--text-dim); font-size:0.85rem; margin-top:4px;">
      Belcher → Landless &nbsp;|&nbsp;
      Boros Energy → Boros Aggro &nbsp;|&nbsp;
      Neobrand → Allosaurus Combo &nbsp;|&nbsp;
      Esper GenericBlink → Blink
    </div>
  </div>
</div>

</div>

<footer>
  <div class="container">
    MTG Modern Metagame Report &middot; Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} &middot; Data: MTGTop8 + MTGGoldfish
  </div>
</footer>

</body>
</html>"""

    return html


if __name__ == "__main__":
    report = generate_html()
    output_path = os.path.join(
        os.path.dirname(__file__), "mtg_modern_data", "decks", "report.html"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Report generated: {output_path}")
