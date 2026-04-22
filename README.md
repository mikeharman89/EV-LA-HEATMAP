# EV × Launch Angle — Contact Quality Heat Map

An interactive MLB Statcast heat map showing batting average, SLG, and HR rate by exit velocity and launch angle. Includes player and team overlays, year filtering, and distribution histograms.

**Live report →** `[https://mikeharman89.github.io/EV-LA-HEATMAP/](https://mikeharman89.github.io/EV-LA-HEATMAP/)`

---

## What it shows

The heat map plots every EV/LA combination from the selected season(s) and colors each cell by the chosen metric — giving an instant visual of where hard-hit, high-BA contact lives vs. where weak contact and outs dominate.

**Metrics**
- **BA** — true batting average (H / AB, including strikeouts)
- **SLG** — slugging percentage on the same denominator
- **HR%** — home run rate per at-bat

**League banner** — BA, OBP, SLG, OPS, and HR% for the selected season pulled from all plate appearances

**Player overlay** — select any player to filter the heat map to their batted ball profile, with BA / SLG / OPS / HR% vs. league average comparison bars

**Team overlay** — same as player overlay but for any MLB team

**Year filter** — toggle between 2025, 2026, or combined

**Histograms** — exit velocity and launch angle distribution charts, color-coded by contact zone (ground ball / line drive / fly ball / pop-up), with hover tooltips showing BA and SLG at each bucket. Updates when a player or team is selected.

---

## Repo structure

```
├── ev_la_heatmap.py              # Main script
├── requirements.txt              # Python dependencies
├── ev_la_heatmap.html            # Latest generated report (auto-updated daily)
└── .github/
    └── workflows/
        └── update_ev_la_heatmap.yml   # Daily schedule
```

---

## Running locally

```bash
pip3 install -r requirements.txt

# Full 2025 + 2026 season to date (default)
python3 ev_la_heatmap.py --years 2025 2026

# Single season
python3 ev_la_heatmap.py --years 2026

# Custom output path
python3 ev_la_heatmap.py --years 2025 2026 --out my_report.html
```

The script fetches Statcast data via [pybaseball](https://github.com/jldbc/pybaseball). pybaseball caches data locally so repeat runs are much faster. First run with two seasons of data takes 10–15 minutes.

Open the output file directly in your browser — no server needed, it's fully self-contained HTML.

---

## Schedule

Runs daily at **2:00 PM MDT** (UTC-6) via GitHub Actions. The cron is set to `0 20 * * *` — update to `0 21 * * *` in winter when Mountain Time shifts to MST (UTC-7).

Trigger a manual run anytime from the **Actions** tab in the repo.

---

## Data notes

- **Grid cells** — contact rates (hits / balls in play at that EV/LA bucket). Strikeouts can't be assigned an EV/LA coordinate so the grid is inherently a balls-in-play view. Labeled as "BA (contact)" in tooltips.
- **Player / team panel** — true BA and SLG using all at-bats including strikeouts, same denominator as MLB official stats.
- **League pills** — calculated from all plate appearances in the selected season(s).
- Regular season only (`game_type == R`). Spring training and playoffs excluded.

Data via [pybaseball](https://github.com/jldbc/pybaseball) / MLB Statcast.
