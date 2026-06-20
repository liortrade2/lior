"""TOAI Analytics — a local, ML-aware trading dashboard (the "TradesViz at home").

Why this exists: external journals (Edgewonk, TradesViz) are great human tools but
they don't know the ML score or what the gate decided. This one does — it reads the
same files the rest of TOAI writes and slices realized performance BY the model's
conviction, plots each trade on its own candles with the score annotated, and shows
the ALLOW-vs-trade-everything edge on real fills. Nothing leaves the machine.

Data it reads (per instrument, all already on disk):
  <inst>/executions.csv  — realized fills (prices, MAE/MFE, SL/TP, commission)
  <inst>/journal.csv     — each fill scored vs the gate (Score/Verdict/Variant)
  <inst>/bar_data.csv    — bars; OHLC columns enable real candlesticks (else EMA line)
  + scorecard.score_trades(...) for the walk-forward (backtest) view

Run:  streamlit run toai/dashboard.py            (or the panel's 📈 Analytics button)
The compute helpers below are import-safe without streamlit/plotly, so they can be
unit-tested headless; only main() pulls in the UI libraries.
"""
from __future__ import annotations

import pandas as pd

# Work both as a package module (`python -m toai.dashboard`) and as a bare script
# (`streamlit run toai/dashboard.py`), where there is no parent package.
try:
    from . import ai_coach, config, journal, scorecard
except ImportError:
    import pathlib
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from toai import ai_coach, config, journal, scorecard

OHLC = ["Open", "High", "Low", "Close"]


# --------------------------------------------------------------------------- #
#  Data loading / shaping (no streamlit — testable headless)
# --------------------------------------------------------------------------- #
def _inst_dir(instrument):
    return config.DATA_ROOT / instrument if instrument else config.DATA_ROOT


def load_realized(instrument) -> pd.DataFrame:
    """One tidy row per realized trade: executions (prices, MAE/MFE, SL/TP) joined
    to the journal (Score/Verdict/Variant/Threshold) on the entry timestamp.
    Empty frame if there are no fills yet."""
    d = _inst_dir(instrument)
    try:
        ex = pd.read_csv(d / "executions.csv")
    except (OSError, ValueError, pd.errors.EmptyDataError):
        return pd.DataFrame()
    if ex.empty or "Entry time" not in ex.columns:
        return pd.DataFrame()

    ex = ex.rename(columns={
        "Entry time": "EntryTime", "Exit time": "ExitTime",
        "Market pos.": "Direction", "Entry price": "EntryPrice",
        "Exit price": "ExitPrice", "Highest price": "HighestPrice",
        "Lowest price": "LowestPrice", "Stop Loss": "StopLoss",
        "Take Profit": "TakeProfit"})
    ex["EntryTime"] = pd.to_datetime(ex["EntryTime"], errors="coerce")
    ex["ExitTime"] = pd.to_datetime(ex.get("ExitTime"), errors="coerce")
    ex = ex.dropna(subset=["EntryTime"]).sort_values("EntryTime")

    # Attach the gate's verdict from the journal (nearest entry within 5 min).
    try:
        j = pd.read_csv(d / "journal.csv")
        j["DateTime"] = pd.to_datetime(j["DateTime"], errors="coerce")
        j = (j.dropna(subset=["DateTime"]).sort_values("DateTime")
             [["DateTime", "Score", "Verdict", "Variant", "Threshold"]])
        ex = pd.merge_asof(ex, j, left_on="EntryTime", right_on="DateTime",
                           direction="nearest", tolerance=pd.Timedelta(minutes=5))
    except (OSError, ValueError, KeyError, pd.errors.EmptyDataError):
        for c in ("Score", "Verdict", "Variant", "Threshold"):
            ex[c] = pd.NA

    ex["Hour"] = ex["EntryTime"].dt.hour
    ex["Day"] = ex["EntryTime"].dt.date
    if "Profit" in ex.columns:
        ex["CumProfit"] = pd.to_numeric(ex["Profit"], errors="coerce").fillna(0).cumsum()
    ex["RMultiple"] = _r_multiple(ex)
    return ex.reset_index(drop=True)


def _r_multiple(ex: pd.DataFrame) -> pd.Series:
    """Profit in units of the initial risk (entry→stop), when a stop is present."""
    out = []
    for _, r in ex.iterrows():
        try:
            entry, stop = float(r["EntryPrice"]), float(r["StopLoss"])
            risk = abs(entry - stop)
            pnl_pts = float(r["ExitPrice"]) - entry
            if str(r.get("Direction", "")).lower().startswith(("short", "sell")):
                pnl_pts = -pnl_pts
            out.append(round(pnl_pts / risk, 2) if risk > 0 else None)
        except (TypeError, ValueError, KeyError):
            out.append(None)
    return pd.Series(out, index=ex.index, dtype="float64")


def load_bars(instrument) -> tuple[pd.DataFrame, bool]:
    """bar_data with DateTime parsed; second value = whether OHLC is present."""
    d = _inst_dir(instrument)
    try:
        bars = pd.read_csv(d / "bar_data.csv")
    except (OSError, ValueError, pd.errors.EmptyDataError):
        return pd.DataFrame(), False
    if "DateTime" not in bars.columns:
        return pd.DataFrame(), False
    bars["DateTime"] = pd.to_datetime(bars["DateTime"], errors="coerce")
    bars = bars.dropna(subset=["DateTime"]).sort_values("DateTime")
    return bars, all(c in bars.columns for c in OHLC)


def trade_bars(bars: pd.DataFrame, entry, exit, pad_bars: int = 25) -> pd.DataFrame:
    """The slice of bars around a trade, padded on both sides for context."""
    if bars.empty:
        return bars
    exit = exit if pd.notna(exit) else entry
    lo, hi = min(entry, exit), max(entry, exit)
    inside = bars[(bars["DateTime"] >= lo) & (bars["DateTime"] <= hi)]
    if inside.empty:
        # nearest bar if the window is between bars
        idx = (bars["DateTime"] - entry).abs().idxmin()
        i = bars.index.get_loc(idx)
    else:
        i0, i1 = bars.index.get_loc(inside.index[0]), bars.index.get_loc(inside.index[-1])
        return bars.iloc[max(0, i0 - pad_bars): i1 + pad_bars + 1]
    return bars.iloc[max(0, i - pad_bars): i + pad_bars + 1]


def scored_for(instrument, source: str) -> tuple[pd.DataFrame | None, float, bool, str, str]:
    """(scored[Score,PnL,(DateTime)], threshold, out_of_sample, date_from, date_to)
    for either the realized fills or the walk-forward backtest."""
    d = _inst_dir(instrument)
    thr = config.get_threshold(d)
    if source == "Realized fills":
        return journal.live_scored(d, source="live"), thr, False, "", ""
    st = scorecard.score_trades(scorecard.active_training_file(instrument))
    if st is None:
        return None, thr, True, "", ""
    return st.scored, thr, st.out_of_sample, st.date_from, st.date_to


def kpis(ex: pd.DataFrame) -> dict:
    """Headline numbers from the realized frame."""
    if ex.empty or "Profit" not in ex.columns:
        return {}
    p = pd.to_numeric(ex["Profit"], errors="coerce").dropna()
    wins, losses = p[p > 0], p[p < 0]
    gross_w, gross_l = wins.sum(), -losses.sum()
    return {
        "trades": int(len(p)),
        "net": float(p.sum()),
        "win_rate": float((p > 0).mean() * 100) if len(p) else 0.0,
        "expectancy": float(p.mean()) if len(p) else 0.0,
        "profit_factor": float(gross_w / gross_l) if gross_l > 0 else None,
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
    }


def instruments() -> list[str]:
    return config.list_instruments() or (["MES"] if (config.DATA_ROOT / "MES").exists() else [])


# --------------------------------------------------------------------------- #
#  Phase A: units, chart transforms, exit analysis, seasonality, calendar
# --------------------------------------------------------------------------- #
# $ per 1.0 price-point and tick size per instrument (CME micros + minis).
CONTRACTS = {
    "MES": (5.0, 0.25), "ES": (50.0, 0.25), "MNQ": (2.0, 0.25), "NQ": (20.0, 0.25),
    "MYM": (0.5, 1.0), "YM": (5.0, 1.0), "M2K": (5.0, 0.1), "RTY": (50.0, 0.1),
    "MCL": (100.0, 0.01), "CL": (1000.0, 0.01), "MGC": (10.0, 0.1), "GC": (100.0, 0.1),
    "MBT": (0.1, 1.0),
}


def contract(instrument) -> tuple[float, float]:
    """(dollars per point, tick size) — defaults to MES-like if unknown."""
    return CONTRACTS.get(str(instrument).upper(), (5.0, 0.25))


def to_units(dollars, instrument, unit: str):
    """Convert a $ amount to the chosen display unit ($, points, ticks)."""
    if unit == "$":
        return dollars
    pv, tick = contract(instrument)
    pts = dollars / pv if pv else dollars
    return pts if unit == "points" else pts / tick if tick else pts


def unit_symbol(unit: str) -> str:
    return {"$": "$", "points": " pts", "ticks": " ticks"}.get(unit, "")


def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Heikin-Ashi OHLC from real OHLC — smooths noise to show trend/reversal."""
    o, h, l, c = df["Open"].to_numpy(), df["High"].to_numpy(), df["Low"].to_numpy(), df["Close"].to_numpy()
    ha_c = (o + h + l + c) / 4
    ha_o = ha_c.copy()
    ha_o[0] = (o[0] + c[0]) / 2
    for i in range(1, len(ha_o)):
        ha_o[i] = (ha_o[i - 1] + ha_c[i - 1]) / 2
    out = pd.DataFrame({"DateTime": df["DateTime"].to_numpy(), "Open": ha_o, "Close": ha_c})
    out["High"] = [max(hh, oo, cc) for hh, oo, cc in zip(h, ha_o, ha_c)]
    out["Low"] = [min(ll, oo, cc) for ll, oo, cc in zip(l, ha_o, ha_c)]
    return out


def renko_bricks(df: pd.DataFrame, brick: float) -> pd.DataFrame:
    """Close-based Renko bricks (size `brick`). Returns Open/Close/Up per brick,
    plotted against the time the brick formed — strips time, shows pure movement."""
    if brick <= 0 or df.empty:
        return pd.DataFrame()
    closes, times = df["Close"].to_numpy(), df["DateTime"].to_numpy()
    base = closes[0]
    rows = []
    for c, t in zip(closes, times):
        while c - base >= brick:
            rows.append((t, base, base + brick, True)); base += brick
        while base - c >= brick:
            rows.append((t, base, base - brick, False)); base -= brick
    return pd.DataFrame(rows, columns=["DateTime", "Open", "Close", "Up"])


def exit_efficiency(ex: pd.DataFrame, instrument) -> pd.DataFrame:
    """How much of the available move each trade captured: realized points vs the
    MFE (best the trade ever showed). 100% = nailed the high; low = gave it back.
    Uses MFE/MAE already in executions, so it needs no bar history."""
    pv, _ = contract(instrument)
    rows = []
    for _, r in ex.iterrows():
        try:
            realized_pts = float(r["Profit"]) / pv
            mfe_pts = float(r["MFE"])
        except (TypeError, ValueError, KeyError):
            continue
        eff = (realized_pts / mfe_pts * 100) if mfe_pts > 0 else None
        rows.append({"EntryTime": r["EntryTime"], "RealizedPts": realized_pts,
                     "MFE": mfe_pts, "MAE": _safe_float(r.get("MAE")),
                     "Efficiency": eff, "Score": r.get("Score")})
    return pd.DataFrame(rows)


def _safe_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def seasonality(ex: pd.DataFrame):
    """P&L grouped by day-of-week, hour and month — the calendar patterns."""
    e = ex.copy()
    e["Profit"] = pd.to_numeric(e["Profit"], errors="coerce")
    e = e.dropna(subset=["Profit"])
    if e.empty:
        return {}
    dow = e.groupby(e["EntryTime"].dt.dayofweek)["Profit"].agg(["sum", "count"])
    dow.index = [["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][i] for i in dow.index]
    month = e.groupby(e["EntryTime"].dt.to_period("M").astype(str))["Profit"].agg(["sum", "count"])
    return {"dow": dow.reset_index(names="k"), "month": month.reset_index(names="k")}


def daily_pnl(ex: pd.DataFrame) -> pd.DataFrame:
    """Net P&L per calendar day (for the calendar heatmap and goals)."""
    e = ex.copy()
    e["Profit"] = pd.to_numeric(e["Profit"], errors="coerce")
    g = e.dropna(subset=["Profit"]).groupby("Day")["Profit"].agg(["sum", "count"])
    return g.reset_index()


def evaluation(ex: pd.DataFrame) -> dict:
    """The Edgewonk-style 'Evaluation' stat block for the Home glance."""
    e = ex.copy()
    e["Profit"] = pd.to_numeric(e["Profit"], errors="coerce")
    e = e.dropna(subset=["Profit"])
    if e.empty:
        return {}
    e["EntryTime"] = pd.to_datetime(e["EntryTime"], errors="coerce")
    e["ExitTime"] = pd.to_datetime(e.get("ExitTime"), errors="coerce")
    hold = (e["ExitTime"] - e["EntryTime"]).dt.total_seconds() / 60
    daily = e.groupby(e["EntryTime"].dt.date)["Profit"].sum()
    fees = (pd.to_numeric(e["Commission"], errors="coerce").fillna(0).sum()
            if "Commission" in e.columns else 0.0)
    # Current win/loss streak (most recent trades).
    signs = (e.sort_values("EntryTime")["Profit"] > 0).tolist()
    streak, win = 0, None
    for s in reversed(signs):
        if win is None:
            win, streak = s, 1
        elif s == win:
            streak += 1
        else:
            break
    return {
        "trades": int(len(e)),
        "avg_per_day": float(daily.mean()),
        "biggest_win": float(e["Profit"].max()),
        "biggest_loss": float(e["Profit"].min()),
        "total_fees": float(fees),
        "avg_hold": float(hold.mean()) if hold.notna().any() else float("nan"),
        "win_rate": float((e["Profit"] > 0).mean() * 100),
        "win_days": int((daily > 0).sum()),
        "loss_days": int((daily < 0).sum()),
        "trades_per_day": len(e) / max(1, daily.shape[0]),
        "streak": streak, "streak_win": win,
    }


# --------------------------------------------------------------------------- #
#  Phase B: what-if simulators
# --------------------------------------------------------------------------- #
def simulate_sltp(ex: pd.DataFrame, instrument, stop_pts: float, target_pts: float,
                  tie: str = "stop") -> pd.DataFrame:
    """Re-simulate each realized trade under a hypothetical fixed stop / target,
    using the MAE/MFE already recorded (no bar history needed). A stop of S points
    "would have hit" when the trade's adverse excursion (MAE) reached S; a target
    of T when the favorable excursion (MFE) reached T. When BOTH would hit the
    order is unknown from MAE/MFE alone — `tie` decides ('stop' = pessimistic).
    Trades that hit neither keep their actual P&L."""
    pv, _ = contract(instrument)
    rows = []
    for _, r in ex.iterrows():
        try:
            mae, mfe, actual = float(r["MAE"]), float(r["MFE"]), float(r["Profit"])
        except (TypeError, ValueError, KeyError):
            continue
        comm = _safe_float(r.get("Commission")) or 0.0
        stop_hit = stop_pts > 0 and mae >= stop_pts
        tgt_hit = target_pts > 0 and mfe >= target_pts
        outcome = (tie if (stop_hit and tgt_hit)
                   else "stop" if stop_hit else "target" if tgt_hit else "actual")
        pnl = (-stop_pts * pv - comm if outcome == "stop"
               else target_pts * pv - comm if outcome == "target" else actual)
        rows.append({"EntryTime": r["EntryTime"], "Sim": pnl, "Actual": actual,
                     "Outcome": outcome, "Score": r.get("Score")})
    return pd.DataFrame(rows)


def _net_stats(pnl: pd.Series) -> dict:
    p = pd.to_numeric(pnl, errors="coerce").dropna()
    if p.empty:
        return {"net": 0.0, "win": 0.0, "pf": None, "n": 0}
    gl = -p[p < 0].sum()
    return {"net": float(p.sum()), "win": float((p > 0).mean() * 100),
            "pf": float(p[p > 0].sum() / gl) if gl > 0 else None, "n": int(len(p))}


# --------------------------------------------------------------------------- #
#  Look & feel — a cohesive dark theme so the dashboard reads like a product,
#  not a default Streamlit app. CSS skins the cards/tabs/typography; a Plotly
#  template makes every chart transparent + consistently styled in one place.
# --------------------------------------------------------------------------- #
THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stMarkdown, button, input, select, textarea, .stSlider {
  font-family: 'Manrope', -apple-system, system-ui, sans-serif !important;
}
.stApp { background: #f6f8fa; }
.block-container { padding-top: 1.3rem; padding-bottom: 1.2rem; max-width: 1500px; }
h1 { font-weight: 800 !important; letter-spacing: -0.6px; color: #111827; font-size: 1.7rem; }
h2, h3 { font-weight: 700 !important; letter-spacing: -0.3px; color: #1f2937; }
/* KPI metric cards — white with a soft shadow (Edgewonk look) */
[data-testid="stMetric"] {
  background: #ffffff; border: 1px solid #eceef1;
  border-radius: 14px; padding: 14px 16px 12px 16px;
  box-shadow: 0 1px 3px rgba(16,24,40,0.06), 0 1px 2px rgba(16,24,40,0.04);
}
[data-testid="stMetricValue"] { font-weight: 700; color: #111827; }
[data-testid="stMetricLabel"] { color: #6b7280; font-size: 0.8rem; font-weight: 600; }
/* Tabs — green underline on the active one */
[data-baseweb="tab-list"] { gap: 2px; border-bottom: 1px solid #e5e7eb; }
[data-baseweb="tab"] { font-weight: 600; padding: 8px 14px; color: #6b7280; }
[data-baseweb="tab"][aria-selected="true"] { color: #16a34a !important; }
[data-baseweb="tab-highlight"] { background-color: #16a34a !important; height: 3px; }
/* Chart + table panels as white cards */
[data-testid="stPlotlyChart"], [data-testid="stDataFrame"] {
  background: #ffffff; border: 1px solid #eceef1; border-radius: 14px;
  padding: 8px; box-shadow: 0 1px 3px rgba(16,24,40,0.05);
}
section[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e9ebef; }
hr { margin: 0.5rem 0; border-color: #e5e7eb; }
/* Evaluation panel — Edgewonk-style stat rows */
.evpanel { background: #ffffff; border: 1px solid #eceef1; border-radius: 14px;
  padding: 4px 16px; box-shadow: 0 1px 3px rgba(16,24,40,0.05); }
.evrow { display: flex; justify-content: space-between; align-items: center;
  padding: 8px 0; border-bottom: 1px solid #f1f3f5; font-size: 0.9rem; }
.evrow:last-child { border-bottom: none; }
.evrow span { color: #6b7280; } .evrow b { color: #111827; font-weight: 700; }
/* Custom KPI cards with mini visuals */
.kpi-row { display: flex; gap: 14px; margin-bottom: 16px; }
.kpi-card { flex: 1; background:#fff; border:1px solid #eceef1; border-radius:14px;
  padding:14px 16px; box-shadow:0 1px 3px rgba(16,24,40,.06); position:relative; min-height:86px; }
.kpi-label { color:#6b7280; font-size:.8rem; font-weight:600; }
.kpi-val { color:#111827; font-size:1.55rem; font-weight:800; margin-top:4px; letter-spacing:-0.5px; }
.kpi-sub { font-size:.72rem; font-weight:600; margin-top:3px; color:#6b7280; }
.kpi-spark { position:absolute; top:14px; right:14px; }
/* Profit calendar (HTML grid) */
.cal { background:#fff; border:1px solid #eceef1; border-radius:14px; padding:14px 16px;
  box-shadow:0 1px 3px rgba(16,24,40,.05); }
.cal-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
.cal-title { font-weight:700; font-size:1.05rem; color:#111827; }
.cal-grid { display:grid; grid-template-columns:repeat(7,1fr) 0.8fr; gap:6px; }
.cal-dow { font-size:.7rem; color:#9aa3ad; font-weight:600; text-align:center; }
.cal-cell { position:relative; min-height:58px; border-radius:10px; background:#f3f5f8;
  border:1px solid #eef0f3; padding:6px 8px; }
.cal-cell.empty { background:transparent; border:none; }
.cal-cell.win { background:#e8f6ee; border-color:#cdebd8; }
.cal-cell.loss { background:#fdeaea; border-color:#f6cccc; }
.cal-day { position:absolute; top:5px; right:8px; font-size:.7rem; color:#9aa3ad; font-weight:600; }
.cal-pnl { font-size:.82rem; font-weight:800; margin-top:20px; }
.cal-pnl.win { color:#16a34a; } .cal-pnl.loss { color:#dc2626; }
.cal-n { font-size:.64rem; color:#6b7280; }
.cal-total { background:#fafbfc; border:1px dashed #e5e7eb; border-radius:10px;
  display:flex; align-items:center; justify-content:center; }
</style>
"""


def _register_plotly_theme(go, pio):
    """One Plotly template so every chart is transparent + consistently styled
    for the light Edgewonk-style theme."""
    pio.templates["toai"] = go.layout.Template(layout=dict(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Manrope, sans-serif", color="#374151", size=13),
        colorway=["#16a34a", "#ef4444", "#3b82f6", "#a855f7", "#f59e0b", "#10b981"],
        xaxis=dict(gridcolor="rgba(17,24,39,0.06)", zerolinecolor="rgba(17,24,39,0.15)",
                   linecolor="rgba(17,24,39,0.12)"),
        yaxis=dict(gridcolor="rgba(17,24,39,0.06)", zerolinecolor="rgba(17,24,39,0.15)",
                   linecolor="rgba(17,24,39,0.12)"),
        legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0),
        margin=dict(t=44, l=12, r=12, b=12),
    ))
    pio.templates.default = "toai"


# --- tiny inline-SVG widgets for the KPI cards (the Edgewonk mini-visuals) --- #
def _spark_svg(vals, color="#16a34a", w=92, h=34):
    vals = [v for v in vals if v == v]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    n = len(vals)
    pts = " ".join(f"{i/(n-1)*w:.1f},{h-(v-lo)/rng*h:.1f}" for i, v in enumerate(vals))
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><polyline points="{pts}" '
            f'fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" '
            f'stroke-linecap="round"/></svg>')


def _gauge_svg(pct, w=66, h=40):
    import math
    r, cx, cy = 27, w / 2, h - 3
    def pt(frac):
        a = math.pi * (1 - max(0.0, min(1.0, frac)))
        return cx + r * math.cos(a), cy - r * math.sin(a)
    x0, y0 = pt(0); x1, y1 = pt(1); xp, yp = pt(pct / 100)
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<path d="M{x0:.1f},{y0:.1f} A{r},{r} 0 0 1 {x1:.1f},{y1:.1f}" fill="none" '
            f'stroke="#e5e7eb" stroke-width="6" stroke-linecap="round"/>'
            f'<path d="M{x0:.1f},{y0:.1f} A{r},{r} 0 0 1 {xp:.1f},{yp:.1f}" fill="none" '
            f'stroke="#16a34a" stroke-width="6" stroke-linecap="round"/></svg>')


def _splitbar_svg(win, loss, w=92, h=9):
    a, b = abs(win or 0), abs(loss or 0)
    wg = a / ((a + b) or 1) * w
    return (f'<svg width="{w}" height="{h}"><rect x="0" y="0" width="{wg:.1f}" height="{h}" '
            f'rx="3" fill="#16a34a"/><rect x="{wg:.1f}" y="0" width="{w-wg:.1f}" height="{h}" '
            f'rx="3" fill="#ef4444"/></svg>')


def kpi_cards_html(cards) -> str:
    """cards: list of {label, val, sub?, sub_color?, visual?(svg)}."""
    out = []
    for c in cards:
        vis = f'<div class="kpi-spark">{c["visual"]}</div>' if c.get("visual") else ""
        sub = (f'<div class="kpi-sub" style="color:{c.get("sub_color", "#6b7280")}">'
               f'{c["sub"]}</div>') if c.get("sub") else ""
        out.append(f'<div class="kpi-card">{vis}<div class="kpi-label">{c["label"]}</div>'
                   f'<div class="kpi-val">{c["val"]}</div>{sub}</div>')
    return f'<div class="kpi-row">{"".join(out)}</div>'


def calendar_html(mdf, unit_label="$") -> str:
    """An Edgewonk-style month grid: rounded day tiles, trade-days tinted
    green/red with the P&L and trade count, plus a weekly Total column."""
    import calendar
    m = {pd.Timestamp(d).date(): (p, n)
         for d, p, n in zip(mdf["Day"], mdf["uPnL"], mdf["count"])}
    if not m:
        return "<div class='cal'>No trades this month.</div>"
    any_d = next(iter(m))
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(any_d.year, any_d.month)
    head = "".join(f"<div class='cal-dow'>{d}</div>"
                   for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")) \
        + "<div class='cal-dow'>Total</div>"
    cells = []
    for wk in weeks:
        wtot = 0.0
        for day in wk:
            if day.month != any_d.month:
                cells.append("<div class='cal-cell empty'></div>")
                continue
            info = m.get(day)
            if info:
                p, n = info
                wtot += p
                cls = "win" if p >= 0 else "loss"
                cells.append(
                    f"<div class='cal-cell {cls}'><div class='cal-day'>{day.day}</div>"
                    f"<div class='cal-pnl {cls}'>{p:+.0f}</div>"
                    f"<div class='cal-n'>{int(n)} trade{'s' if n != 1 else ''}</div></div>")
            else:
                cells.append(f"<div class='cal-cell'><div class='cal-day'>{day.day}</div></div>")
        if wtot:
            tcls = "win" if wtot >= 0 else "loss"
            cells.append(f"<div class='cal-total'><span class='cal-pnl {tcls}' "
                         f"style='margin:0'>{wtot:+.0f}</span></div>")
        else:
            cells.append("<div class='cal-total'></div>")
    title = pd.Timestamp(any_d).strftime("%B %Y")
    return (f"<div class='cal'><div class='cal-head'><div class='cal-title'>{title}</div>"
            f"<div class='cal-dow'>in {unit_label}</div></div>"
            f"<div class='cal-grid'>{head}{''.join(cells)}</div></div>")


# --------------------------------------------------------------------------- #
#  Streamlit UI (imports the heavy libs lazily, so the helpers above stay light)
# --------------------------------------------------------------------------- #
def main():
    import streamlit as st
    import plotly.graph_objects as go
    import plotly.io as pio

    # Light-theme palette that matches the Plotly template + green accent.
    GREEN, RED, MUTED, ACCENT = "#16a34a", "#ef4444", "#6b7280", "#a855f7"
    mode = config.MODE_LABEL  # LIVE / PLAYBACK

    st.set_page_config(page_title=f"TOAI Analytics — {mode}", layout="wide")
    _register_plotly_theme(go, pio)
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    if config.IS_PLAYBACK:
        st.warning("⏵ PLAYBACK MODE — replay data, not live money "
                   "(root: C:\\LIOR_ML_PLAYBACK)")
    st.title(f"📈 TOAI Analytics — {mode}")
    st.caption("ML-aware: every metric is sliced by the model's score and the gate's "
               "verdict. Reads your local executions/journal/bar data — nothing leaves "
               "this machine.")

    insts = instruments()
    if not insts:
        st.info("No instruments found under the data root yet.")
        return

    with st.sidebar:
        st.header("Filters")
        inst = st.selectbox("Instrument", insts)
        source = st.radio("Data source", ["Realized fills", "Walk-forward backtest"],
                          help="Realized = your actual fills. Walk-forward = honest "
                               "out-of-sample backtest of the active model.")
        d = _inst_dir(inst)
        live_thr = config.get_threshold(d)
        threshold = st.slider("ML gate threshold", 0, 100, int(live_thr),
                              help=f"Live threshold is {live_thr:g}. Drag to explore "
                                   "what a different gate would do.")
        unit = st.radio("Display unit", ["$", "points", "ticks"], horizontal=True)
        st.divider()
        st.caption("🎯 Goals (net P&L targets)")
        goal_day = st.number_input("Daily goal ($)", value=200, step=50)
        goal_week = st.number_input("Weekly goal ($)", value=800, step=100)
        goal_month = st.number_input("Monthly goal ($)", value=3000, step=250)

    scored, _thr, oos, dfrom, dto = scored_for(inst, source)
    ex = load_realized(inst)

    def u(dollars):
        return to_units(dollars, inst, unit)
    usym = unit_symbol(unit)

    tab_home, tab_edge, tab_break, tab_cal, tab_goals, tab_sim, tab_explore, tab_ai = st.tabs(
        ["🏠 Home", "🎯 ML edge", "🔬 Breakdowns", "📅 Calendar", "🥅 Goals",
         "🧪 Simulator", "🕯 Trade explorer", "🤖 AI Coach"])

    # ---- HOME: one-glance overview (Edgewonk-style) — fits a screen, no scroll ----
    with tab_home:
        k = kpis(ex)
        if not k:
            st.info("No realized fills yet — the ML edge tab still works on the "
                    "Walk-forward backtest.")
        else:
            ev = evaluation(ex)
            ml_edge = None
            if scored is not None and len(scored):
                _sc = scorecard.scorecard_from_scored(
                    scored, threshold, inst, out_of_sample=oos,
                    realized=(source == "Realized fills"))
                ml_edge = _sc.edge_per_trade if _sc else None
            cum = (pd.to_numeric(ex["Profit"], errors="coerce").fillna(0)
                   .cumsum().apply(u).tolist())
            cards = [
                {"label": "Net P&L", "val": f"{u(k['net']):,.2f}{usym}",
                 "visual": _spark_svg(cum, GREEN if k["net"] >= 0 else RED)},
                {"label": "Win rate", "val": f"{k['win_rate']:.0f}%",
                 "visual": _gauge_svg(k["win_rate"])},
                {"label": "Avg / trade", "val": f"{u(k['expectancy']):,.2f}{usym}",
                 "visual": _splitbar_svg(k["avg_win"], k["avg_loss"]),
                 "sub": f"win {u(k['avg_win']):.1f} · loss {u(k['avg_loss']):.1f}"},
                {"label": "Profit factor",
                 "val": f"{k['profit_factor']:.2f}" if k["profit_factor"] else "—"},
                {"label": "ML edge / trade",
                 "val": f"{u(ml_edge):+.2f}{usym}" if ml_edge is not None else "—",
                 "sub": "ALLOW vs all", "sub_color": GREEN},
            ]
            st.markdown(kpi_cards_html(cards), unsafe_allow_html=True)

            left, right = st.columns([3, 2], gap="medium")
            with left:
                st.subheader("Profit calendar")
                dp = daily_pnl(ex)
                dp["Day"] = pd.to_datetime(dp["Day"])
                dp["uPnL"] = dp["sum"].apply(u)
                msel = dp["Day"].dt.to_period("M").astype(str).max()
                mdf = dp[dp["Day"].dt.to_period("M").astype(str) == msel]
                st.markdown(calendar_html(mdf, usym.strip() or "$"),
                            unsafe_allow_html=True)
            with right:
                st.subheader("Evaluation")
                hold = f"{ev['avg_hold']:.0f}" if ev["avg_hold"] == ev["avg_hold"] else "—"
                streak = (f"{ev['streak']} {'win' if ev['streak_win'] else 'loss'}"
                          if ev.get("streak") else "—")
                rows = [
                    ("Total trades", str(ev["trades"])),
                    ("Avg profit / day", f"{u(ev['avg_per_day']):,.2f}{usym}"),
                    ("Biggest winner", f"{u(ev['biggest_win']):,.2f}{usym}"),
                    ("Biggest loser", f"{u(ev['biggest_loss']):,.2f}{usym}"),
                    ("Total fees", f"${ev['total_fees']:,.2f}"),
                    ("Avg hold (min)", hold),
                    ("Win rate", f"{ev['win_rate']:.0f}%"),
                    ("Winning / losing days", f"{ev['win_days']} / {ev['loss_days']}"),
                    ("Trades / day", f"{ev['trades_per_day']:.1f}"),
                    ("Current streak", streak),
                ]
                html = "".join(f"<div class='evrow'><span>{a}</span><b>{b}</b></div>"
                               for a, b in rows)
                st.markdown(f"<div class='evpanel'>{html}</div>", unsafe_allow_html=True)

    # ---- TAB 1: ML edge (works for both sources via the scorecard machinery) ----
    with tab_edge:
        if scored is None or len(scored) == 0:
            st.info("Not enough scored trades for this source yet.")
        else:
            sc = scorecard.scorecard_from_scored(
                scored, threshold, inst, out_of_sample=oos,
                realized=(source == "Realized fills"), date_from=dfrom, date_to=dto)
            basis = ("realized fills" if source == "Realized fills"
                     else "walk-forward, out-of-sample" if oos else "in-sample (few trades)")
            st.caption(f"{sc.n_trades} trades · {basis}"
                       + (f" · {dfrom} → {dto}" if dfrom else ""))

            c1, c2, c3 = st.columns(3)
            c1.metric("ALLOW expectancy", f"${sc.allow.expectancy:+,.2f}",
                      f"{sc.allow.win_rate:.0f}% win")
            c2.metric("Edge per taken trade", f"${sc.edge_per_trade:+,.2f}",
                      "vs trading everything")
            c3.metric("Selectivity", f"{sc.selectivity:.0f}%",
                      f"{sc.allow.n} of {sc.all.n} trades")

            # Expectancy by score bucket — the core ML-separation view.
            if sc.buckets:
                b = pd.DataFrame([{
                    "Bucket": f"{x.lo:g}-{x.hi:g}", "Expectancy": x.expectancy,
                    "Win%": x.win_rate, "N": x.n} for x in sc.buckets])
                fig = go.Figure(go.Bar(
                    x=b["Bucket"], y=b["Expectancy"],
                    marker_color=[GREEN if v >= 0 else RED for v in b["Expectancy"]],
                    text=[f"${v:+.0f}<br>{w:.0f}% (n={n})"
                          for v, w, n in zip(b["Expectancy"], b["Win%"], b["N"])],
                    textposition="outside"))
                fig.update_layout(
                    title="Expectancy by ML score bucket ($/trade)",
                    yaxis_title="$ / trade", height=380, margin=dict(t=40))
                fig.add_hline(y=0, line_color=MUTED)
                st.plotly_chart(fig, width='stretch')
                st.caption("If the bars rise left→right, the model is separating good "
                           "trades from bad by money — the thing no external journal can show.")

            # Equity: ALLOW-only vs trading everything.
            try:
                eq = scorecard.equity_curves(scored, threshold)
                if eq is not None:
                    all_eq, allow_eq = eq
                    fig2 = go.Figure()
                    fig2.add_trace(go.Scatter(y=all_eq, name="Trade everything",
                                              line=dict(color=MUTED)))
                    fig2.add_trace(go.Scatter(y=allow_eq, name="ALLOW only",
                                              line=dict(color=GREEN, width=2)))
                    fig2.update_layout(title="Equity — ALLOW only vs trading everything",
                                       height=340, margin=dict(t=40),
                                       yaxis_title="cumulative $")
                    st.plotly_chart(fig2, width='stretch')
            except Exception:
                pass

    # ---- TAB 2: breakdowns (realized frame) ----
    with tab_break:
        if ex.empty:
            st.info("No realized fills yet for breakdowns.")
        else:
            exn = ex.copy()
            exn["Profit"] = pd.to_numeric(exn["Profit"], errors="coerce")
            left, right = st.columns(2)

            with left:
                by_hour = exn.groupby("Hour")["Profit"].agg(["sum", "count"]).reset_index()
                fig = go.Figure(go.Bar(
                    x=by_hour["Hour"], y=by_hour["sum"],
                    marker_color=[GREEN if v >= 0 else RED for v in by_hour["sum"]],
                    text=by_hour["count"], textposition="outside"))
                fig.update_layout(title="P&L by entry hour (ET)", height=320,
                                  xaxis_title="hour", yaxis_title="$", margin=dict(t=40))
                st.plotly_chart(fig, width='stretch')

                if exn["Variant"].notna().any():
                    bv = exn.groupby(exn["Variant"].fillna("—"))["Profit"].agg(
                        ["sum", "count"]).reset_index()
                    fig = go.Figure(go.Bar(
                        x=bv["sum"], y=bv["Variant"], orientation="h",
                        marker_color=[GREEN if v >= 0 else RED for v in bv["sum"]],
                        text=bv["count"], textposition="outside"))
                    fig.update_layout(title="P&L by strategy/variant", height=320,
                                      xaxis_title="$", margin=dict(t=40))
                    st.plotly_chart(fig, width='stretch')

            with right:
                # MAE/MFE vs outcome, coloured by ML score — does the model pick
                # trades that go less underwater?
                if {"MAE", "MFE"}.issubset(exn.columns):
                    mae = pd.to_numeric(exn["MAE"], errors="coerce")
                    col = pd.to_numeric(exn.get("Score"), errors="coerce")
                    fig = go.Figure(go.Scatter(
                        x=mae, y=exn["Profit"], mode="markers",
                        marker=dict(size=11, color=col, colorscale="Viridis",
                                    showscale=bool(col.notna().any()),
                                    colorbar=dict(title="ML"), line=dict(width=1)),
                        text=[f"score {s}" for s in exn.get("Score", "")]))
                    fig.update_layout(title="MAE vs P&L (colour = ML score)", height=320,
                                      xaxis_title="MAE", yaxis_title="$", margin=dict(t=40))
                    fig.add_hline(y=0, line_color=MUTED)
                    st.plotly_chart(fig, width='stretch')

                if exn["RMultiple"].notna().any():
                    fig = go.Figure(go.Histogram(x=exn["RMultiple"], nbinsx=20,
                                                 marker_color=ACCENT))
                    fig.update_layout(title="R-multiple distribution", height=320,
                                      xaxis_title="R", margin=dict(t=40))
                    st.plotly_chart(fig, width='stretch')

            # Exit efficiency — how much of each trade's best move it captured,
            # coloured by ML score. Low bars = giving profit back before exit.
            eff = exit_efficiency(ex, inst)
            eff = eff[eff["Efficiency"].notna()] if not eff.empty else eff
            if not eff.empty:
                col = pd.to_numeric(eff["Score"], errors="coerce")
                fig = go.Figure(go.Bar(
                    x=[f"{t:%m-%d %H:%M}" for t in eff["EntryTime"]],
                    y=eff["Efficiency"],
                    marker=dict(color=col, colorscale="Viridis",
                                showscale=bool(col.notna().any()),
                                colorbar=dict(title="ML")),
                    text=[f"{v:.0f}%" for v in eff["Efficiency"]], textposition="outside"))
                fig.update_layout(
                    title="Exit efficiency — captured % of the best move (MFE)",
                    yaxis_title="% of MFE captured", height=320, margin=dict(t=40))
                fig.add_hline(y=0, line_color=MUTED)
                st.plotly_chart(fig, width='stretch')
                st.caption(f"Median capture: {eff['Efficiency'].median():.0f}% of the "
                           "best move. If ML-high trades capture more, the score is "
                           "also picking cleaner exits.")

    # ---- TAB 3: Calendar & seasonality ----
    with tab_cal:
        if ex.empty:
            st.info("No realized fills yet for the calendar.")
        else:
            dp = daily_pnl(ex)
            dp["Day"] = pd.to_datetime(dp["Day"])
            dp["uPnL"] = dp["sum"].apply(u)
            # Month calendar heatmap (week rows × weekday cols).
            months = sorted(dp["Day"].dt.to_period("M").astype(str).unique())
            msel = st.selectbox("Month", months, index=len(months) - 1)
            mdf = dp[dp["Day"].dt.to_period("M").astype(str) == msel]
            z, txt = _calendar_grid(mdf)
            fig = go.Figure(go.Heatmap(
                z=z, x=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                text=txt, texttemplate="%{text}", colorscale="RdYlGn", zmid=0,
                showscale=True, hoverinfo="text"))
            fig.update_layout(title=f"Daily net P&L — {msel} ({usym.strip() or '$'})",
                              height=300, margin=dict(t=40), yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, width='stretch')

            s = seasonality(ex)
            if s:
                a, bcol = st.columns(2)
                for cc, key, title in ((a, "dow", "P&L by weekday"),
                                       (bcol, "month", "P&L by month")):
                    g = s[key]
                    fig = go.Figure(go.Bar(
                        x=g["k"], y=g["sum"].apply(u),
                        marker_color=[GREEN if v >= 0 else RED for v in g["sum"]],
                        text=g["count"], textposition="outside"))
                    fig.update_layout(title=title, height=300, margin=dict(t=40),
                                      yaxis_title=usym.strip() or "$")
                    cc.plotly_chart(fig, width='stretch')

    # ---- TAB 4: Goals ----
    with tab_goals:
        if ex.empty:
            st.info("No realized fills yet to measure against goals.")
        else:
            e = ex.copy()
            e["Profit"] = pd.to_numeric(e["Profit"], errors="coerce")
            e["EntryTime"] = pd.to_datetime(e["EntryTime"])
            today = e["EntryTime"].dt.date.max()
            iso = pd.Timestamp(today).isocalendar()
            day_pnl = e[e["EntryTime"].dt.date == today]["Profit"].sum()
            week_pnl = e[e["EntryTime"].dt.isocalendar().week.eq(iso.week) &
                         e["EntryTime"].dt.isocalendar().year.eq(iso.year)]["Profit"].sum()
            month_pnl = e[e["EntryTime"].dt.to_period("M") ==
                          pd.Period(today, "M")]["Profit"].sum()
            st.caption(f"Latest trading day in data: {today}")
            for label, pnl, goal in (("Today", day_pnl, goal_day),
                                     ("This week", week_pnl, goal_week),
                                     ("This month", month_pnl, goal_month)):
                pct = (pnl / goal * 100) if goal else 0
                st.metric(f"{label} — {u(pnl):,.2f}{usym} / {u(goal):,.0f}{usym} goal",
                          f"{pct:.0f}%")
                st.progress(min(1.0, max(0.0, pnl / goal if goal else 0)))

    # ---- TAB 5: what-if stop/target simulator ----
    with tab_sim:
        if ex.empty or not {"MAE", "MFE"}.issubset(ex.columns):
            st.info("Need realized fills with MAE/MFE to simulate.")
        else:
            pv, tick = contract(inst)
            st.caption("Re-run your actual trades under a different fixed stop / "
                       "target, using each trade's recorded MAE/MFE. No bar history "
                       "needed — answers \"what if my stop was tighter?\" on real fills.")
            cc = st.columns(3)
            stop_pts = cc[0].slider("Stop (points)", 0.0, 30.0, 5.0, 0.25)
            target_pts = cc[1].slider("Target (points)", 0.0, 40.0, 10.0, 0.25)
            tie = cc[2].radio("If both hit, assume", ["stop", "target"],
                              help="MAE/MFE don't reveal which came first.")
            sim = simulate_sltp(ex, inst, stop_pts, target_pts, tie)
            if sim.empty:
                st.info("No simulatable trades.")
            else:
                a, b = _net_stats(sim["Actual"]), _net_stats(sim["Sim"])
                m = st.columns(4)
                m[0].metric("Sim net", f"{u(b['net']):,.2f}{usym}",
                            f"{u(b['net'] - a['net']):+,.2f} vs actual")
                m[1].metric("Sim win rate", f"{b['win']:.0f}%", f"{b['win'] - a['win']:+.0f}pp")
                m[2].metric("Sim PF", f"{b['pf']:.2f}" if b["pf"] else "—")
                oc = sim["Outcome"].value_counts().to_dict()
                m[3].metric("Stopped / Target / Actual",
                            f"{oc.get('stop',0)} / {oc.get('target',0)} / {oc.get('actual',0)}")

                sim = sim.sort_values("EntryTime")
                fig = go.Figure()
                fig.add_trace(go.Scatter(y=sim["Actual"].apply(u).cumsum(),
                                         name="Actual", line=dict(color=MUTED)))
                fig.add_trace(go.Scatter(y=sim["Sim"].apply(u).cumsum(),
                                         name="Simulated", line=dict(color=GREEN, width=2)))
                fig.update_layout(title="Equity — simulated stop/target vs actual",
                                  height=340, margin=dict(t=40),
                                  yaxis_title=usym.strip() or "$")
                st.plotly_chart(fig, width='stretch')
                st.caption(f"1 point = ${pv:g} · tie broken as '{tie}'. Trades that hit "
                           "neither level keep their real outcome.")

    # ---- TAB 6: trade explorer (per-trade candles + markers) ----
    with tab_explore:
        if ex.empty:
            st.info("No realized fills to explore yet.")
        else:
            show = ex[["EntryTime", "ExitTime", "Direction", "EntryPrice", "ExitPrice",
                       "Profit", "MAE", "MFE", "Score", "Verdict", "Variant"]].copy()
            st.dataframe(show, width='stretch', height=240)

            bars, has_ohlc = load_bars(inst)
            labels = [f"#{i} · {r.EntryTime:%Y-%m-%d %H:%M} · {r.Direction} · "
                      f"${pd.to_numeric(pd.Series([r.Profit]), errors='coerce')[0]:+.2f}"
                      for i, r in ex.iterrows()]
            pick = st.selectbox("Plot a trade", range(len(ex)),
                                format_func=lambda i: labels[i])
            r = ex.iloc[pick]
            if bars.empty:
                st.info("No bar_data to chart.")
            else:
                w = trade_bars(bars, r["EntryTime"], r["ExitTime"]).reset_index(drop=True)
                if len(w) > 2:
                    upto = st.slider("Replay (reveal bars up to)", 2, len(w), len(w),
                                     help="Drag left to replay the trade bar by bar.")
                    w = w.iloc[:upto]
                ctypes = (["Candlestick", "Heikin-Ashi", "Renko", "Line"]
                          if has_ohlc else ["Line"])
                copts = st.columns([2, 3])
                ctype = copts[0].selectbox("Chart type", ctypes)
                ema_cols = [c for c in ("EMA9", "EMA20", "EMA50") if c in w.columns]
                inds = copts[1].multiselect("Indicators", ema_cols, default=ema_cols[:2])

                fig = go.Figure()
                if ctype == "Candlestick":
                    fig.add_trace(go.Candlestick(
                        x=w["DateTime"], open=w["Open"], high=w["High"],
                        low=w["Low"], close=w["Close"], name="price"))
                elif ctype == "Heikin-Ashi":
                    ha = heikin_ashi(w)
                    fig.add_trace(go.Candlestick(
                        x=ha["DateTime"], open=ha["Open"], high=ha["High"],
                        low=ha["Low"], close=ha["Close"], name="Heikin-Ashi"))
                elif ctype == "Renko":
                    pv, tick = contract(inst)
                    brick = max(tick, round(float(w["ATR20"].median()) / 2, 4)
                                if "ATR20" in w.columns and w["ATR20"].notna().any() else tick)
                    rk = renko_bricks(w, brick)
                    if not rk.empty:
                        fig.add_trace(go.Bar(
                            x=list(range(len(rk))),
                            y=[brick] * len(rk), base=rk[["Open", "Close"]].min(axis=1),
                            marker_color=[GREEN if up else RED for up in rk["Up"]],
                            name=f"Renko ({brick:g})"))
                        fig.update_layout(xaxis_title="brick #")
                    st.caption(f"Renko brick size {brick:g} (≈½ ATR).")
                else:   # Line
                    yname = "Close" if "Close" in w.columns else "EMA20"
                    fig.add_trace(go.Scatter(x=w["DateTime"], y=w[yname], name=yname,
                                             line=dict(color=MUTED)))
                    if not has_ohlc:
                        st.caption("bar_data has no OHLC yet — showing the EMA20 line. "
                                   "Recompile TOAIExporterGaugeTick to get real candles.")
                if ctype != "Renko":
                    for c in inds:
                        fig.add_trace(go.Scatter(x=w["DateTime"], y=w[c], name=c,
                                                 line=dict(width=1)))
                if ctype != "Renko":   # time-x markers don't map onto brick #
                    _marker(fig, go, r["EntryTime"], r["EntryPrice"], "Entry", GREEN)
                    _marker(fig, go, r["ExitTime"], r["ExitPrice"], "Exit", RED)
                for lvl, name, color in (("StopLoss", "Stop", RED),
                                         ("TakeProfit", "Target", GREEN)):
                    v = pd.to_numeric(pd.Series([r.get(lvl)]), errors="coerce")[0]
                    if pd.notna(v) and v > 0:
                        fig.add_hline(y=v, line_dash="dot", line_color=color,
                                      annotation_text=name)
                sc_txt = f"ML score {r.get('Score')}" if pd.notna(r.get("Score")) else "no ML score"
                fig.update_layout(
                    title=f"{r['Direction']} · {r['EntryTime']:%Y-%m-%d %H:%M} · "
                          f"{sc_txt} · {r.get('Verdict', '')}",
                    height=480, xaxis_rangeslider_visible=False, margin=dict(t=50))
                st.plotly_chart(fig, width='stretch')

    # ---- TAB 7: AI Coach (off-path Claude, ML-aware) ----
    with tab_ai:
        st.caption("Off-path Claude (claude-opus-4-8) reading your real fills WITH the "
                   "ML score & verdict — the analysis no external journal can do. "
                   "Uses the Anthropic API, so usage costs apply.")
        if not ai_coach.available():
            st.info("Set **ANTHROPIC_API_KEY** in the environment to enable the AI "
                    "Coach, then relaunch.\n\n```\nsetx ANTHROPIC_API_KEY sk-ant-...\n```")
        elif ex.empty:
            st.info("No realized fills yet for the coach to analyse.")
        else:
            c1, c2 = st.columns(2)
            if c1.button("🗓 Daily debrief", width='stretch'):
                with st.spinner("Coaching…"):
                    st.session_state["ai_daily"] = ai_coach.daily_summary(ex, inst)
            if st.session_state.get("ai_daily"):
                st.markdown(st.session_state["ai_daily"])

            st.divider()
            tlabels = [f"{r.EntryTime:%m-%d %H:%M} · {r.Direction} · "
                       f"${pd.to_numeric(pd.Series([r.Profit]), errors='coerce')[0]:+.2f}"
                       for _, r in ex.iterrows()]
            ti = c2.selectbox("Review a trade", range(len(ex)),
                              format_func=lambda i: tlabels[i])
            if c2.button("🔍 Review this trade", width='stretch'):
                with st.spinner("Reviewing…"):
                    st.session_state["ai_review"] = ai_coach.review_trade(ex.iloc[ti], inst)
            if st.session_state.get("ai_review"):
                st.markdown(st.session_state["ai_review"])

            st.divider()
            st.caption("💬 Ask about your journal")
            for m in st.session_state.get("ai_chat", []):
                with st.chat_message(m["role"]):
                    st.markdown(m["content"])
            q = st.chat_input("e.g. which hour should I stop trading?")
            if q:
                hist = st.session_state.get("ai_chat", [])
                with st.chat_message("user"):
                    st.markdown(q)
                with st.chat_message("assistant"):
                    with st.spinner("Thinking…"):
                        a = ai_coach.chat(q, ex, inst, hist)
                    st.markdown(a)
                st.session_state["ai_chat"] = hist + [
                    {"role": "user", "content": q}, {"role": "assistant", "content": a}]


def _calendar_grid(mdf):
    """A month grid (week rows × weekday cols) of daily P&L for the heatmap."""
    import calendar
    vals = {pd.Timestamp(d).date(): v for d, v in zip(mdf["Day"], mdf["uPnL"])}
    if not vals:
        return [[None] * 7], [[""] * 7]
    any_date = next(iter(vals))
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(
        any_date.year, any_date.month)
    z, txt = [], []
    for wk in weeks:
        zrow, trow = [], []
        for day in wk:
            if day.month != any_date.month:
                zrow.append(None); trow.append("")
            else:
                v = vals.get(day)
                zrow.append(v if v is not None else 0.0)
                trow.append(f"{day.day}<br>{v:+.0f}" if v is not None else f"{day.day}")
        z.append(zrow); txt.append(trow)
    return z, txt


def _marker(fig, go, t, price, name, color):
    try:
        price = float(price)
    except (TypeError, ValueError):
        return
    if pd.isna(t):
        return
    fig.add_trace(go.Scatter(
        x=[t], y=[price], mode="markers+text", name=name,
        marker=dict(size=13, color=color, symbol="triangle-up"
                    if name == "Entry" else "triangle-down", line=dict(width=1)),
        text=[name], textposition="top center"))


if __name__ == "__main__":
    main()
