#!/usr/bin/env python3
"""
Exit Velocity × Launch Angle — Contact Quality Heat Map
League-average heat map (BA / SLG / HR%) with player overlay.

Usage:
    python ev_la_heatmap.py                 # Full 2026 season to date
    python ev_la_heatmap.py --year 2025
    python ev_la_heatmap.py --out my.html
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

try:
    from pybaseball import statcast
    from pybaseball import cache
    cache.enable()
except ImportError:
    print("ERROR: pybaseball not installed. Run: pip install pybaseball")
    sys.exit(1)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="EV x LA Contact Quality Heat Map")
    parser.add_argument("--years", nargs="+", type=int, default=[2025, datetime.today().year],
                        help="Season years to include e.g. --years 2025 2026")
    parser.add_argument("--out",   default="/Users/michaelharman/Projects/EV_LA_HEATMAP/ev_la_heatmap.html")
    return parser.parse_args()


# ─── CONSTANTS ────────────────────────────────────────────────────────────────

EV_MIN, EV_MAX, EV_STEP = 50, 120, 5
LA_MIN, LA_MAX, LA_STEP = -30, 60,  5
MIN_AB = 5


# ─── wOBA WEIGHTS ─────────────────────────────────────────────────────────────

HITS    = {"single", "double", "triple", "home_run"}
SLG_MAP = {"single": 1, "double": 2, "triple": 3, "home_run": 4}


# ─── DATA FETCH ───────────────────────────────────────────────────────────────

def fetch_season(year):
    start = f"{year}-03-26"
    today = datetime.today()
    # For past seasons use end of season; for current use today
    end   = f"{year}-11-01" if year < today.year else today.strftime("%Y-%m-%d")
    print(f"Fetching {year}: {start} to {end}")
    df = statcast(start_dt=start, end_dt=end)
    df = df[df["game_type"] == "R"].copy()
    df["season"] = year
    print(f"  {len(df):,} plate appearances")
    return df


def add_batter_name(df):
    if "batter_name" in df.columns:
        return df
    if "des" in df.columns:
        df["batter_name"] = (
            df["des"]
            .str.extract(r"^([A-Za-z\s'\-\.]+?)(?:\s+(?:homers|hits|singles|doubles|triples|grounds|flies|lines|pops|strikes|walks|reaches))")[0]
            .str.strip()
        )
    else:
        df["batter_name"] = df["player_name"]
    return df


# ─── OUTCOME CALCULATIONS ─────────────────────────────────────────────────────

NON_AB_EVENTS = {"walk", "hit_by_pitch", "sac_fly", "sac_bunt", "sac_fly_double_play", "catcher_interf"}

def compute_outcomes(grp):
    # True AB: exclude walks, HBP, sac flies, sac bunts
    ab_mask = ~grp["events"].isin(NON_AB_EVENTS) & grp["events"].notna()
    ab   = int(ab_mask.sum())
    hits = int(grp["events"].isin(HITS).sum())
    hrs  = int((grp["events"] == "home_run").sum())
    slg  = grp["events"].map(SLG_MAP).fillna(0).sum()
    # OBP for this group
    bb  = int((grp["events"] == "walk").sum())
    hbp = int((grp["events"] == "hit_by_pitch").sum())
    sf  = int(grp["events"].isin({"sac_fly","sac_fly_double_play"}).sum())
    obp_den = ab + bb + hbp + sf
    obp = round((hits + bb + hbp) / obp_den, 3) if obp_den else 0
    slg_val = round(float(slg) / ab, 3) if ab else 0
    return {
        "ab":      ab,
        "hits":    hits,
        "hrs":     hrs,
        "ba":      round(hits / ab, 3)  if ab else 0,
        "slg":     slg_val,
        "obp":     obp,
        "ops":     round(obp + slg_val, 3),
        "hr_rate": round(hrs / ab, 3)   if ab else 0,
    }


# ─── GRID BUILDER ─────────────────────────────────────────────────────────────

def bucket(val, mn, step):
    return int(((val - mn) // step) * step + mn)


def build_grid(df):
    # ── Compute true league totals from ALL plate appearances first ──
    all_pa = df[df["events"].notna()].copy()
    lg_ab_mask   = ~all_pa["events"].isin(NON_AB_EVENTS)
    lg_ab_total  = int(lg_ab_mask.sum())
    lg_hits      = int(all_pa["events"].isin(HITS).sum())
    lg_hrs       = int((all_pa["events"] == "home_run").sum())
    lg_slg       = all_pa["events"].map(SLG_MAP).fillna(0).sum()
    # OBP: (H + BB + HBP) / (AB + BB + HBP + SF)
    lg_bb        = int((all_pa["events"] == "walk").sum())
    lg_hbp       = int((all_pa["events"] == "hit_by_pitch").sum())
    lg_sf        = int(all_pa["events"].isin({"sac_fly", "sac_fly_double_play"}).sum())
    lg_pa_total  = int(all_pa["events"].notna().sum())
    lg_obp_num   = lg_hits + lg_bb + lg_hbp
    lg_obp_den   = lg_ab_total + lg_bb + lg_hbp + lg_sf

    # ── Now filter to EV/LA batted balls for the grid ──
    df = df[
        (df["launch_speed"] >= EV_MIN) & (df["launch_speed"] <= EV_MAX) &
        (df["launch_angle"] >= LA_MIN) & (df["launch_angle"] <= LA_MAX) &
        df["events"].notna() &
        df["launch_speed"].notna() &
        df["launch_angle"].notna()
    ].copy()
    df["ev_b"] = df["launch_speed"].apply(lambda v: bucket(v, EV_MIN, EV_STEP))
    df["la_b"] = df["launch_angle"].apply(lambda v: bucket(v, LA_MIN, LA_STEP))

    ev_labels = list(range(EV_MIN, EV_MAX, EV_STEP))
    la_labels = list(range(LA_MIN, LA_MAX, LA_STEP))

    grid_map = {}
    for (ev, la), grp in df.groupby(["ev_b", "la_b"]):
        outcomes = compute_outcomes(grp)
        if outcomes["ab"] >= MIN_AB:
            grid_map[(int(ev), int(la))] = outcomes

    cells = []
    for ev in ev_labels:
        row = []
        for la in la_labels:
            row.append(grid_map.get((ev, la)))
        cells.append(row)

    ab_mask    = ~df["events"].isin(NON_AB_EVENTS) & df["events"].notna()
    ab_total   = int(ab_mask.sum())

    lg_ba  = round(lg_hits / lg_ab_total, 3)          if lg_ab_total else 0
    lg_slg = round(float(lg_slg) / lg_ab_total, 3)    if lg_ab_total else 0
    lg_obp = round(lg_obp_num / lg_obp_den, 3)        if lg_obp_den  else 0
    lg_ops = round(lg_obp + lg_slg, 3)

    # ── Histograms — batted balls with EV/LA only, grouped by 5 ──
    bip = df  # already filtered to EV/LA batted balls
    ev_hist_buckets = list(range(EV_MIN, EV_MAX, EV_STEP))
    la_hist_buckets = list(range(LA_MIN, LA_MAX, LA_STEP))
    ev_hist = {b: int(((bip["launch_speed"] >= b) & (bip["launch_speed"] < b + EV_STEP)).sum()) for b in ev_hist_buckets}
    la_hist = {b: int(((bip["launch_angle"] >= b) & (bip["launch_angle"] < b + LA_STEP)).sum()) for b in la_hist_buckets}
    avg_ev  = round(float(bip["launch_speed"].mean()), 1) if len(bip) else 0
    avg_la  = round(float(bip["launch_angle"].mean()), 1) if len(bip) else 0

    # BA/SLG per EV and LA bucket (contact rate — balls in play only)
    def bucket_stats(sub):
        ab = len(sub)
        if ab == 0:
            return None
        hits = int(sub["events"].isin(HITS).sum())
        slg  = float(sub["events"].map(SLG_MAP).fillna(0).sum())
        return {"ab": ab, "ba": round(hits/ab, 3), "slg": round(slg/ab, 3)}

    ev_stats = [bucket_stats(bip[(bip["launch_speed"] >= b) & (bip["launch_speed"] < b + EV_STEP)]) for b in ev_hist_buckets]
    la_stats = [bucket_stats(bip[(bip["launch_angle"] >= b) & (bip["launch_angle"] < b + LA_STEP)]) for b in la_hist_buckets]

    return {
        "ev_labels":    ev_labels,
        "la_labels":    la_labels,
        "cells":        cells,
        "total_pa":     lg_pa_total,
        "league_ba":    lg_ba,
        "league_slg":   lg_slg,
        "league_obp":   lg_obp,
        "league_ops":   lg_ops,
        "league_hr":    round(lg_hrs / lg_ab_total, 3) if lg_ab_total else 0,
        "ev_hist":      [ev_hist.get(b, 0) for b in ev_hist_buckets],
        "la_hist":      [la_hist.get(b, 0) for b in la_hist_buckets],
        "ev_stats":     ev_stats,
        "la_stats":     la_stats,
        "avg_ev":       avg_ev,
        "avg_la":       avg_la,
    }



# ─── PLAYER PROFILES ──────────────────────────────────────────────────────────

def build_player_profiles(df):
    """True BA/SLG from all PAs; BIP subset for grid overlay and histograms."""
    # Full PA — all events, for true BA/SLG
    full = df[df["events"].notna() & df["batter_name"].notna()].copy()

    # BIP subset — EV/LA data only, for grid dots and histograms
    bip_df = full[
        full["launch_speed"].between(EV_MIN, EV_MAX) &
        full["launch_angle"].between(LA_MIN, LA_MAX) &
        full["launch_speed"].notna() &
        full["launch_angle"].notna()
    ].copy()

    players = {}
    for name, full_grp in full.groupby("batter_name"):
        bip_grp = bip_df[bip_df["batter_name"] == name]
        if len(bip_grp) < 10:
            continue

        # True BA/SLG from all plate appearances (includes Ks)
        outcomes = compute_outcomes(full_grp)

        # Grid overlay dots (BIP only)
        balls = []
        for _, row in bip_grp.iterrows():
            ev = bucket(row["launch_speed"], EV_MIN, EV_STEP)
            la = bucket(row["launch_angle"], LA_MIN, LA_STEP)
            balls.append({
                "ev":     ev,
                "la":     la,
                "event":  row["events"],
                "is_hit": 1 if row["events"] in HITS else 0,
                "is_hr":  1 if row["events"] == "home_run" else 0,
            })

        players[name] = {
            "name":    name,
            "ab":      outcomes["ab"],
            "ba":      outcomes["ba"],
            "obp":     outcomes["obp"],
            "slg":     outcomes["slg"],
            "ops":     outcomes["ops"],
            "hr_rate": outcomes["hr_rate"],
            "avg_ev":  round(float(bip_grp["launch_speed"].mean()), 1) if len(bip_grp) else None,
            "avg_la":  round(float(bip_grp["launch_angle"].mean()), 1) if len(bip_grp) else None,
            "ev_hist": [int(((bip_grp["launch_speed"] >= b) & (bip_grp["launch_speed"] < b + EV_STEP)).sum()) for b in range(EV_MIN, EV_MAX, EV_STEP)],
            "la_hist": [int(((bip_grp["launch_angle"] >= b) & (bip_grp["launch_angle"] < b + LA_STEP)).sum()) for b in range(LA_MIN, LA_MAX, LA_STEP)],
            "balls":   balls,
        }

    return dict(sorted(players.items()))


# ─── TEAM PROFILES ───────────────────────────────────────────────────────────

def build_team_profiles(df):
    """Build team profiles using full PA dataset for true BA/SLG."""
    # Add batting team to full dataset
    full = df[df["events"].notna()].copy()
    if "inning_topbot" in full.columns and "away_team" in full.columns:
        full["batting_team"] = full.apply(
            lambda r: r["home_team"] if r["inning_topbot"] == "Bot" else r["away_team"], axis=1
        )
    elif "home_team" in full.columns:
        full["batting_team"] = full["home_team"]
    else:
        return {}

    # BIP-only subset
    bip_df = full[
        (full["launch_speed"] >= EV_MIN) & (full["launch_speed"] <= EV_MAX) &
        (full["launch_angle"] >= LA_MIN) & (full["launch_angle"] <= LA_MAX) &
        full["launch_speed"].notna() &
        full["launch_angle"].notna()
    ].copy()

    teams = {}
    for team, full_grp in full.groupby("batting_team"):
        if pd.isna(team) or not team:
            continue
        # True BA/SLG from all PAs
        outcomes = compute_outcomes(full_grp)
        if outcomes["ab"] < 20:
            continue

        bip_t = bip_df[bip_df["batting_team"] == team]
        # Bucket-level data for overlay (BIP only)
        bucket_map = {}
        for _, row in bip_t.iterrows():
            ev = bucket(row["launch_speed"], EV_MIN, EV_STEP)
            la = bucket(row["launch_angle"], LA_MIN, LA_STEP)
            k = f"{ev}_{la}"
            if k not in bucket_map:
                bucket_map[k] = {"total": 0, "hits": 0, "hrs": 0}
            bucket_map[k]["total"] += 1
            bucket_map[k]["hits"]  += 1 if row["events"] in HITS else 0
            bucket_map[k]["hrs"]   += 1 if row["events"] == "home_run" else 0
        teams[str(team)] = {
            "name":    str(team),
            "ab":      outcomes["ab"],
            "ba":      outcomes["ba"],
            "obp":     outcomes["obp"],
            "slg":     outcomes["slg"],
            "ops":     outcomes["ops"],
            "hr_rate": outcomes["hr_rate"],
            "avg_ev":  round(float(bip_t["launch_speed"].mean()), 1) if len(bip_t) else None,
            "avg_la":  round(float(bip_t["launch_angle"].mean()), 1) if len(bip_t) else None,
            "ev_hist": [int(((bip_t["launch_speed"] >= b) & (bip_t["launch_speed"] < b + EV_STEP)).sum()) for b in range(EV_MIN, EV_MAX, EV_STEP)],
            "la_hist": [int(((bip_t["launch_angle"] >= b) & (bip_t["launch_angle"] < b + LA_STEP)).sum()) for b in range(LA_MIN, LA_MAX, LA_STEP)],
            "buckets": bucket_map,
        }
    return dict(sorted(teams.items()))


# ─── HTML ─────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EV x Launch Angle Contact Quality {{YEARS}}</title>
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@400;500;600&family=IBM+Plex+Sans:wght@300;400;500&family=IBM+Plex+Mono&display=swap" rel="stylesheet">
<style>
  :root {
    --navy:   #0D1B2A;
    --navy2:  #162232;
    --navy3:  #1E2F42;
    --red:    #D0021B;
    --gold:   #F5A623;
    --blue:   #2C7BE5;
    --muted:  #8AA0B5;
    --border: rgba(138,160,181,0.18);
    --text:   #E8EEF4;
    --mono:   'IBM Plex Mono', monospace;
  }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--navy); color:var(--text); font-family:'IBM Plex Sans',sans-serif; font-size:14px; line-height:1.5; }

  .hero { background:var(--navy2); border-bottom:3px solid var(--red); padding:2.5rem 2rem 2rem; position:relative; overflow:hidden; }
  .hero::before { content:''; position:absolute; inset:0; background:repeating-linear-gradient(-45deg,transparent,transparent 22px,rgba(208,2,27,0.04) 22px,rgba(208,2,27,0.04) 44px); pointer-events:none; }
  .hero-inner { position:relative; max-width:1300px; margin:0 auto; }
  .hero-eyebrow { font-family:'Oswald',sans-serif; font-size:11px; letter-spacing:3px; color:var(--red); text-transform:uppercase; margin-bottom:0.5rem; }
  .hero-title { font-family:'Oswald',sans-serif; font-size:clamp(1.8rem,4vw,3rem); font-weight:600; color:#fff; line-height:1.05; }
  .hero-title span { color:var(--red); }
  .hero-meta { margin-top:0.6rem; font-size:12px; color:var(--muted); font-family:var(--mono); }
  .stats-row { display:flex; gap:1rem; margin-top:1.75rem; flex-wrap:wrap; }
  .stat-pill { background:var(--navy3); border:1px solid var(--border); border-radius:6px; padding:0.65rem 1.1rem; min-width:120px; }
  .stat-pill-label { font-size:10px; letter-spacing:2px; text-transform:uppercase; color:var(--muted); margin-bottom:3px; }
  .stat-pill-val { font-family:'Oswald',sans-serif; font-size:1.5rem; font-weight:500; color:#fff; line-height:1; }
  .stat-pill-val.gold { color:var(--gold); }

  .content { max-width:1300px; margin:0 auto; padding:2rem 1.5rem 3rem; }

  .controls { display:flex; gap:1.5rem; align-items:center; flex-wrap:wrap; margin-bottom:1.5rem; }
  .control-group { display:flex; align-items:center; gap:8px; }
  .control-label { font-size:11px; letter-spacing:1.5px; text-transform:uppercase; color:var(--muted); font-family:var(--mono); white-space:nowrap; }
  .toggle-btn { font-family:var(--mono); font-size:10px; letter-spacing:1px; padding:5px 14px; border-radius:4px; cursor:pointer; border:1px solid var(--border); background:transparent; color:var(--muted); transition:all 0.15s; }
  .toggle-btn.active { border-color:var(--red); background:var(--red); color:#fff; }
  select { background:var(--navy3); color:var(--text); border:1px solid var(--border); border-radius:4px; padding:5px 10px; font-family:var(--mono); font-size:12px; cursor:pointer; }

  .main-layout { display:grid; grid-template-columns:1fr 290px; gap:2rem; align-items:start; }
  @media (max-width:960px) { .main-layout { grid-template-columns:1fr; } }

  .heatmap-wrap { overflow-x:auto; border:1px solid var(--border); border-radius:10px; background:var(--navy2); padding:1.5rem 1rem 1rem; }
  .heatmap-container { display:flex; gap:8px; min-width:800px; }
  .y-axis-wrap { display:flex; gap:4px; }
  .y-axis-title { font-family:'Oswald',sans-serif; font-size:11px; letter-spacing:2px; color:var(--muted); text-transform:uppercase; writing-mode:vertical-rl; transform:rotate(180deg); white-space:nowrap; margin-right:4px; }
  .y-axis { display:flex; flex-direction:column-reverse; justify-content:space-between; padding-bottom:36px; min-width:42px; }
  .y-axis-label { font-family:var(--mono); font-size:10px; color:var(--muted); text-align:right; height:22px; display:flex; align-items:center; justify-content:flex-end; }
  .grid-and-x { display:flex; flex-direction:column; flex:1; }
  .heatmap-grid { display:grid; gap:2px; }
  .cell { width:100%; height:22px; border-radius:2px; display:flex; align-items:center; justify-content:center; font-family:var(--mono); font-size:8px; font-weight:500; cursor:default; transition:transform 0.1s; }
  .cell:hover { transform:scale(1.5); z-index:10; position:relative; }
  .cell.empty { background:rgba(255,255,255,0.03); }
  .cell.has-player { outline:2px solid rgba(255,255,255,0.85); outline-offset:-2px; z-index:2; position:relative; }
  .x-axis { display:flex; padding-top:6px; }
  .x-axis-label { font-family:var(--mono); font-size:9px; color:var(--muted); text-align:center; width:100%; }
  .x-axis-title { font-family:'Oswald',sans-serif; font-size:11px; letter-spacing:2px; color:var(--muted); text-transform:uppercase; text-align:center; margin-top:6px; }

  .legend { display:flex; align-items:center; gap:10px; margin-top:1.25rem; flex-wrap:wrap; }
  .legend-label { font-size:11px; color:var(--muted); font-family:var(--mono); }
  .legend-bar { height:12px; width:220px; border-radius:3px; }

  .player-panel { background:var(--navy2); border:1px solid var(--border); border-radius:10px; padding:1.25rem; position:sticky; top:1rem; }
  .panel-title { font-family:'Oswald',sans-serif; font-size:1rem; font-weight:500; color:#fff; margin-bottom:1rem; letter-spacing:0.5px; }
  .player-select-wrap { margin-bottom:1rem; }
  .player-select-wrap select { width:100%; }
  .player-stats { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:1rem; }
  .player-stat { background:var(--navy3); border-radius:6px; padding:8px 10px; border:1px solid transparent; transition:border-color 0.15s; }
  .player-stat.active-stat { border-color:var(--gold); }
  .player-stat-label { font-size:9px; letter-spacing:1.5px; text-transform:uppercase; color:var(--muted); margin-bottom:2px; }
  .player-stat-val { font-family:'Oswald',sans-serif; font-size:1.2rem; font-weight:500; color:#fff; }
  .player-stat.active-stat .player-stat-val { color:var(--gold); }
  .dot-ex { width:10px; height:10px; border-radius:2px; flex-shrink:0; display:inline-block; }
  .clear-btn { width:100%; margin-top:0.75rem; font-family:var(--mono); font-size:10px; letter-spacing:1px; padding:7px; border-radius:4px; cursor:pointer; border:1px solid var(--border); background:transparent; color:var(--muted); transition:all 0.15s; }
  .clear-btn:hover { border-color:var(--red); color:var(--red); }

  .vs-league { margin-top:1rem; border-top:1px solid var(--border); padding-top:1rem; }
  .vs-label { font-size:10px; letter-spacing:1.5px; text-transform:uppercase; color:var(--muted); font-family:var(--mono); margin-bottom:8px; }
  .vs-row { display:flex; align-items:center; gap:8px; margin-bottom:5px; font-size:11px; font-family:var(--mono); }
  .vs-metric { color:var(--muted); width:55px; }
  .vs-bar-wrap { flex:1; height:6px; background:var(--navy3); border-radius:3px; overflow:hidden; }
  .vs-bar { height:100%; border-radius:3px; transition:width 0.4s; }
  .vs-val { color:var(--text); width:38px; text-align:right; }
  .vs-diff { font-size:10px; width:38px; text-align:right; }

  .tooltip { position:fixed; background:var(--navy3); border:1px solid var(--border); border-radius:6px; padding:10px 14px; font-family:var(--mono); font-size:11px; color:var(--text); pointer-events:none; opacity:0; transition:opacity 0.1s; z-index:1000; white-space:nowrap; }
  .tooltip.visible { opacity:1; }
  .tt-title { font-size:12px; font-weight:500; color:#fff; margin-bottom:6px; border-bottom:1px solid var(--border); padding-bottom:6px; }
  .tt-row { color:var(--muted); margin-top:3px; }
  .tt-row span { color:var(--text); }
  .tt-highlight { color:var(--gold) !important; }
  .tt-player { color:rgba(245,166,35,0.8); margin-top:6px; border-top:1px solid var(--border); padding-top:6px; }
  .tt-player span { color:#fff; }

  footer { border-top:1px solid var(--border); padding:1.5rem; text-align:center; font-size:11px; color:var(--muted); font-family:var(--mono); }
</style>
</head>
<body>

<div class="hero">
  <div class="hero-inner">
    <div class="hero-eyebrow">MLB Statcast {{YEARS}} — Contact Quality</div>
    <h1 class="hero-title">Exit Velocity <span>×</span> Launch Angle Heat Map</h1>
    <div class="hero-meta">League outcomes by contact bucket · Player overlay · Generated {{GENERATED}}</div>
    <div class="stats-row">
      <div class="stat-pill"><div class="stat-pill-label">Plate Appearances</div><div class="stat-pill-val" id="pill-bb">—</div></div>
      <div class="stat-pill"><div class="stat-pill-label">League BA</div><div class="stat-pill-val" id="pill-ba">—</div></div>
      <div class="stat-pill"><div class="stat-pill-label">League OBP</div><div class="stat-pill-val" id="pill-obp">—</div></div>
      <div class="stat-pill"><div class="stat-pill-label">League SLG</div><div class="stat-pill-val" id="pill-slg">—</div></div>
      <div class="stat-pill"><div class="stat-pill-label">League OPS</div><div class="stat-pill-val" id="pill-ops">—</div></div>
      <div class="stat-pill"><div class="stat-pill-label">League HR%</div><div class="stat-pill-val gold" id="pill-hr">—</div></div>
    </div>
  </div>
</div>

<div class="content">
  <div class="controls">
    <div class="control-group">
      <span class="control-label">Season</span>
      <div id="year-btns" style="display:flex;gap:6px;"></div>
    </div>
    <div class="control-group">
      <span class="control-label">Metric</span>
      <button class="toggle-btn active" id="btn-ba"      onclick="setMetric('ba')">BA</button>
      <button class="toggle-btn"        id="btn-slg"     onclick="setMetric('slg')">SLG</button>
      <button class="toggle-btn"        id="btn-hr_rate" onclick="setMetric('hr_rate')">HR%</button>
    </div>
    <div class="control-group">
      <span class="control-label">Min. BBs</span>
      <select id="min-ab" onchange="render()">
        <option value="0" selected>None</option>
        <option value="5">5</option>
        <option value="10">10</option>
        <option value="25">25</option>
        <option value="50">50</option>
      </select>
    </div>
  </div>

  <div class="main-layout">
    <div>
      <div class="heatmap-wrap">
        <div class="heatmap-container">
          <div class="y-axis-wrap">
            <div class="y-axis-title">Launch Angle (°)</div>
            <div class="y-axis" id="y-axis"></div>
          </div>
          <div class="grid-and-x">
            <div class="heatmap-grid" id="heatmap-grid"></div>
            <div class="x-axis" id="x-axis"></div>
            <div class="x-axis-title">Exit Velocity (mph)</div>
          </div>
        </div>
        <div class="legend">
          <span class="legend-label" id="legend-lo">0</span>
          <div class="legend-bar" id="legend-bar"></div>
          <span class="legend-label" id="legend-hi">1.000</span>
          <span class="legend-label" style="margin-left:1rem;color:rgba(255,255,255,0.15);">Grey = below min sample</span>
          <span class="legend-label" style="margin-left:1rem;color:rgba(255,255,255,0.15);">Grid shows contact rates (BIP). Player/team panel shows true BA/SLG.</span>
        </div>
      </div>
    </div>

    <div class="player-panel">
      <div class="panel-title">Overlay</div>
      <div style="display:flex;gap:6px;margin-bottom:0.75rem;">
        <button class="toggle-btn active" id="overlay-btn-player" onclick="setOverlayMode('player')" style="flex:1;text-align:center;">Player</button>
        <button class="toggle-btn"        id="overlay-btn-team"   onclick="setOverlayMode('team')"   style="flex:1;text-align:center;">Team</button>
      </div>
      <div class="player-select-wrap" id="player-select-wrap">
        <select id="player-select" onchange="setPlayer(this.value)">
          <option value="">— Select a player —</option>
        </select>
      </div>
      <div class="player-select-wrap" id="team-select-wrap" style="display:none;">
        <select id="team-select" onchange="setTeam(this.value)">
          <option value="">— Select a team —</option>
        </select>
      </div>
      <div class="player-stats" id="player-stats" style="display:none;">
        <div class="player-stat" id="pstat-ba">      <div class="player-stat-label">BA</div>      <div class="player-stat-val" id="ps-ba">—</div></div>
        <div class="player-stat" id="pstat-slg">     <div class="player-stat-label">SLG</div>     <div class="player-stat-val" id="ps-slg">—</div></div>
        <div class="player-stat" id="pstat-ops">     <div class="player-stat-label">OPS</div>     <div class="player-stat-val" id="ps-ops">—</div></div>
        <div class="player-stat" id="pstat-hr_rate"> <div class="player-stat-label">HR%</div>      <div class="player-stat-val" id="ps-hr_rate">—</div></div>
      </div>
      <div class="vs-league" id="vs-league" style="display:none;">
        <div class="vs-label">vs. League Avg</div>
        <div id="vs-rows"></div>
      </div>
      <button class="clear-btn" id="clear-btn" style="display:none;" onclick="clearPlayer()">Clear overlay</button>
    </div>
  </div>
</div>

<div class="tooltip" id="tooltip">
  <div class="tt-title" id="tt-title"></div>
  <div class="tt-row">BA (contact) <span id="tt-ba" class="tt-highlight"></span></div>
  <div class="tt-row">SLG (contact) <span id="tt-slg"></span></div>
  <div class="tt-row">HR% <span id="tt-hr"></span></div>
  <div class="tt-row">Batted Balls <span id="tt-ab"></span></div>
  <div class="tt-player" id="tt-player" style="display:none;">
    Player BBs in bucket: <span id="tt-pab"></span>
  </div>
</div>

<!-- HISTOGRAMS -->
<div style="max-width:1300px;margin:0 auto;padding:0 1.5rem 3rem;">
  <div style="border-top:1px solid var(--border);padding-top:2rem;">

    <!-- AVG BANNER -->
    <div style="display:flex;gap:1rem;margin-bottom:2rem;flex-wrap:wrap;">
      <div style="background:var(--navy2);border:1px solid var(--border);border-radius:6px;padding:0.65rem 1.25rem;min-width:160px;">
        <div style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:3px;font-family:var(--mono);">Avg Exit Velocity</div>
        <div style="font-family:'Oswald',sans-serif;font-size:1.5rem;font-weight:500;color:#fff;" id="avg-ev-val">—</div>
        <div style="font-size:10px;color:var(--muted);font-family:var(--mono);margin-top:2px;" id="avg-ev-ctx">League — All batted balls</div>
      </div>
      <div style="background:var(--navy2);border:1px solid var(--border);border-radius:6px;padding:0.65rem 1.25rem;min-width:160px;">
        <div style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:3px;font-family:var(--mono);">Avg Launch Angle</div>
        <div style="font-family:'Oswald',sans-serif;font-size:1.5rem;font-weight:500;color:#fff;" id="avg-la-val">—</div>
        <div style="font-size:10px;color:var(--muted);font-family:var(--mono);margin-top:2px;" id="avg-la-ctx">League — All batted balls</div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:2rem;">

      <!-- EV Histogram -->
      <div>
        <div style="display:flex;align-items:baseline;gap:1rem;margin-bottom:1.25rem;padding-bottom:0.6rem;border-bottom:1px solid var(--border);">
          <div style="font-family:'Oswald',sans-serif;font-size:1.2rem;font-weight:500;letter-spacing:1px;color:#fff;">Exit Velocity Distribution</div>
          <div style="background:var(--red);color:#fff;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;padding:2px 8px;border-radius:3px;font-family:var(--mono);">Balls in Play</div>
        </div>
        <canvas id="ev-hist" height="180"></canvas>
      </div>

      <!-- LA Histogram -->
      <div>
        <div style="display:flex;align-items:baseline;gap:1rem;margin-bottom:1.25rem;padding-bottom:0.6rem;border-bottom:1px solid var(--border);">
          <div style="font-family:'Oswald',sans-serif;font-size:1.2rem;font-weight:500;letter-spacing:1px;color:#fff;">Launch Angle Distribution</div>
          <div style="background:var(--red);color:#fff;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;padding:2px 8px;border-radius:3px;font-family:var(--mono);">Balls in Play</div>
        </div>
        <canvas id="la-hist" height="180"></canvas>
      </div>

    </div>
  </div>
</div>

<footer>Data via pybaseball / MLB Statcast {{YEARS}} &nbsp;·&nbsp; Generated {{GENERATED}}</footer>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
const DATA    = {{DATA_JSON}};
const EV_STEP = {{EV_STEP}};
const LA_STEP = {{LA_STEP}};
const EV_LABELS = DATA.ev_labels;
const LA_LABELS = DATA.la_labels;

let metric      = 'ba';
let curYear     = DATA.years.includes('all') ? 'all' : DATA.years[DATA.years.length - 1];
let curPlayer   = null;
let curTeam     = null;
let overlayMode = 'player';

// ── YEAR DATA ACCESSOR ──
function yd() { return DATA.year_data[curYear]; }

// ── YEAR BUTTONS ──
(function() {
  const wrap = document.getElementById('year-btns');
  const yearList = DATA.years.includes('all')
    ? [...DATA.years.filter(y => y !== 'all'), 'all']
    : DATA.years;
  yearList.forEach(y => {
    const btn = document.createElement('button');
    btn.className   = 'toggle-btn' + (y === curYear ? ' active' : '');
    btn.textContent = y === 'all' ? 'All' : y;
    btn.id          = 'yr-btn-' + y;
    btn.onclick     = () => setYear(y);
    wrap.appendChild(btn);
  });
})();

function setYear(y) {
  curYear = y;
  DATA.years.forEach(yr => {
    const el = document.getElementById('yr-btn-' + yr);
    if (el) el.classList.toggle('active', yr === y);
  });
  // Rebuild player and team dropdowns for selected year
  rebuildDropdowns();
  updatePills();
  render();
  updateHistograms();
}

// ── FORMAT ──
function fmtStat(val, m) {
  if (val === null || val === undefined) return '—';
  if (m === 'slg') return val.toFixed(3);
  if (m === 'hr_rate') return (val * 100).toFixed(1) + '%';
  const rounded = Math.round(val * 1000);
  if (rounded >= 1000) return '1.000';
  return '.' + String(rounded).padStart(3, '0');
}

function diffStr(player, league, m) {
  const d = player - league;
  const s = fmtStat(Math.abs(d), m);
  return (d >= 0 ? '+' : '-') + s;
}

// ── COLOR SCALES ──
const RANGES = { ba:[0,1], slg:[0,4], hr_rate:[0,1] };
const STOPS  = {
  ba:      ['#0a1628','#1a3a6e','#2563b0','#22c55e','#facc15','#ef4444'],
  slg:     ['#0a1628','#1a3a6e','#2563b0','#7c3aed','#facc15','#ef4444'],
  hr_rate: ['#0a1628','#162232','#1a3a6e','#2563b0','#facc15','#ef4444'],
};

function lerp(c1, c2, t) {
  const h = c => [parseInt(c.slice(1,3),16),parseInt(c.slice(3,5),16),parseInt(c.slice(5,7),16)];
  const [r1,g1,b1]=h(c1),[r2,g2,b2]=h(c2);
  return '#'+[Math.round(r1+(r2-r1)*t),Math.round(g1+(g2-g1)*t),Math.round(b1+(b2-b1)*t)].map(x=>x.toString(16).padStart(2,'0')).join('');
}

function cellColor(val, m) {
  const [lo,hi] = RANGES[m];
  const t = Math.max(0, Math.min(1, (val-lo)/(hi-lo)));
  const s = STOPS[m];
  const seg = (s.length-1)*t;
  const i   = Math.min(Math.floor(seg), s.length-2);
  return lerp(s[i], s[i+1], seg-i);
}

function textOn(bg) {
  const r=parseInt(bg.slice(1,3),16),g=parseInt(bg.slice(3,5),16),b=parseInt(bg.slice(5,7),16);
  return (r*.299+g*.587+b*.114)>100?'#0D1B2A':'rgba(255,255,255,0.75)';
}

// ── OVERLAY MAP ──
function overlayMap() {
  // Returns null (league mode) or a bucket map with {total,hits,hrs,ba,slg}
  let raw = null;
  if (overlayMode === 'player' && curPlayer) {
    const balls = yd().players[curPlayer]?.balls || [];
    raw = {};
    balls.forEach(b => {
      const k = b.ev+'_'+b.la;
      if (!raw[k]) raw[k]={total:0,hits:0,hrs:0};
      raw[k].total++; raw[k].hits+=b.is_hit; raw[k].hrs+=b.is_hr;
    });
  } else if (overlayMode === 'team' && curTeam) {
    raw = yd().teams[curTeam]?.buckets || null;
  }
  if (!raw) return null;
  // Compute per-bucket contact rates
  const map = {};
  for (const [k, v] of Object.entries(raw)) {
    map[k] = {
      ...v,
      ba:  v.total > 0 ? v.hits / v.total : 0,
      slg: v.total > 0 ? (v.hits + v.hrs*3) / v.total : 0, // approx: singles=1, HRs=4 avg
    };
  }
  return map;
}

// ── UPDATE PILLS ──
function updatePills() {
  const d = yd();
  document.getElementById('pill-bb').textContent   = d.total_pa.toLocaleString();
  document.getElementById('pill-ba').textContent   = fmtStat(d.league_ba,  'ba');
  document.getElementById('pill-obp').textContent  = fmtStat(d.league_obp, 'ba');
  document.getElementById('pill-slg').textContent  = fmtStat(d.league_slg, 'slg');
  document.getElementById('pill-ops').textContent  = fmtStat(d.league_ops, 'slg');
  document.getElementById('pill-hr').textContent   = fmtStat(d.league_hr,  'hr_rate');
}

// ── REBUILD DROPDOWNS ──
function rebuildDropdowns() {
  const d = yd();
  const pSel = document.getElementById('player-select');
  pSel.innerHTML = '<option value="">— Select a player —</option>';
  Object.keys(d.players || {}).forEach(name => {
    const o = document.createElement('option');
    o.value = name; o.textContent = name + ' (' + d.players[name].ab + ' BB)';
    pSel.appendChild(o);
  });
  const tSel = document.getElementById('team-select');
  tSel.innerHTML = '<option value="">— Select a team —</option>';
  Object.keys(d.teams || {}).sort().forEach(team => {
    const o = document.createElement('option');
    o.value = team; o.textContent = team + ' (' + d.teams[team].ab + ' AB)';
    tSel.appendChild(o);
  });
  curPlayer = null; curTeam = null;
  document.getElementById('player-stats').style.display = 'none';
  document.getElementById('vs-league').style.display    = 'none';
  document.getElementById('clear-btn').style.display    = 'none';
}

// ── RENDER ──
function render() {
  const minAB  = parseInt(document.getElementById('min-ab').value) || 0;
  const d      = yd();
  const cells  = d.cells;
  const evCols = EV_LABELS.length;
  const laCols = LA_LABELS.length;
  const grid   = document.getElementById('heatmap-grid');
  grid.innerHTML = '';
  grid.style.gridTemplateColumns = `repeat(${evCols},minmax(0,1fr))`;
  grid.style.gridTemplateRows    = `repeat(${laCols},22px)`;

  const oMap = overlayMap();

  document.getElementById('legend-bar').style.background = `linear-gradient(to right,${STOPS[metric].join(',')})`;
  document.getElementById('legend-lo').textContent = '0';
  document.getElementById('legend-hi').textContent = metric==='slg' ? '4.000' : metric==='hr_rate' ? '100%' : '1.000';

  for (let li = laCols-1; li >= 0; li--) {
    for (let ei = 0; ei < evCols; ei++) {
      const cell = cells[ei][li];
      const ev   = EV_LABELS[ei];
      const la   = LA_LABELS[li];
      const pKey = ev+'_'+la;
      const oB   = oMap ? oMap[pKey] : null;
      const div  = document.createElement('div');

      // In overlay mode, show overlay bucket data; in league mode show league cell
      const useOverlay = oMap !== null;
      const displayCell = useOverlay ? (oB ? {ba: oB.ba, slg: oB.slg, hr_rate: oB.hrs/oB.total, ab: oB.total} : null) : cell;
      const meetsMin = displayCell && displayCell.ab >= (useOverlay ? 1 : minAB);

      if (!meetsMin) {
        div.className = 'cell empty';
      } else {
        const val = displayCell[metric] || 0;
        const bg  = cellColor(val, metric);
        div.className        = 'cell';
        div.style.background = bg;
        div.style.color      = textOn(bg);
        div.textContent      = fmtStat(val, metric);
      }

      const ttTitle = ev+'–'+(ev+EV_STEP)+' mph  ·  '+la+'–'+(la+LA_STEP)+'°';
      div.addEventListener('mouseenter', () => {
        document.getElementById('tt-title').textContent = ttTitle;
        const hasData = meetsMin;
        const src = hasData ? displayCell : null;
        document.getElementById('tt-ba').textContent  = src ? fmtStat(src.ba,      'ba')      : '—';
        document.getElementById('tt-slg').textContent = src ? fmtStat(src.slg,     'slg')     : '—';
        document.getElementById('tt-hr').textContent  = src ? fmtStat(src.hr_rate||src.hrs/src.total, 'hr_rate') : '—';
        document.getElementById('tt-ab').textContent  = src ? src.ab + (useOverlay ? ' BIP' : ' BBs') : '< min';
        ['tt-ba','tt-slg','tt-hr'].forEach(id => document.getElementById(id).classList.remove('tt-highlight'));
        const hlMap = {ba:'tt-ba',slg:'tt-slg',hr_rate:'tt-hr'};
        if (hlMap[metric]) document.getElementById(hlMap[metric]).classList.add('tt-highlight');
        const pRow = document.getElementById('tt-player');
        if (oB && !useOverlay) {
          pRow.style.display = 'block';
          document.getElementById('tt-pab').textContent = oB.total+' ('+oB.hits+' H, '+oB.hrs+' HR)';
        } else { pRow.style.display = 'none'; }
        document.getElementById('tooltip').classList.add('visible');
      });
      div.addEventListener('mousemove', e => {
        const t = document.getElementById('tooltip');
        t.style.left = (e.clientX+14)+'px'; t.style.top = (e.clientY-70)+'px';
      });
      div.addEventListener('mouseleave', () => document.getElementById('tooltip').classList.remove('visible'));
      grid.appendChild(div);
    }
  }

  const yAxis = document.getElementById('y-axis');
  yAxis.innerHTML = '';
  [...LA_LABELS].forEach(la => {
    const d = document.createElement('div');
    d.className = 'y-axis-label'; d.textContent = la+'°';
    yAxis.appendChild(d);
  });

  const xAxis = document.getElementById('x-axis');
  xAxis.innerHTML = '';
  EV_LABELS.forEach((ev,i) => {
    const d = document.createElement('div');
    d.className = 'x-axis-label'; d.textContent = i%4===0 ? ev : '';
    xAxis.appendChild(d);
  });
}

// ── METRIC TOGGLE ──
function setMetric(m) {
  metric = m;
  ['ba','slg','hr_rate'].forEach(k => {
    document.getElementById('btn-'+k).classList.toggle('active', k===m);
    const el = document.getElementById('pstat-'+k);
    if (el) el.classList.toggle('active-stat', k===m);
  });
  render();
}

// ── OVERLAY MODE ──
function setOverlayMode(mode) {
  overlayMode = mode;
  document.getElementById('overlay-btn-player').classList.toggle('active', mode==='player');
  document.getElementById('overlay-btn-team').classList.toggle('active',   mode==='team');
  document.getElementById('player-select-wrap').style.display = mode==='player' ? 'block' : 'none';
  document.getElementById('team-select-wrap').style.display   = mode==='team'   ? 'block' : 'none';
  curPlayer = null; curTeam = null;
  document.getElementById('player-stats').style.display = 'none';
  document.getElementById('vs-league').style.display    = 'none';
  document.getElementById('clear-btn').style.display    = 'none';
  render();
}

// ── SHARED OVERLAY STATS ──
function showOverlayStats(obj, name) {
  const d = yd();
  const LEAGUE = { ba:d.league_ba, slg:d.league_slg, ops:d.league_ops, hr_rate:d.league_hr };
  document.getElementById('player-stats').style.display  = 'grid';
  document.getElementById('vs-league').style.display     = 'block';
  document.getElementById('clear-btn').style.display     = 'block';
  document.getElementById('ps-ba').textContent      = fmtStat(obj.ba,      'ba');
  document.getElementById('ps-slg').textContent     = fmtStat(obj.slg,     'slg');
  document.getElementById('ps-ops').textContent     = fmtStat(obj.ops,     'slg');
  document.getElementById('ps-hr_rate').textContent = fmtStat(obj.hr_rate, 'hr_rate');
  const vsDiv = document.getElementById('vs-rows');
  vsDiv.innerHTML = '';
  [{m:'ba',label:'BA',range:1},{m:'slg',label:'SLG',range:4},{m:'ops',label:'OPS',range:2},{m:'hr_rate',label:'HR%',range:1}].forEach(({m,label,range}) => {
    const pVal = obj[m] ?? 0, lgVal = LEAGUE[m] ?? 0;
    const pct  = Math.round((pVal / range) * 100);
    const diff = pVal - lgVal;
    const diffColor = diff >= 0 ? '#22c55e' : '#ef4444';
    const fmtM = (m === 'slg' || m === 'ops') ? 'slg' : m;
    vsDiv.innerHTML += `<div class="vs-row">
      <span class="vs-metric">${label}</span>
      <div class="vs-bar-wrap"><div class="vs-bar" style="width:${pct}%;background:${diff>=0?'#2C7BE5':'#ef4444'};"></div></div>
      <span class="vs-val">${fmtStat(pVal,fmtM)}</span>
      <span class="vs-diff" style="color:${diffColor}">${diffStr(pVal,lgVal,fmtM)}</span>
    </div>`;
  });
  ['ba','slg','ops','hr_rate'].forEach(k => {
    const el = document.getElementById('pstat-'+k);
    if (el) el.classList.toggle('active-stat', k===metric);
  });
}

// ── PLAYER OVERLAY ──
function setPlayer(name) {
  curPlayer = name || null;
  if (name && yd().players[name]) showOverlayStats(yd().players[name], name);
  else {
    document.getElementById('player-stats').style.display = 'none';
    document.getElementById('vs-league').style.display    = 'none';
    document.getElementById('clear-btn').style.display    = 'none';
  }
  render();
  updateHistograms();
}

// ── TEAM OVERLAY ──
function setTeam(name) {
  curTeam = name || null;
  if (name && yd().teams[name]) showOverlayStats(yd().teams[name], name);
  else {
    document.getElementById('player-stats').style.display = 'none';
    document.getElementById('vs-league').style.display    = 'none';
    document.getElementById('clear-btn').style.display    = 'none';
  }
  render();
  updateHistograms();
}

function clearPlayer() {
  document.getElementById('player-select').value = '';
  document.getElementById('team-select').value   = '';
  curPlayer = null; curTeam = null;
  document.getElementById('player-stats').style.display = 'none';
  document.getElementById('vs-league').style.display    = 'none';
  document.getElementById('clear-btn').style.display    = 'none';
  render();
  updateHistograms();
}

// ── INIT ──
rebuildDropdowns();
updatePills();
render();
// updateHistograms called after charts are created below

/* ── HISTOGRAMS ── */
let evChart = null, laChart = null;

function updateHistograms() {
  const d = yd();
  let evData, laData, avgEV, avgLA, ctx;
  if (overlayMode === 'player' && curPlayer && d.players[curPlayer]) {
    const p = d.players[curPlayer];
    evData = p.ev_hist; laData = p.la_hist;
    avgEV  = p.avg_ev;  avgLA  = p.avg_la;
    ctx    = curPlayer.split(' ').pop();
  } else if (overlayMode === 'team' && curTeam && d.teams[curTeam]) {
    const t = d.teams[curTeam];
    evData = t.ev_hist; laData = t.la_hist;
    avgEV  = t.avg_ev;  avgLA  = t.avg_la;
    ctx    = curTeam;
  } else {
    evData = d.ev_hist; laData = d.la_hist;
    avgEV  = d.avg_ev;  avgLA  = d.avg_la;
    ctx    = 'League';
  }
  if (!evData || !laData) return;

  // Store current stats on charts for tooltip access
  if (evChart) {
    evChart.data.datasets[0].data = evData;
    evChart._evStats = d.ev_stats;
    evChart.update();
  }
  if (laChart) {
    laChart.data.datasets[0].data = laData;
    laChart._laStats = d.la_stats;
    laChart.update();
  }

  document.getElementById('avg-ev-val').textContent = avgEV != null ? avgEV + ' mph' : '—';
  document.getElementById('avg-la-val').textContent = avgLA != null ? avgLA + '°'    : '—';
  document.getElementById('avg-ev-ctx').textContent = ctx + ' — All batted balls';
  document.getElementById('avg-la-ctx').textContent = ctx + ' — All batted balls';
}

(function() {
  const chartDefaults = {
    responsive: true,
    maintainAspectRatio: true,
    animation: { duration: 400 },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: '#1E2F42',
        borderColor: 'rgba(138,160,181,0.18)',
        borderWidth: 1,
        titleColor: '#E8EEF4',
        bodyColor: '#8AA0B5',
        titleFont: { family: 'IBM Plex Mono', size: 11 },
        bodyFont: { family: 'IBM Plex Mono', size: 11 },
        callbacks: {
          title: items => items[0].label + ' – ' + (parseInt(items[0].label) + EV_STEP) + ' mph',
          label: item => item.raw.toLocaleString() + ' batted balls',
        }
      }
    },
    scales: {
      x: {
        ticks: { color: '#8AA0B5', font: { family: 'IBM Plex Mono', size: 9 }, maxRotation: 0 },
        grid:  { color: 'rgba(138,160,181,0.08)' },
        border:{ color: 'rgba(138,160,181,0.18)' },
      },
      y: {
        ticks: { color: '#8AA0B5', font: { family: 'IBM Plex Mono', size: 9 },
                 callback: v => v >= 1000 ? (v/1000).toFixed(0)+'k' : v },
        grid:  { color: 'rgba(138,160,181,0.08)' },
        border:{ color: 'rgba(138,160,181,0.18)' },
      }
    }
  };

  // EV histogram
  const d0 = yd();
  evChart = new Chart(document.getElementById('ev-hist'), {
    type: 'bar',
    data: {
      labels: DATA.ev_labels.map(v => v),
      datasets: [{
        data: d0.ev_hist || [],
        backgroundColor: DATA.ev_labels.map(v => {
          const t = (v - 50) / 70;
          return `rgba(${Math.round(44+t*192)},${Math.round(123-t*60)},${Math.round(229-t*229)},0.8)`;
        }),
        borderColor: 'transparent',
        borderRadius: 2,
        borderSkipped: false,
      }]
    },
    options: {
      ...chartDefaults,
      plugins: {
        ...chartDefaults.plugins,
        tooltip: {
          ...chartDefaults.plugins.tooltip,
          callbacks: {
            title: items => items[0].label + '–' + (parseInt(items[0].label) + EV_STEP) + ' mph',
            label: item => item.raw.toLocaleString() + ' batted balls',
            afterLabel: item => {
              const stats = item.chart._evStats && item.chart._evStats[item.dataIndex];
              if (!stats) return '';
              return ['BA (contact): ' + fmtStat(stats.ba, 'ba'), 'SLG (contact): ' + fmtStat(stats.slg, 'slg')];
            }
          }
        }
      }
    }
  });
  evChart._evStats = d0.ev_stats;

  // LA histogram
  laChart = new Chart(document.getElementById('la-hist'), {
    type: 'bar',
    data: {
      labels: DATA.la_labels.map(v => v + '°'),
      datasets: [{
        data: d0.la_hist,
        backgroundColor: DATA.la_labels.map(v => {
          // Color by outcome zone: ground ball (neg) = red, line drive (10-25) = gold, fly ball = blue
          if (v < 0)  return 'rgba(208,2,27,0.7)';
          if (v < 10) return 'rgba(138,160,181,0.5)';
          if (v < 25) return 'rgba(245,166,35,0.8)';
          if (v < 50) return 'rgba(44,123,229,0.8)';
          return 'rgba(138,160,181,0.4)';
        }),
        borderColor: 'transparent',
        borderRadius: 2,
        borderSkipped: false,
      }]
    },
    options: {
      ...chartDefaults,
      plugins: {
        ...chartDefaults.plugins,
        tooltip: {
          ...chartDefaults.plugins.tooltip,
          callbacks: {
            title: items => items[0].label.replace('°','') + '–' + (parseInt(items[0].label) + LA_STEP) + '°',
            label: item => item.raw.toLocaleString() + ' batted balls',
            afterLabel: item => {
              const stats = item.chart._laStats && item.chart._laStats[item.dataIndex];
              if (!stats) return '';
              return ['BA (contact): ' + fmtStat(stats.ba, 'ba'), 'SLG (contact): ' + fmtStat(stats.slg, 'slg')];
            }
          }
        }
      }
    }
  });
  laChart._laStats = d0.la_stats;

  // Color legend for LA histogram
  const laLegend = [
    { color:'rgba(208,2,27,0.7)',    label:'Ground ball (< 0°)' },
    { color:'rgba(138,160,181,0.5)', label:'Near-ground (0–10°)' },
    { color:'rgba(245,166,35,0.8)',  label:'Line drive (10–25°)' },
    { color:'rgba(44,123,229,0.8)',  label:'Fly ball (25–50°)' },
    { color:'rgba(138,160,181,0.4)', label:'Pop-up (50°+)' },
  ];
  const legendEl = document.createElement('div');
  legendEl.style.cssText = 'display:flex;flex-wrap:wrap;gap:10px;margin-top:10px;';
  laLegend.forEach(({color, label}) => {
    legendEl.innerHTML += `<div style="display:flex;align-items:center;gap:5px;font-family:IBM Plex Mono,monospace;font-size:10px;color:#8AA0B5;">
      <div style="width:10px;height:10px;border-radius:2px;background:${color};flex-shrink:0;"></div>${label}</div>`;
  });
  document.getElementById('la-hist').parentNode.appendChild(legendEl);
  updateHistograms();
})();
</script>
</body>
</html>
"""


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    args  = parse_args()
    years = sorted(set(args.years))
    print(f"Years: {years}")

    # Fetch each year separately
    frames = {}
    for y in years:
        df_y = fetch_season(y)
        df_y = add_batter_name(df_y)
        frames[y] = df_y

    # Build per-year datasets
    year_data = {}
    for y, df_y in frames.items():
        print(f"\nBuilding grid for {y}...")
        gd = build_grid(df_y)
        print(f"  Building player profiles for {y}...")
        pl = build_player_profiles(df_y)
        print(f"    {len(pl)} players")
        print(f"  Building team profiles for {y}...")
        tm = build_team_profiles(df_y)
        print(f"    {len(tm)} teams")
        year_data[str(y)] = {**gd, "players": pl, "teams": tm}

    # Build combined "all" dataset
    if len(years) > 1:
        print("\nBuilding combined dataset...")
        df_all = pd.concat(list(frames.values()), ignore_index=True)
        gd_all = build_grid(df_all)
        pl_all = build_player_profiles(df_all)
        tm_all = build_team_profiles(df_all)
        year_data["all"] = {**gd_all, "players": pl_all, "teams": tm_all}

    data_payload = {
        "years":      [str(y) for y in years],
        "year_data":  year_data,
        "ev_labels":  list(range(EV_MIN, EV_MAX, EV_STEP)),
        "la_labels":  list(range(LA_MIN, LA_MAX, LA_STEP)),
    }

    year_label = " · ".join(str(y) for y in years)
    html = (HTML
        .replace("{{YEARS}}",     year_label)
        .replace("{{GENERATED}}", datetime.now().strftime("%b %d, %Y %H:%M"))
        .replace("{{EV_STEP}}",   str(EV_STEP))
        .replace("{{LA_STEP}}",   str(LA_STEP))
        .replace("{{DATA_JSON}}", json.dumps(data_payload))
    )

    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    print(f"\nHeat map written -> {out.resolve()}")


if __name__ == "__main__":
    main()
