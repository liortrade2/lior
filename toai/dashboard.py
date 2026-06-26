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
    from . import ai_coach, config, journal, reset, scorecard
except ImportError:
    import pathlib
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from toai import ai_coach, config, journal, reset, scorecard

OHLC = ["Open", "High", "Low", "Close"]

from pathlib import Path as _Path  # noqa: E402
PROJECT_ROOT = _Path(__file__).resolve().parent.parent


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
    # executions.csv holds only the CURRENT session — the logger rewrites it each
    # day. Union the per-day archives (executions_YYYY-MM-DD.csv) + the current
    # file so the dashboard keeps the FULL trade history, then dedupe identical
    # fills (the current file duplicates today's archive).
    frames = []
    for f in sorted(d.glob("executions_*.csv")) + [d / "executions.csv"]:
        try:
            part = pd.read_csv(f)
        except (OSError, ValueError, pd.errors.EmptyDataError):
            continue
        if not part.empty and "Entry time" in part.columns:
            frames.append(part)
    if not frames:
        return pd.DataFrame()
    ex = pd.concat(frames, ignore_index=True)
    _dedup = [c for c in ("Entry time", "Exit time", "Market pos.", "Qty", "Profit")
              if c in ex.columns]
    if _dedup:
        ex = ex.drop_duplicates(subset=_dedup, keep="last").reset_index(drop=True)

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
        "n_win": int((p > 0).sum()),
        "n_loss": int((p < 0).sum()),
        "n_be": int((p == 0).sum()),
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
    if ex.empty or "Profit" not in ex.columns or "Day" not in ex.columns:
        return pd.DataFrame(columns=["Day", "sum", "count"])
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
.block-container { padding-top: 16px; padding-bottom: 0.6rem; padding-left: 196px; padding-right: 8px; max-width: none; }
/* CSS-injection markdowns must not take vertical space (else they push the calendar down) */
[data-testid="stElementContainer"]:has(style) { display: none !important; }
section[data-testid="stSidebar"] { display: none; }
/* KPI strip + bottom filters sit BELOW the nav rail, so reclaim the left
   gutter: pull them left to the window edge and keep them flush right. */
.st-key-kpiwrap { overflow: visible !important; }
.st-key-kpiwrap [data-testid="stHorizontalBlock"] {
  width: calc(100vw - 24px) !important; max-width: none !important; margin-left: -184px !important;
}
[data-testid="stExpander"] summary { font-weight: 700; }
h1 { font-weight: 800 !important; letter-spacing: -0.6px; color: #111827; font-size: 1.7rem; }
h2, h3 { font-weight: 700 !important; letter-spacing: -0.3px; color: #1f2937; font-size: 1.15rem !important; }
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
/* Vertical left-rail navigation — the nav radio (key=toainav) styled as a
   sticky left column of icon items; content sits to its right. */
.st-key-nav_toggle { position: fixed; left: 12px; top: 16px; width: 176px; z-index: 51; }
.st-key-nav_toggle button { width: 100%; border-radius: 8px; border-color: #e9ebef;
  color: #6b7280; font-weight: 700; min-height: 32px; }
.st-key-toainav { position: fixed; left: 12px; top: 56px; width: 176px; z-index: 50;
  max-height: calc(100vh - 68px); overflow-y: auto; }
.st-key-toainav [role="radiogroup"] { flex-direction: column; gap: 3px; }
.st-key-toainav [role="radiogroup"] label {
  width: 100%; padding: 8px 12px; border-radius: 8px;
  border-left: 3px solid transparent; cursor: pointer; margin: 0;
}
.st-key-toainav [role="radiogroup"] label:hover { background: #f3f5f8; }
.st-key-toainav [role="radiogroup"] label p { font-weight: 600; font-size: 0.92rem; }
.st-key-toainav [role="radiogroup"] label:has(input:checked) {
  background: #ecfdf3; border-left-color: #16a34a;
}
.st-key-toainav [role="radiogroup"] label:has(input:checked) p { color: #15803d; }
.st-key-toainav [role="radiogroup"] label > div:first-child { display: none; }  /* hide the radio dot */
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
/* full-width Evaluation panel (below the calendar): flow stats into 2 columns */
.evpanel.wide { margin-top: 12px; column-count: 2; column-gap: 32px; }
.evpanel.wide .evrow { break-inside: avoid; }
.evrow { display: flex; justify-content: space-between; align-items: center; gap: 8px;
  padding: 6px 0; border-bottom: 1px solid #f1f3f5; font-size: 0.78rem; white-space: nowrap; }
.evrow:last-child { border-bottom: none; }
.evrow span { color: #6b7280; } .evrow b { color: #111827; font-weight: 700; }
/* Custom KPI cards with mini visuals */
.kpi-row { display: flex; gap: 10px; margin-top: 12px; width: 100%; }
.kpi-card { flex: 1 1 0; min-width: 0; background:#fff; border:1px solid #eceef1;
  border-radius:14px; padding:12px 14px; box-shadow:0 1px 3px rgba(16,24,40,.06);
  display:flex; flex-direction:column; justify-content:center; min-height:120px; }
/* equal-height KPI cards — every card fills its column up to the tallest one */
.st-key-kpiwrap [data-testid="stHorizontalBlock"] { align-items:stretch; }
.st-key-kpiwrap [data-testid="stColumn"],
.st-key-kpiwrap [data-testid="stColumn"] > div,
.st-key-kpiwrap [data-testid="stVerticalBlock"],
.st-key-kpiwrap [data-testid="stElementContainer"],
.st-key-kpiwrap [data-testid="stMarkdown"],
.st-key-kpiwrap [data-testid="stMarkdownContainer"] { height:100%; }
.st-key-kpiwrap .kpi-card { height:100%; }
.kpi-label { color:#6b7280; font-size:.82rem; font-weight:600; }
.kpi-mid { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-top:4px; }
.kpi-val { color:#111827; font-size:1.45rem; font-weight:800; letter-spacing:-0.5px; white-space:nowrap; }
.kpi-vis { flex-shrink:0; line-height:0; }
.kpi-sub { font-size:.72rem; font-weight:600; margin-top:4px; color:#6b7280; }
.kpi-sub .pill { display:inline-block; min-width:16px; text-align:center; padding:1px 7px;
  border-radius:8px; font-weight:700; font-size:.7rem; margin-right:4px; }
.kpi-sub .pill.win { background:#e8f6ee; color:#16a34a; }
.kpi-sub .pill.be { background:#f1f3f5; color:#6b7280; }
.kpi-sub .pill.loss { background:#fdeaea; color:#dc2626; }
/* Profit calendar (HTML grid) — Edgewonk-style */
.cal { background:#fff; border:1px solid #eceef1; border-radius:14px; padding:14px 16px;
  box-shadow:0 1px 3px rgba(16,24,40,.05); }
.cal-cardtitle { font-weight:700; font-size:1.15rem; color:#111827; }
.day-back { display:block; text-align:center; text-decoration:none; cursor:pointer;
  padding:8px 12px; border:1px solid #e9ebef; border-radius:8px; color:#111827;
  font-weight:600; background:#fff; transition:background .12s, border-color .12s; }
.day-back:hover { background:#f3f4f6; border-color:#d1d5db; }
.cal-monthlbl { font-weight:700; font-size:1rem; color:#111827; text-align:center;
  margin-top:10px; position:relative; top:10px; }  /* June onto the Monthly-goal line */
/* live-watch control row — status text + slide toggle on a single line */
.watch-status { font-size:.74rem; color:#6b7280; font-weight:600; white-space:nowrap;
  position:relative; top:10px; }
.st-key-watch_toggle [data-testid="stWidgetLabel"] { display:none; }
.st-key-watch_toggle { position:relative; top:20px; }
/* the ‹ › nav buttons in the calendar header row */
.st-key-cal_prev button, .st-key-cal_next button { border-radius:7px; padding:1px 9px;
  min-height:0; color:#6b7280; font-size:.85rem; line-height:1.2; margin-top:12px;
  position:relative; top:10px; }
/* hug the arrows to the "June 2026" label */
.st-key-cal_prev { display:flex; justify-content:flex-end; }
.st-key-cal_next { display:flex; justify-content:flex-start; }
.cal-grid { display:grid; grid-template-columns:repeat(8,1fr); grid-template-rows:auto;
  grid-auto-rows:84px; gap:7px; }
.cal-dow { font-size:.68rem; color:#9aa3ad; font-weight:600; text-align:center;
  padding-bottom:2px; }
.cal-cell { position:relative; min-height:60px; border-radius:12px; background:#f4f7fe;
  border:1px solid #eaf0fb; padding:6px 9px; }
.cal-cell.win { background:#e8f6ee; border-color:#cdebd8; }
.cal-cell.loss { background:#fdeaea; border-color:#f6cccc; }
/* clickable trade days → open the day journal */
.cal-cell.link { text-decoration:none; color:inherit; cursor:pointer; display:block;
  transition:box-shadow .12s ease, transform .12s ease; }
.cal-cell.link:hover { box-shadow:0 5px 14px rgba(16,24,40,.16); transform:translateY(-2px); }
.cal-cell.out { background:repeating-linear-gradient(-45deg,#fbfcfe,#fbfcfe 5px,
  #eef1f6 5px,#eef1f6 10px); border-color:#eef1f6; }
.cal-cell.today { border:2px solid #111827; }
.cal-daynum { position:absolute; top:6px; right:6px; min-width:22px; height:22px; padding:0 5px;
  border-radius:11px; background:#ffffff; color:#6b7280; font-size:.7rem; font-weight:700;
  display:flex; align-items:center; justify-content:center; box-shadow:0 1px 1px rgba(16,24,40,.05); }
.cal-cell.out .cal-daynum { background:transparent; box-shadow:none; color:#b9c0c9; }
.cal-pnl { font-size:.9rem; font-weight:800; margin-top:24px; }
.cal-pnl.win { color:#16a34a; } .cal-pnl.loss { color:#dc2626; }
.cal-n { font-size:.66rem; color:#6b7280; }
/* daily / weekly goal progress bars */
.cal-daybar { position:absolute; left:9px; right:9px; bottom:7px; height:3px;
  border-radius:2px; background:rgba(16,24,40,.07); overflow:hidden; }
.cal-daybar i { display:block; height:100%; border-radius:2px; background:#16a34a; }
.cal-daybar.done i { background:#15803d; }
.cal-wbar { width:78%; height:4px; margin-top:5px; border-radius:2px;
  background:rgba(16,24,40,.07); overflow:hidden; }
.cal-wbar i { display:block; height:100%; border-radius:2px; background:#16a34a; }
.cal-wbar.done i { background:#15803d; }
.cal-total { border-radius:12px; background:#f8fafc; border:1px solid #eef0f3;
  display:flex; flex-direction:column; align-items:center; justify-content:center; }
.cal-total.win { background:#e8f6ee; border-color:#cdebd8; }
.cal-total.loss { background:#fdeaea; border-color:#f6cccc; }
.cal-foot { display:flex; justify-content:flex-end; align-items:center; gap:10px;
  margin-top:10px; padding-top:10px; border-top:1px solid #eef0f3; }
.cal-foot span { color:#6b7280; font-size:.8rem; font-weight:600; }
.cal-foot b { font-size:1rem; font-weight:800; margin:0; }
/* Monthly-goal tracker — sits in its own row below the calendar, hugging right */
.cal-goal-below { display:flex; justify-content:flex-start; margin-top:10px;
  margin-left:-120px; }  /* left edge ("Monthly goal") sits at X≈400 */
.cal-goal-below .cal-goal { width:600px; max-width:none; }  /* span 600px → $-values right edge at X≈1000 */
.cal-goal { width:100%; }
/* Eval bar docked in the top account row (right of the Account selector) */
.acct-eval { width:100%; }
.acct-eval .cal-goal { width:100%; max-width:none; }
/* Top account row: inset 16px each side so its left (Account) and right (eval
   bar) edges line up with the calendar card's inner frame below it. */
.st-key-acctrow { padding-left:16px; padding-right:16px; }
/* Collapsible section headers (Control etc.) — clickable list-row look. */
[class*="st-key-btn_sec_"] button {
  justify-content:flex-start !important; text-align:left;
  background:#f6f8fa; border:1px solid #e7eaee; border-radius:10px;
  padding:8px 14px; color:#1f2937; box-shadow:none; }
[class*="st-key-btn_sec_"] button:hover { background:#eef1f5; border-color:#d7dbe0; }
[class*="st-key-btn_sec_"] button p { font-weight:700 !important; font-size:1rem !important; }
[class*="st-key-ctl_openall"] button, [class*="st-key-ctl_collapseall"] button {
  padding:3px 10px; font-size:.8rem; }
.cal-goal-row { display:flex; justify-content:space-between; align-items:center; padding:1px 0; }
.cal-goal-row span { color:#6b7280; font-size:.8rem; font-weight:600; }
.cal-goal-row b { font-size:.95rem; font-weight:800; }
.cal-goal-row b.gval { color:#111827; }
.cal-goal-bar { height:7px; border-radius:4px; background:#eef1f6; overflow:hidden; margin:5px 0; }
.cal-goal-bar i { display:block; height:100%; border-radius:4px; background:#16a34a; }
.cal-goal-bar i.loss { background:#ef4444; }
.cal-goal-bar i.warn { background:#f59e0b; }
.cal-goal-cap { text-align:right; font-size:.66rem; color:#9aa3ad; margin-top:3px; }
/* Hide the eval-bar caption (Net · buffer · bal · floor) per user preference. */
.acct-eval .cal-goal-cap { display:none; }
.acct-lbl { text-align:right; font-size:.8rem; font-weight:600; color:#6b7280; white-space:nowrap; }
/* evaluation range bar: Trailing DD (left) · 0 (center) · Profit target (right) */
.eval-labels { display:flex; justify-content:space-between; align-items:center;
  font-size:.74rem; font-weight:600; margin-bottom:5px; }
.eval-labels .loss { color:#dc2626; } .eval-labels .win { color:#16a34a; }
.eval-labels .mid { color:#9aa3ad; font-size:.7rem; }
.eval-bar { position:relative; height:12px; border-radius:6px; background:#eef1f6; overflow:hidden; }
.eval-fill { position:absolute; top:0; bottom:0; }
.eval-fill.win { background:#16a34a; } .eval-fill.loss { background:#ef4444; }
.eval-zero { position:absolute; top:0; bottom:0; width:2px; background:#c2c8d0;
  transform:translateX(-1px); }
.eval-floor { position:absolute; top:0; bottom:0; width:2px; background:#111827;
  transform:translateX(-1px); }
.cal-goal-rem { text-align:right; font-size:.78rem; font-weight:700; color:#6b7280; margin-top:1px; }
.cal-goal-rem.win { color:#16a34a; } .cal-goal-rem.loss { color:#dc2626; }
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
def _spark_svg(vals, color="#16a34a", w=92, h=34, fill=True):
    vals = [v for v in vals if v == v]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    n = len(vals)
    pts = [(i / (n - 1) * w, h - (v - lo) / rng * h) for i, v in enumerate(vals)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    # Edgewonk-style filled area under the curve, tinted by direction.
    area = (f'<polygon points="0,{h:.1f} {line} {w:.1f},{h:.1f}" '
            f'fill="{color}" fill-opacity="0.12"/>') if fill else ""
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">{area}'
            f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round"/></svg>')


def _gauge_svg(pct, w=66, h=40):
    """Half-circle gauge: green over the winning fraction, red over the rest
    (Edgewonk-style), instead of green-over-grey."""
    import math
    r, cx, cy = 27, w / 2, h - 3
    def pt(frac):
        a = math.pi * (1 - max(0.0, min(1.0, frac)))
        return cx + r * math.cos(a), cy - r * math.sin(a)
    x0, y0 = pt(0); x1, y1 = pt(1); xp, yp = pt(pct / 100)
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<path d="M{x0:.1f},{y0:.1f} A{r},{r} 0 0 1 {x1:.1f},{y1:.1f}" fill="none" '
            f'stroke="#ef4444" stroke-width="6" stroke-linecap="round"/>'
            f'<path d="M{x0:.1f},{y0:.1f} A{r},{r} 0 0 1 {xp:.1f},{yp:.1f}" fill="none" '
            f'stroke="#16a34a" stroke-width="6" stroke-linecap="round"/></svg>')


def _ring_svg(pct, color="#16a34a", w=46, h=46):
    """A donut ring filled to `pct` (0-100) — mirrors Edgewonk's score ring."""
    import math
    r = 18.0
    cx = cy = w / 2
    circ = 2 * math.pi * r
    dash = circ * max(0.0, min(1.0, pct / 100))
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#e5e7eb" stroke-width="5"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="5" '
            f'stroke-linecap="round" stroke-dasharray="{dash:.1f} {circ:.1f}" '
            f'transform="rotate(-90 {cx} {cy})"/></svg>')


def _pfbar_svg(pf, w=92, h=14):
    """A scale with breakeven (1.0) at center and a marker at the profit factor —
    green right of center when PF>1, red when below."""
    if pf is None:
        return ""
    x = max(0.0, min(2.0, pf)) / 2 * w
    col = "#16a34a" if pf >= 1 else "#ef4444"
    cx, mid = w / 2, h / 2
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<line x1="0" y1="{mid}" x2="{w}" y2="{mid}" stroke="#e5e7eb" '
            f'stroke-width="3" stroke-linecap="round"/>'
            f'<line x1="{cx}" y1="2" x2="{cx}" y2="{h-2}" stroke="#9aa3ad" stroke-width="1.5"/>'
            f'<circle cx="{x:.1f}" cy="{mid}" r="4.5" fill="{col}"/></svg>')


def _splitbar_svg(win, loss, w=92, h=9):
    a, b = abs(win or 0), abs(loss or 0)
    wg = a / ((a + b) or 1) * w
    return (f'<svg width="{w}" height="{h}"><rect x="0" y="0" width="{wg:.1f}" height="{h}" '
            f'rx="3" fill="#16a34a"/><rect x="{wg:.1f}" y="0" width="{w-wg:.1f}" height="{h}" '
            f'rx="3" fill="#ef4444"/></svg>')


def _kpi_card_one(c) -> str:
    """One KPI card: label on top, then value + mini-visual side by side (so the
    spark/gauge/split-bar never overlaps the label), optional sub line below."""
    vis = f'<div class="kpi-vis">{c["visual"]}</div>' if c.get("visual") else ""
    sub = (f'<div class="kpi-sub" style="color:{c.get("sub_color", "#6b7280")}">'
           f'{c["sub"]}</div>') if c.get("sub") else ""
    return (f'<div class="kpi-card"><div class="kpi-label">{c["label"]}</div>'
            f'<div class="kpi-mid"><div class="kpi-val">{c["val"]}</div>{vis}</div>{sub}</div>')


def kpi_cards_html(cards) -> str:
    """A flex row of KPI cards — used by the saved 1060x512 journal HTML."""
    return f'<div class="kpi-row">{"".join(_kpi_card_one(c) for c in cards)}</div>'


def _cal_fmt(v, unit_label):
    """Format a calendar P&L value. Dollars round to whole; points/ticks keep
    two decimals so a real +0.78 pts never shows as a misleading +1."""
    return f"{v:+,.0f}" if unit_label == "$" else f"{v:+,.2f}"


def _goalbar(actual, target, cls):
    """A thin progress bar (actual vs $ target). Empty when target unset."""
    if not target:
        return ""
    pct = max(0.0, min(100.0, actual / target * 100))
    done = " done" if actual >= target else ""
    return f"<div class='{cls}{done}'><i style='width:{pct:.0f}%'></i></div>"


def calendar_html(mdf, unit_label="$", month=None, today=None,
                  goal_day=None, goal_week=None) -> str:
    """An Edgewonk-style month grid: each day a tinted tile with a circular
    day-badge, the P&L and trade count; the current day framed; next-month
    days hatched; a tinted weekly Total column. `month` ('YYYY-MM') pins which
    month to draw (empty months still render); `today` (a date) frames the
    current day. `goal_day`/`goal_week` are the $ targets: each day cell shows a
    daily-goal bar and each weekly Total cell a weekly-goal bar. The monthly
    goal/total summary lives in the header row (see `_month_goal_html`)."""
    import calendar
    has_sum = "sum" in getattr(mdf, "columns", [])
    sums = mdf["sum"] if has_sum else mdf["uPnL"]
    m = {pd.Timestamp(d).date(): (p, n, s)
         for d, p, n, s in zip(mdf["Day"], mdf["uPnL"], mdf["count"], sums)}
    if month:
        yr, mo = (int(x) for x in str(month).split("-")[:2])
    elif m:
        any_d = next(iter(m))
        yr, mo = any_d.year, any_d.month
    else:
        return "<div class='cal'>No trades this month.</div>"
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(yr, mo)
    head = "".join(f"<div class='cal-dow'>{d}</div>"
                   for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")) \
        + "<div class='cal-dow'>Total</div>"
    cells = []
    for wk in weeks:
        wtot = 0.0       # week net in display units
        wtot_d = 0.0     # week net in $ (for the weekly-goal bar)
        for day in wk:
            badge = f"<span class='cal-daynum'>{day.day}</span>"
            if day.month != mo:
                # Day spilling in from the adjacent month — hatched, muted.
                cells.append(f"<div class='cal-cell out'>{badge}</div>")
                continue
            tcls = " today" if today and day == today else ""
            info = m.get(day)
            if info:
                p, n, s = info
                wtot += p
                wtot_d += s
                cls = "win" if p >= 0 else "loss"
                bar = _goalbar(s, goal_day, "cal-daybar")
                tip = (f" title='Day {s:+,.0f}$ of ${goal_day:,.0f} goal'"
                       if goal_day else "")
                # Trade days are links → ?day=YYYY-MM-DD opens that day's journal.
                cells.append(
                    f"<a class='cal-cell link {cls}{tcls}'{tip} "
                    f"href='?day={day.isoformat()}' target='_self'>{badge}"
                    f"<div class='cal-pnl {cls}'>{_cal_fmt(p, unit_label)}</div>"
                    f"<div class='cal-n'>{int(n)} trade{'s' if n != 1 else ''}</div>"
                    f"{bar}</a>")
            else:
                cells.append(f"<div class='cal-cell{tcls}'>{badge}</div>")
        if wtot:
            tcls = "win" if wtot >= 0 else "loss"
            wbar = _goalbar(wtot_d, goal_week, "cal-wbar")
            wtip = (f" title='Week {wtot_d:+,.0f}$ of ${goal_week:,.0f} goal'"
                    if goal_week else "")
            cells.append(f"<div class='cal-total {tcls}'{wtip}><span class='cal-pnl {tcls}' "
                         f"style='margin:0'>{_cal_fmt(wtot, unit_label)}</span>{wbar}</div>")
        else:
            cells.append("<div class='cal-total'></div>")
    return (f"<div class='cal'>"
            f"<div class='cal-grid'>{head}{''.join(cells)}</div></div>")


def _month_goal_html(mtot_disp, unit_label, goal, goal_now):
    """The monthly goal/total summary block — set vs now vs remaining — shown in
    the calendar header row. `mtot_disp` is the month net in display units;
    `goal`/`goal_now` are the $ target and the month net in $."""
    mcls = "win" if mtot_disp >= 0 else "loss"
    tot_b = (f"<b class='cal-pnl {mcls}'>{_cal_fmt(mtot_disp, unit_label)} "
             f"{unit_label}</b>")
    if not goal:
        return (f"<div class='cal-goal'><div class='cal-goal-row'>"
                f"<span>Month total</span>{tot_b}</div></div>")
    pct = max(0.0, min(100.0, goal_now / goal * 100))
    reached = goal_now >= goal
    rem = goal - goal_now
    barcls = "" if goal_now >= 0 else "loss"
    remcls = "win" if reached else "loss" if goal_now < 0 else ""
    rem_text = "🎉 Goal reached" if reached else f"${rem:,.0f}"
    return (f"<div class='cal-goal'>"
            f"<div class='cal-goal-row'><span>Monthly goal</span>"
            f"<b class='gval'>${goal:,.0f}</b></div>"
            f"<div class='cal-goal-bar'><i class='{barcls}' "
            f"style='width:{pct:.0f}%'></i></div>"
            f"<div class='cal-goal-row'><span>Month total</span>"
            f"<b class='cal-goal-rem {remcls}'>{rem_text}</b></div></div>")


def _eval_html(net_now, dd_from_peak, profit_target, max_dd, account_size=0,
               min_buf=None):
    """Prop-evaluation tracker (Bulenox 25K-style): progress toward the $ profit
    target, and the remaining real-time trailing-drawdown buffer. `net_now` =
    cumulative account P&L ($, commission-inclusive); `dd_from_peak` = how far
    below the (intraday, MFE-inclusive) high-water mark. The trailing floor LOCKS
    at the starting balance (Bulenox stops trailing there). `min_buf` is the
    closest the real-time equity (incl. intraday MAE lows) ever got to the floor —
    ≤0 means it was touched."""
    pt, md = profit_target or 0, max_dd or 0
    rng = (md + pt) or 1
    peak_net = net_now + dd_from_peak
    floor_net = min(peak_net - md, 0.0) if md else 0.0   # locked at start
    buf = net_now - floor_net                            # $ before failing
    blown = bool(md) and buf <= 0
    target_hit = bool(pt) and net_now >= pt

    def _pos(v):  # value in net terms (−md … +pt) → 0..100% across the bar
        return max(0.0, min(100.0, (v + md) / rng * 100))
    zero, npos, fpos = _pos(0), _pos(net_now), _pos(floor_net)
    lo, hi = sorted((zero, npos))
    fillcls = "win" if net_now >= 0 else "loss"

    labels = (f"<div class='eval-labels'>"
              f"<span class='loss'>Trailing DD ${md:,.0f}</span>"
              f"<span class='mid'>0</span>"
              f"<span class='win'>Profit target ${pt:,.0f}</span></div>")
    bar = (f"<div class='eval-bar'>"
           f"<div class='eval-fill {fillcls}' style='left:{lo:.1f}%;width:{hi-lo:.1f}%'></div>"
           f"<div class='eval-floor' style='left:{fpos:.1f}%'></div>"
           f"<div class='eval-zero' style='left:{zero:.1f}%'></div></div>")
    parts = ["🎉 target hit" if target_hit else f"Net {net_now:+,.0f}",
             "❌ DD hit" if blown else f"buffer ${buf:,.0f}"]
    if account_size:
        parts.append(f"bal ${account_size + net_now:,.0f}")
        parts.append(f"floor ${account_size + floor_net:,.0f}")
    if min_buf is not None and min_buf <= 0:
        parts.append("<b style='color:#dc2626'>⚠ touched floor</b>")
    cap = f"<div class='cal-goal-cap'>{' · '.join(parts)}</div>"
    return f"<div class='cal-goal'>{labels}{bar}{cap}</div>"


def _day_detail(st, ex, day_str, u, usym):
    """The per-day 'journal' panel shown when a calendar day is clicked
    (?day=YYYY-MM-DD) — a quick summary plus that day's individual trades."""
    try:
        d0 = pd.Timestamp(day_str).date()
    except (ValueError, TypeError):
        st.query_params.clear()
        return
    sub = ex[ex["Day"] == d0].copy()
    hc = st.columns([6, 2], vertical_alignment="center")
    hc[0].markdown(f"<div class='cal-cardtitle'>📋 Trades on "
                   f"{d0:%A, %B} {d0.day}, {d0.year}</div>", unsafe_allow_html=True)
    # "Back to month" is an anchor to ?  (no day) — the same navigation the
    # calendar uses to OPEN a day, so it reliably clears the URL. Styled to look
    # like a secondary button.
    hc[1].markdown(
        "<a href='?' target='_self' class='day-back'>‹ Back to month</a>",
        unsafe_allow_html=True)
    if sub.empty:
        st.info("No trades on this day.")
        st.divider()
        return
    p = pd.to_numeric(sub["Profit"], errors="coerce").fillna(0)
    mc = st.columns(4)
    mc[0].metric("Day net", f"{u(p.sum()):,.2f}{usym}")
    mc[1].metric("Trades", str(len(p)))
    mc[2].metric("Win rate", f"{(p > 0).mean() * 100:.0f}%")
    mc[3].metric("Best / worst", f"{u(p.max()):+.1f} / {u(p.min()):+.1f}{usym}")
    unit = usym.strip() or "$"
    disp = pd.DataFrame({
        "Entry": sub["EntryTime"].dt.strftime("%H:%M:%S"),
        "Exit": pd.to_datetime(sub["ExitTime"], errors="coerce").dt.strftime("%H:%M:%S"),
        "Dir": sub.get("Direction"),
        "Qty": sub.get("Qty"),
        "Entry px": sub.get("EntryPrice"),
        "Exit px": sub.get("ExitPrice"),
        f"P&L ({unit})": p.apply(u).round(2),
        "MAE": pd.to_numeric(sub.get("MAE"), errors="coerce"),
        "MFE": pd.to_numeric(sub.get("MFE"), errors="coerce"),
        "Score": sub.get("Score"),
        "Verdict": sub.get("Verdict"),
    })
    st.dataframe(disp, width='stretch', hide_index=True)
    st.divider()


# --------------------------------------------------------------------------- #
#  Fixed-size 1060x512 "journal" — a self-contained HTML card (its own <style>,
#  since it renders in an isolated iframe) you can embed or save and open
#  standalone at exactly that size.
# --------------------------------------------------------------------------- #
JOURNAL_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800&display=swap');
*{box-sizing:border-box;margin:0;padding:0;font-family:'Manrope',-apple-system,system-ui,sans-serif;}
body{background:#f6f8fa;}
.journal{width:1060px;height:512px;background:#f6f8fa;padding:10px;display:flex;flex-direction:column;gap:10px;}
.kpi-row{display:flex;gap:10px;}
.kpi-card{flex:1;background:#fff;border:1px solid #eceef1;border-radius:12px;padding:10px 12px;position:relative;min-height:76px;box-shadow:0 1px 2px rgba(16,24,40,.06);}
.kpi-label{color:#6b7280;font-size:.72rem;font-weight:600;}
.kpi-val{color:#111827;font-size:1.35rem;font-weight:800;margin-top:2px;letter-spacing:-.5px;}
.kpi-sub{font-size:.64rem;font-weight:600;margin-top:2px;color:#6b7280;}
.kpi-spark{position:absolute;top:10px;right:12px;}
.jlower{display:flex;gap:10px;flex:1;min-height:0;}
.cal{flex:1.7;background:#fff;border:1px solid #eceef1;border-radius:12px;padding:9px 12px;box-shadow:0 1px 2px rgba(16,24,40,.05);display:flex;flex-direction:column;}
.cal-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;}
.cal-title{font-weight:700;font-size:.92rem;color:#111827;}
.cal-grid{display:grid;grid-template-columns:repeat(7,1fr) .8fr;grid-auto-rows:1fr;gap:4px;flex:1;}
.cal-dow{font-size:.6rem;color:#9aa3ad;font-weight:600;text-align:center;}
.cal-cell{position:relative;border-radius:8px;background:#f3f5f8;border:1px solid #eef0f3;padding:2px 6px;}
.cal-cell.empty{background:transparent;border:none;}
.cal-cell.win{background:#e8f6ee;border-color:#cdebd8;}
.cal-cell.loss{background:#fdeaea;border-color:#f6cccc;}
.cal-day{position:absolute;top:2px;right:5px;font-size:.58rem;color:#9aa3ad;font-weight:600;}
.cal-pnl{font-size:.68rem;font-weight:800;margin-top:11px;}
.cal-pnl.win{color:#16a34a;}.cal-pnl.loss{color:#dc2626;}
.cal-n{font-size:.52rem;color:#6b7280;}
.cal-total{background:#fafbfc;border:1px dashed #e5e7eb;border-radius:8px;display:flex;align-items:center;justify-content:center;}
.eval{flex:1;background:#fff;border:1px solid #eceef1;border-radius:12px;padding:2px 14px;box-shadow:0 1px 2px rgba(16,24,40,.05);}
.evrow{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid #f1f3f5;font-size:.76rem;}
.evrow:last-child{border-bottom:none;}
.evrow span{color:#6b7280;}.evrow b{color:#111827;font-weight:700;}
"""


def journal_doc(cards_html, cal_html, eval_rows) -> str:
    evrows = "".join(f"<div class='evrow'><span>{a}</span><b>{b}</b></div>"
                     for a, b in eval_rows)
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<style>{JOURNAL_CSS}</style></head><body>"
            f"<div class='journal'>{cards_html}"
            f"<div class='jlower'>{cal_html}<div class='eval'>{evrows}</div></div>"
            f"</div></body></html>")


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
        st.caption("⏵ PLAYBACK — replay data, not live money.")

    insts = instruments()
    if not insts:
        st.info("No instruments found under the data root yet.")
        return

    # Filter VALUES are read from session_state here (top), but the filter
    # WIDGETS render at the BOTTOM of the page (see _filters_bar at the end).
    # Streamlit writes a widget's value to session_state on interaction before
    # the rerun, so the top sees the current value with no lag.
    ss = st.session_state
    if ss.get("f_inst") not in insts:
        ss["f_inst"] = insts[0]
    if "f_source" not in ss:
        # First load: default to Realized fills, but auto-fall back to the
        # Walk-forward backtest when there are no realized fills yet (e.g. right
        # after a reset + train) so a freshly-trained model is visible without
        # manually flipping the Data source. A later manual choice sticks.
        src0 = "Realized fills"
        try:
            _d0 = _inst_dir(ss["f_inst"])
            _live = journal.live_scored(_d0, source="live")
            if _live is None or len(_live) == 0:
                _bt = scored_for(ss["f_inst"], "Walk-forward backtest")[0]
                if _bt is not None and len(_bt):
                    src0 = "Walk-forward backtest"
        except Exception:
            pass
        ss["f_source"] = src0
    ss.setdefault("f_unit", "$")
    ss.setdefault("f_gday", 200)
    ss.setdefault("f_profit_target", 1500)
    ss.setdefault("f_max_dd", 1500)
    ss.setdefault("f_account_size", 25000)
    ss.setdefault("f_gweek", 800)
    ss.setdefault("f_gmonth", 3000)
    inst, source, unit = ss["f_inst"], ss["f_source"], ss["f_unit"]
    d = _inst_dir(inst)
    live_thr = config.get_threshold(d)
    ss.setdefault("f_thr", int(live_thr))
    threshold = ss["f_thr"]
    goal_day, goal_week, goal_month = ss["f_gday"], ss["f_gweek"], ss["f_gmonth"]

    scored, _thr, oos, dfrom, dto = scored_for(inst, source)
    ex = load_realized(inst)
    # Account filter (pro-journal pattern: one store, filter by the Account
    # column). "All accounts" = consolidated; pick one to scope the whole view
    # (calendar, KPIs, evaluation) to that account, e.g. the Bulenox eval.
    accounts = (sorted(ex["Account"].dropna().astype(str).unique())
                if "Account" in ex.columns and len(ex) else [])
    # Include EVERY NinjaTrader account (the AddOn writes them to accounts.txt),
    # not just ones that have already traded — so you can pick e.g. Bulenox first.
    _acct_file = config.DATA_ROOT / "accounts.txt"
    if _acct_file.exists():
        try:
            accounts = sorted(set(accounts) | {
                a.strip() for a in _acct_file.read_text(
                    encoding="utf-8", errors="ignore").splitlines() if a.strip()})
        except OSError:
            pass
    # Classify each account (Demo / Evaluation / Funded) — persisted in
    # account_types.json, defaulted by name, editable in Filters & goals. Powers
    # the grouped selector: All Evaluation / All Funded / All Demo / per-account.
    import json
    _types_file = config.DATA_ROOT / "account_types.json"
    acct_types_saved = {}
    if _types_file.exists():
        try:
            acct_types_saved = json.loads(_types_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            acct_types_saved = {}

    def _default_type(a):
        al = str(a).lower()
        return "Demo" if ("sim" in al or "demo" in al or "playback" in al) else "Evaluation"
    TYPE_ORDER = ["Evaluation", "Funded", "Demo"]
    SINGLE = "Single account…"
    acct_type = {a: acct_types_saved.get(a, _default_type(a)) for a in accounts}
    # Scope dropdown = groups only; the individual accounts live in a second
    # dropdown that appears when "Single account…" is picked.
    acct_opts = ["All accounts"] + [f"All {t}" for t in TYPE_ORDER] + [SINGLE]
    # Remember the last-used account scope across sessions (persisted to
    # ui_prefs.json) so a fresh page load doesn't snap back to "All accounts".
    _prefs_file = config.DATA_ROOT / "ui_prefs.json"
    _ui_prefs = {}
    if _prefs_file.exists():
        try:
            _ui_prefs = json.loads(_prefs_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _ui_prefs = {}

    def _update_prefs(**kw):
        # Read-modify-write so concurrent savers (account scope, stats toggle)
        # don't clobber each other's keys.
        cur = {}
        if _prefs_file.exists():
            try:
                cur = json.loads(_prefs_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cur = {}
        cur.update(kw)
        try:
            _prefs_file.write_text(json.dumps(cur, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _save_account_pref():
        _update_prefs(f_account=ss.get("f_account"),
                      f_account_one=ss.get("f_account_one"))

    def _section(key, title, icon="", summary="", default_open=False):
        """Collapsible section header (clickable). Open/closed state persists in
        ui_prefs.json so the user's chosen layout sticks across sessions. When
        collapsed, the one-line `summary` shows the key value without opening.
        Returns True when the section is open (caller renders its body)."""
        sk = f"sec_{key}"
        if sk not in ss:
            ss[sk] = bool(_ui_prefs.get(sk, default_open))
        chev = "▾" if ss[sk] else "▸"
        sm = f"   —   {summary}" if (summary and not ss[sk]) else ""

        def _toggle():
            ss[sk] = not ss[sk]
            _update_prefs(**{sk: ss[sk]})
        st.button(f"{chev}  {icon} {title}{sm}", key=f"btn_{sk}",
                  on_click=_toggle, width='stretch')
        return ss[sk]

    def _set_sections(keys, open_):
        for k in keys:
            ss[f"sec_{k}"] = open_
        _update_prefs(**{f"sec_{k}": open_ for k in keys})

    if "f_account" not in ss:
        _saved = _ui_prefs.get("f_account")
        ss["f_account"] = _saved if _saved in acct_opts else "All accounts"
    elif ss.get("f_account") not in acct_opts:
        ss["f_account"] = "All accounts"
    if "f_account_one" not in ss:
        _saved1 = _ui_prefs.get("f_account_one")
        if accounts:
            ss["f_account_one"] = _saved1 if _saved1 in accounts else accounts[0]
    elif accounts and ss.get("f_account_one") not in accounts:
        ss["f_account_one"] = accounts[0]

    def _scope_label(a):
        if a == "All accounts":
            return "📊 All accounts"
        if a == SINGLE:
            return "👤 Single account…"
        return f"▸ All {a[4:]} accounts"

    def _one_label(a):  # "BX104751-01!Bulenox!Bulenox" -> "Bulenox · BX104751-01"
        parts = [p for p in str(a).split("!") if p]
        return f"{parts[1]} · {parts[0]}" if len(parts) >= 2 else a

    # Prominent, always-visible selector at the top (TradeZella-style): Account on
    # the left, the prop-evaluation bar continuing horizontally to its right
    # (filled below once eval_html is computed).
    _scope = ss["f_account"]
    with st.container(key="acctrow"):
        if _scope == SINGLE and accounts:
            _ac = st.columns([1.7, 1.9, 5.5], gap="small", vertical_alignment="center")
            _ac[0].selectbox("Scope", acct_opts, key="f_account",
                             format_func=_scope_label, label_visibility="collapsed",
                             on_change=_save_account_pref)
            _ac[1].selectbox("Account", accounts, key="f_account_one",
                             format_func=_one_label, label_visibility="collapsed",
                             on_change=_save_account_pref)
        else:
            _ac = st.columns([1.9, 7.2], gap="small", vertical_alignment="center")
            _ac[0].selectbox("Scope", acct_opts, key="f_account",
                             format_func=_scope_label, label_visibility="collapsed",
                             on_change=_save_account_pref)
    _evalcol = _ac[-1]

    if "Account" in ex.columns and _scope != "All accounts":
        if _scope == SINGLE:
            _one = ss.get("f_account_one")
            if _one:
                ex = ex[ex["Account"].astype(str) == _one].reset_index(drop=True)
        else:  # "All <Type>"
            _keep = [a for a in accounts if acct_type[a] == _scope[4:]]
            ex = ex[ex["Account"].astype(str).isin(_keep)].reset_index(drop=True)

    # Prop-evaluation (Bulenox 25K): cumulative account P&L ($) and how far below
    # the high-water mark. Peak = INTRADAY high-water mark (real-time, incl.
    # unrealized) = balance-before + MFE($). Floor locks at start. min_buf =
    # closest the real-time low (balance-before − MAE) came to the (locked) floor
    # — ≤0 means the floor was touched intraday. Computed globally (after account
    # filtering) so the eval bar can sit in the top row on every tab.
    eval_net = eval_dd = eval_min_buf = 0.0
    if "Profit" in ex.columns and len(ex):
        _prof = pd.to_numeric(ex["Profit"], errors="coerce").fillna(0)
        _mfe = pd.to_numeric(ex.get("MFE", 0), errors="coerce").fillna(0)
        _mae = pd.to_numeric(ex.get("MAE", 0), errors="coerce").fillna(0)
        _closed = _prof.cumsum()
        _before = _closed.shift(1).fillna(0.0)
        eval_net = float(_closed.iloc[-1])
        _md = ss["f_max_dd"]
        _peak_series = pd.concat([_before + _mfe, _closed], axis=1).max(axis=1).cummax()
        _floor_series = (_peak_series - _md).clip(upper=0.0)
        eval_dd = max(0.0, float(_peak_series.iloc[-1]) - eval_net)
        eval_min_buf = float(((_before - _mae) - _floor_series).min())
    eval_html = _eval_html(eval_net, eval_dd, ss["f_profit_target"],
                           ss["f_max_dd"], ss["f_account_size"], eval_min_buf)
    _evalcol.markdown(f"<div class='acct-eval'>{eval_html}</div>",
                      unsafe_allow_html=True)

    def u(dollars):
        return to_units(dollars, inst, unit)
    usym = unit_symbol(unit)

    NAV = ["🏠 Home", "🎚 Filters", "⚙️ Control", "🎯 ML edge", "🔬 Breakdowns",
           "📅 Calendar", "🥅 Goals", "🧪 Simulator", "🕯 Trade explorer",
           "🤖 AI Coach"]
    # Collapse button: shrinks the rail to icon-only.
    ss.setdefault("nav_collapsed", True)  # start collapsed (icons only)
    if st.button("»" if ss["nav_collapsed"] else "«  Collapse", key="nav_toggle",
                 width='stretch'):
        ss["nav_collapsed"] = not ss["nav_collapsed"]
        st.rerun()
    nav_collapsed = ss["nav_collapsed"]
    view = st.radio("Navigation", NAV, label_visibility="collapsed", key="toainav",
                    format_func=(lambda o: o.split(" ", 1)[0]) if nav_collapsed
                    else (lambda o: o))
    if nav_collapsed:
        st.markdown(
            "<style>"
            ".st-key-nav_toggle, .st-key-toainav { width:52px !important; }"
            ".st-key-toainav [role='radiogroup'] label { padding:9px 4px !important;"
            " justify-content:center; }"
            ".st-key-toainav [role='radiogroup'] label p { font-size:1.2rem !important; }"
            ".block-container { padding-left:72px !important; }"
            ".st-key-kpiwrap [data-testid='stHorizontalBlock']"
            " { margin-left:-60px !important; }"
            "</style>", unsafe_allow_html=True)

    # ---- CONTROL: everything the Control Panel does, in the dashboard ----
    if view == "⚙️ Control":
        import subprocess
        import sys
        d = _inst_dir(inst)
        thr = config.get_threshold(d)

        # Open all / Collapse all — one-click control over the whole section list.
        _ctl_secs = ["ctl_live", "ctl_gate", "ctl_tf", "ctl_variants",
                     "ctl_mode", "ctl_actions", "ctl_watch", "ctl_reset"]
        _oc = st.columns([1.1, 1.3, 6])
        if _oc[0].button("⛶ Open all", key="ctl_openall", width='stretch'):
            _set_sections(_ctl_secs, True); st.rerun()
        if _oc[1].button("⊟ Collapse all", key="ctl_collapseall", width='stretch'):
            _set_sections(_ctl_secs, False); st.rerun()

        # ── Live status ── (open by default)
        try:
            _sc_txt = (d / "score.txt").read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            _sc_txt = "—"
        try:
            _verdict = "ALLOW" if float(_sc_txt) >= thr else "SKIP"
        except ValueError:
            _verdict = "—"
        if _section("ctl_live", "Live status", "🟢",
                    f"score {_sc_txt} · {_verdict}"):
            auto = st.checkbox("🔄 Auto-refresh every 2s", value=False, key="ctl_auto")

            @st.fragment(run_every=2 if auto else None)
            def _live_status():
                try:
                    sc_txt = (d / "score.txt").read_text(encoding="utf-8", errors="ignore").strip()
                except OSError:
                    sc_txt = "—"
                t = config.get_threshold(d)
                try:
                    verdict = "ALLOW" if float(sc_txt) >= t else "SKIP"
                except ValueError:
                    verdict = "—"
                cc = st.columns(4)
                cc[0].metric("Live score", sc_txt)
                cc[1].metric("Threshold", f"{t:g}")
                cc[2].metric("Gate", verdict)
                try:
                    from toai import health
                    h = health.check(inst)
                    cc[3].metric("Model age",
                                 f"{h['age_days']}d" if h.get("age_days") is not None else "—",
                                 "stale" if h.get("stale") else "ok")
                    for m in h.get("messages", []):
                        st.caption("⚠ " + m)
                except Exception:
                    pass
            _live_status()

        # ── Gate threshold ──
        if _section("ctl_gate", "Gate threshold", "🎯", f"min score {int(thr)}"):
            tcol = st.columns([3, 1])
            newthr = tcol[0].number_input("min ML score to ALLOW", 0, 100, int(thr), key="ctl_thr")
            if tcol[1].button("Apply to live", width='stretch'):
                config.set_threshold(float(newthr), d)
                st.success(f"Live threshold for {inst} set to {newthr:g}.")

        # ── Training timeframe ──
        tf_opts = ["Auto", "1", "2", "3", "5", "15"]
        cur_tf = config.get_train_tf(d)
        cur_lbl = "Auto" if cur_tf is None else str(cur_tf)
        if _section("ctl_tf", "Training timeframe", "🕒", cur_lbl):
            gc = st.columns([3, 1])
            seltf = gc[0].radio("Train new exports as", tf_opts,
                                index=tf_opts.index(cur_lbl) if cur_lbl in tf_opts else 0,
                                horizontal=True, key="ctl_traintf")
            if gc[1].button("Set TF", width='stretch'):
                config.set_train_tf(None if seltf == "Auto" else int(seltf), d)
                st.success(f"Training timeframe set to {seltf}.")

        # ── Active model / variants ──
        try:
            reg = variants._load_registry(d)
        except Exception:
            reg = {}
        active = next((s for s, v in reg.items() if v.get("active")), None)
        _vsum = (f"{reg[active].get('name', active)} · WF {reg[active].get('wf_mean', 0):.2f}"
                 if active else ("none active" if reg else "no variants"))
        if _section("ctl_variants", "Active model / variants", "🧬", _vsum):
            if reg:
                slugs = list(reg)

                def _vlabel(s):
                    v = reg[s]
                    dot = "● " if s == active else ""
                    return (f"{dot}{v.get('name', s)}  ·  PMV {v.get('pmv', 0):.3f} · "
                            f"WF {v.get('wf_mean', 0):.3f} · {v.get('timeframe', '?')}m")
                pick = st.radio("Choose the variant to score live with", slugs,
                                index=slugs.index(active) if active in slugs else 0,
                                format_func=_vlabel, key="ctl_variant")
                if st.button("Activate selected variant", type="primary"):
                    variants.select_variant(pick, d, rescore=True)
                    st.success(f"Activated: {reg[pick].get('name', pick)} — the live "
                               "model.pkl is now this variant.")

                with st.expander("Manage variants — portfolio toggle / delete"):
                    arm_del = st.checkbox("Arm delete (irreversible)", key="ctl_armdel")
                    for s in slugs:
                        v = reg[s]
                        mc = st.columns([5, 2, 1])
                        mc[0].write(v.get("name", s))
                        in_pf = bool(v.get("portfolio"))
                        new_pf = mc[1].checkbox("⊕ portfolio", value=in_pf, key=f"ctl_pf_{s}")
                        if new_pf != in_pf:
                            variants.set_portfolio(s, d, on=new_pf)
                            st.rerun()
                        if mc[2].button("🗑", key=f"ctl_del_{s}", disabled=not arm_del):
                            variants.delete_variant(s, d)
                            st.success(f"Deleted {v.get('name', s)}.")
                            st.rerun()
            else:
                st.info("No variants yet. Train an export below to create one.")

        # ── Strategy mode ──
        from toai import score as _score
        _mmf = d / "mode_manual.txt"
        try:
            _cur_manual = _mmf.read_text().strip()
        except OSError:
            _cur_manual = ""
        _mode_opts = ["Auto (from model)", "Standard", "Mean Reversion"]
        _mi = _mode_opts.index(_cur_manual) if _cur_manual in _mode_opts else 0
        if _section("ctl_mode", "Strategy mode", "🧭", _cur_manual or "Auto (from model)"):
            mc = st.columns([3, 1], vertical_alignment="bottom")
            mode_pick = mc[0].selectbox(
                "Chart-HUD mode — tag the strategy when you upload it",
                _mode_opts, index=_mi, key="ctl_mode")
            if mc[1].button("Apply", width='stretch', key="ctl_mode_apply"):
                try:
                    if mode_pick.startswith("Auto"):
                        if _mmf.exists():
                            _mmf.unlink()
                    else:
                        _mmf.write_text(mode_pick)
                    import joblib
                    try:
                        _bm = joblib.load(d / "model.pkl")
                    except Exception:
                        _bm = {"features": []}
                    _score.write_mode(_bm, d / "mode.txt")
                    st.success(f"HUD mode → {_score.model_mode(_bm, d)}")
                except Exception as e:
                    st.error(f"Failed: {e}")
            st.caption("Auto = derived from the model (Mean Reversion when the "
                       "candle-shape features are on). Pin it manually to tag the "
                       "strategy — the choice persists across retrains and shows on "
                       "the chart HUD.")

        # ── Actions ──
        if _section("ctl_actions", "Actions", "⚡"):
            a = st.columns(2)
            if a[0].button("⚙ Train newest export", width='stretch'):
                from toai.build_and_train import build_and_train, find_trades_export
                p = find_trades_export()
                if p is None:
                    st.warning(f"No trades export found in {config.DATA_ROOT}.")
                else:
                    with st.spinner(f"Training {p.name}…"):
                        try:
                            build_and_train(trades_file=p)
                            st.success(f"Trained {p.name}. Reload the chart for scores.")
                        except Exception as e:
                            st.error(f"Train failed: {e}")
            if a[1].button("💾 Backup models", width='stretch'):
                from toai import backup
                try:
                    p = backup.backup_instrument(d)
                    st.success(f"Backed up → {p}" if p else "Nothing to back up yet.")
                except Exception as e:
                    st.error(f"Backup failed: {e}")

            b = st.columns(3)
            if b[0].button("🧹 Clear NT cache", width='stretch'):
                from toai import ninja_cache
                try:
                    st.success(f"Cleared NinjaTrader cache: {ninja_cache.clear_cache()}")
                except Exception as e:
                    st.error(f"Clear failed: {e}")
            arm = b[1].checkbox("Arm day routines", help="Start/End-day launch or "
                                "close NinjaTrader. Tick to enable the buttons.")
            if b[2].button("🌅 Start day", width='stretch', disabled=not arm):
                from toai import routines
                with st.spinner("Start-of-day…"):
                    st.success(str(routines.start_of_day()))
            if arm and st.button("🌙 End day"):
                from toai import routines
                with st.spinner("End-of-day…"):
                    st.success(str(routines.end_of_day()))

        # ── Live watch ──
        proc = st.session_state.get("watch_proc")
        running = proc is not None and proc.poll() is None
        if _section("ctl_watch", "Live watch", "👁",
                    "🟢 running" if running else "⚪ not started"):
            st.write("Status: " + ("🟢 running (this dashboard)" if running else "⚪ not started here"))
            w = st.columns(2)
            if w[0].button("▶ Start watch", width='stretch', disabled=running):
                st.session_state["watch_proc"] = subprocess.Popen(
                    [sys.executable, "-c", "from toai.score import watch; watch()"],
                    cwd=str(PROJECT_ROOT))
                st.success("Watch started in the background.")
            if w[1].button("⏹ Stop watch", width='stretch', disabled=not running):
                proc.terminate()
                st.session_state["watch_proc"] = None
                st.success("Watch stopped.")
            st.caption("The watch scores live bars → score.txt, ingests fills → journal, "
                       "and auto-trains new exports. ⚠️ Run only ONE watcher — if "
                       "TOAI_Control.bat is already running its watch, don't start a second.")

        # ── Reset a simulation account ──
        if _section("ctl_reset", "Reset a simulation account", "🗑"):
            _sims = reset.sim_accounts(accounts)
            if not _sims:
                st.caption("No simulation accounts found yet (e.g. NinjaTrader "
                           "Sim101). They appear here once they've traded or are "
                           "listed in accounts.txt.")
            else:
                rc = st.columns([3, 1], vertical_alignment="bottom")
                sim_pick = rc[0].selectbox("Account to reset", _sims,
                                           key="ctl_reset_acct")
                n_rows = reset.count_rows(sim_pick)
                rc[1].metric("Fills", n_rows)
                confirm = st.checkbox(
                    f"Yes, delete all {n_rows} fill(s) for {sim_pick} across every "
                    f"instrument", key="ctl_reset_confirm")
                if st.button("🗑 Reset account", type="primary", width='stretch',
                             disabled=not confirm or n_rows == 0):
                    try:
                        res = reset.reset_account(sim_pick)
                        st.toast(f"Reset {res['account']}: removed "
                                 f"{res['removed']} fill(s) + "
                                 f"{res['journal_removed']} journal row(s).",
                                 icon="✅")
                        if res["backup"]:
                            st.toast(f"Backup → {res['backup']}", icon="💾")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Reset failed: {e}")
                st.caption("Clears this account's calendar / KPIs / evaluation AND "
                           "its 'Realized fills' trades — removing both the fills "
                           "(executions) and the matching scored journal rows from "
                           "every instrument. Originals are copied to _reset_backups "
                           "first, so it's reversible.")

    # ---- HOME: one-glance overview (Edgewonk-style) — fits a screen, no scroll ----
    elif view == "🏠 Home":
        # Live auto-refresh while the watch is ON — reloads executions/journal so
        # new fills appear without a manual click. Quiet (no refresh) when OFF.
        if ss.get("watch_toggle"):
            @st.fragment(run_every=4)
            def _live_refresh():
                st.rerun()
            _live_refresh()
        k = kpis(ex)
        # Clicking a calendar day sets ?day=… → show that day's journal first.
        # The panel is driven purely by the URL: a day link opens it, and the
        # "Back to month" link inside it navigates back to ?  (clears day) —
        # the SAME anchor mechanism in both directions, so closing is as
        # reliable as opening. (Older code closed via st.query_params.clear(),
        # which newer Streamlit doesn't reliably push to the browser URL.)
        qp_day = st.query_params.get("day")
        if qp_day:
            _day_detail(st, ex, qp_day, u, usym)

        # ── Calendar FIRST: full width, at the very top — drawn even with ZERO
        #    realized fills so the month grid is always visible. Nav + goal +
        #    watch toggle sit on one row below; KPI cards + the evaluation panel
        #    only appear once there are trades to summarise. ──
        dp = daily_pnl(ex)
        if len(dp):
            dp["Day"] = pd.to_datetime(dp["Day"])
            dp["uPnL"] = dp["sum"].apply(u)
        latest = (dp["Day"].dt.to_period("M").max() if len(dp)
                  else pd.Timestamp.today().to_period("M"))
        if not ss.get("f_calmonth"):
            ss["f_calmonth"] = str(latest)
        cur = pd.Period(ss["f_calmonth"], freq="M")
        msel = str(cur)
        mdf = (dp[dp["Day"].dt.to_period("M").astype(str) == msel] if len(dp)
               else pd.DataFrame(columns=["Day", "uPnL", "count", "sum"]))
        month_dollars = float(mdf["sum"].sum()) if len(mdf) else 0.0
        mtot_disp = float(mdf["uPnL"].sum()) if len(mdf) else 0.0
        # (Eval bar now lives in the top account row — computed globally above.)
        st.markdown(calendar_html(mdf, usym.strip() or "$", month=msel,
                                  today=pd.Timestamp.today().date(),
                                  goal_day=goal_day, goal_week=goal_week),
                    unsafe_allow_html=True)

        # Below the calendar: ‹ Month › nav on the left, monthly-goal block on
        # the right — aligned on the same (Monthly goal $…) row. on_click
        # callbacks fire before the rerun body, so the calendar above stays
        # in sync even though the buttons render after it.
        def _shift_month(delta):
            cm = ss.get("f_calmonth")
            if cm:
                ss["f_calmonth"] = str(pd.Period(cm, "M") + delta)

        # Live-watch toggle — does the Control tab's Start/Stop watch without
        # opening ⚙️ Control. Default ON: opening the dashboard auto-starts the
        # watcher so live fills are journaled (and NinjaTrader is gated) without
        # having to remember to flip it. on_change handles later toggles.
        def _start_watch():
            import subprocess
            import sys
            return subprocess.Popen(
                [sys.executable, "-c", "from toai.score import watch; watch()"],
                cwd=str(PROJECT_ROOT))

        def _toggle_watch():
            wp = ss.get("watch_proc")
            alive = wp is not None and wp.poll() is None
            if ss.get("watch_toggle") and not alive:
                ss["watch_proc"] = _start_watch()
            elif not ss.get("watch_toggle") and alive:
                wp.terminate()
                ss["watch_proc"] = None
        ss.setdefault("watch_toggle", True)
        _wp = ss.get("watch_proc")
        _alive = _wp is not None and _wp.poll() is None
        # Auto-start once when the default-ON toggle has no live watcher yet
        # (guarded so it doesn't respawn on every rerun).
        if ss["watch_toggle"] and not _alive and not ss.get("_watch_autostarted"):
            ss["_watch_autostarted"] = True
            ss["watch_proc"] = _start_watch()
            _wp = ss["watch_proc"]
            _alive = True

        # Left column: ‹ Month › nav on top (aligned with Monthly goal), and the
        # live-watch control on ONE line below (aligned with Month total).
        # Right column: the monthly-goal block.
        _sp, navcol, goalcol = st.columns([0.66, 3.4, 5], gap="small",
                                          vertical_alignment="bottom")
        with navcol:
            nc = st.columns([0.55, 1.5, 0.55, 2.4], gap="small", vertical_alignment="center")
            nc[0].button("‹", key="cal_prev", on_click=_shift_month, args=(-1,))
            nc[1].markdown(f"<div class='cal-monthlbl'>{cur.strftime('%B %Y')}</div>",
                           unsafe_allow_html=True)
            nc[2].button("›", key="cal_next", on_click=_shift_month, args=(1,))
            # wc mirrors nc's cumulative widths so the toggle lands under the › arrow.
            wc = st.columns([2.05, 0.55, 2.4], gap="small", vertical_alignment="center")
            wc[0].markdown(
                f"<div class='watch-status'>"
                f"{'🟢 watch running' if _alive else '⚪ watch stopped'}</div>",
                unsafe_allow_html=True)
            wc[1].toggle("watch", key="watch_toggle", label_visibility="collapsed",
                         on_change=_toggle_watch)
        # Collapsible stats: the evaluation bar + KPI cards are hidden by default
        # so the page opens on the journal (calendar) alone. The toggle lives
        # where the eval bar sits (right of the month nav).
        if "home_stats_open" not in ss:
            ss["home_stats_open"] = bool(_ui_prefs.get("home_stats_open", False))

        def _toggle_stats():
            ss["home_stats_open"] = not ss["home_stats_open"]
            _update_prefs(home_stats_open=ss["home_stats_open"])

        with goalcol:
            st.button("▾ Hide stats" if ss["home_stats_open"] else "▸ Show stats",
                      key="home_stats_btn", on_click=_toggle_stats)

        if not ss["home_stats_open"]:
            pass
        elif not k:
            st.info("No realized fills yet — the calendar above is empty. The ML "
                    "edge tab still works on the Walk-forward backtest.")
        else:
            # ── KPI cards + Evaluation panel — only once there are realized trades ──
            ev = evaluation(ex)
            ml_edge = sel = None
            if scored is not None and len(scored):
                _sc = scorecard.scorecard_from_scored(
                    scored, threshold, inst, out_of_sample=oos,
                    realized=(source == "Realized fills"))
                if _sc:
                    ml_edge = _sc.edge_per_trade
                    sel = _sc.selectivity
            cum = (pd.to_numeric(ex["Profit"], errors="coerce").fillna(0)
                   .cumsum().apply(u).tolist())
            payoff = abs(k["avg_win"] / k["avg_loss"]) if k["avg_loss"] else 0.0
            cards = [
                {"label": "Net P&L", "val": f"{u(k['net']):,.2f}{usym}",
                 "visual": _spark_svg(cum, GREEN if k["net"] >= 0 else RED)},
                {"label": "Win rate", "val": f"{k['win_rate']:.0f}%",
                 "visual": _gauge_svg(k["win_rate"]),
                 "sub": (f"<span class='pill win'>{k['n_win']}</span>"
                         f"<span class='pill be'>{k['n_be']}</span>"
                         f"<span class='pill loss'>{k['n_loss']}</span>")},
                {"label": "Avg / trade", "val": f"{u(k['expectancy']):,.2f}{usym}",
                 "visual": _splitbar_svg(k["avg_win"], k["avg_loss"]),
                 "sub": (f"<b style='color:{GREEN}'>{u(k['avg_win']):+.1f}</b> · "
                         f"<b style='color:{RED}'>{u(k['avg_loss']):+.1f}</b> · "
                         f"{payoff:.2f}:1")},
                {"label": "Profit factor",
                 "val": f"{k['profit_factor']:.2f}" if k["profit_factor"] else "—",
                 "visual": _pfbar_svg(k["profit_factor"])},
                {"label": "ML edge / trade",
                 "val": f"{u(ml_edge):+.2f}{usym}" if ml_edge is not None else "—",
                 "visual": _ring_svg(sel, GREEN if (ml_edge or 0) >= 0 else RED)
                 if sel is not None else "",
                 "sub": "ALLOW vs all", "sub_color": GREEN},
            ]
            with st.container(key="kpiwrap"):
                for col, c in zip(st.columns(5, gap="small"), cards):
                    col.markdown(_kpi_card_one(c), unsafe_allow_html=True)


    # ---- TAB 1: ML edge (works for both sources via the scorecard machinery) ----
    elif view == "🎯 ML edge":
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

            # TRUST badge — is the live score reliable? Read from the calibrated
            # model bundle. Old (pre-calibration) bundles lack these fields and
            # simply show nothing.
            if _section("mle_summary", "Summary & trust", "📊"):
                try:
                    import joblib
                    _b = joblib.load(_inst_dir(inst) / "model.pkl")
                except Exception:
                    _b = {}
                _trust = _b.get("trust")
                if _trust:
                    _color = {"good": GREEN, "weak": "#d97706", "uncalibrated": "#d97706",
                              "none": RED, "unknown": "#6b7280"}.get(_trust, "#6b7280")
                    _msg = {"good": "score is reliable",
                            "weak": "small edge — use a soft threshold",
                            "uncalibrated": "ranks ok but the % is off",
                            "none": "out-of-sample ≈ random — the % ≈ base rate",
                            "unknown": "not enough data for walk-forward"}.get(_trust, "")
                    _p = [f"<b style='color:{_color}'>TRUST: {_trust}</b> — {_msg}"]
                    if _b.get("wf_mean") is not None:
                        _p.append(f"WF&nbsp;AUC&nbsp;{_b['wf_mean']:.2f}")
                    if _b.get("calibrated"):
                        _p.append("calibrated&nbsp;✓")
                    if _b.get("wf_ece") is not None:
                        _p.append(f"ECE&nbsp;{_b['wf_ece']:.2f}")
                    _rev = [f for f in (_b.get("features") or [])
                            if f in ("BodyDir_ATR", "ClosePos", "LowerWick_ATR",
                                     "UpperWick_ATR", "DipDepth_ATR")]
                    _p.append("reversion&nbsp;features&nbsp;"
                              + ("ON" if _rev else "OFF"))
                    st.markdown("<div style='font-size:0.85rem;color:#6b7280;"
                                "margin:-4px 0 6px'>" + "&nbsp;·&nbsp;".join(_p)
                                + "</div>", unsafe_allow_html=True)
                    if _trust in ("none", "weak"):
                        st.caption("⚠ The gate adds little or no edge on current data — "
                                   "collect more trades, and re-export bars (OHLC) to "
                                   "enable the candle-shape mean-reversion features, "
                                   "before trusting the score.")

                c1, c2, c3 = st.columns(3)
                c1.metric("ALLOW expectancy", f"${sc.allow.expectancy:+,.2f}",
                          f"{sc.allow.win_rate:.0f}% win")
                c2.metric("Edge per taken trade", f"${sc.edge_per_trade:+,.2f}",
                          "vs trading everything")
                c3.metric("Selectivity", f"{sc.selectivity:.0f}%",
                          f"{sc.allow.n} of {sc.all.n} trades")

            # Expectancy by score bucket — the core ML-separation view.
            if sc.buckets and _section("mle_buckets", "Expectancy by score bucket",
                                       "📶"):
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
            if _section("mle_equity", "Equity — ALLOW only vs trading everything", "📈"):
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
    elif view == "🔬 Breakdowns":
        if ex.empty:
            st.info("No realized fills yet for breakdowns.")
        else:
            exn = ex.copy()
            exn["Profit"] = pd.to_numeric(exn["Profit"], errors="coerce")
            if _section("bd_grid", "P&L breakdowns", "🔬"):
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
            if not eff.empty and _section("bd_exit", "Exit efficiency", "🎯"):
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
    elif view == "📅 Calendar":
        if ex.empty:
            st.info("No realized fills yet for the calendar.")
        else:
            dp = daily_pnl(ex)
            dp["Day"] = pd.to_datetime(dp["Day"])
            dp["uPnL"] = dp["sum"].apply(u)
            # Month calendar heatmap (week rows × weekday cols).
            if _section("cal_heat", "Month heatmap", "📅"):
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
            if s and _section("cal_season", "Seasonality", "🗓"):
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
    elif view == "🥅 Goals":
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
    elif view == "🧪 Simulator":
        if ex.empty or not {"MAE", "MFE"}.issubset(ex.columns):
            st.info("Need realized fills with MAE/MFE to simulate.")
        else:
            pv, tick = contract(inst)
            st.caption("What-if: re-run your real trades under a different fixed "
                       "stop / target (uses each trade's MAE/MFE — no bar history).")
            cc = st.columns(3)
            stop_pts = cc[0].slider("Stop (points)", 0.0, 30.0, 5.0, 0.25)
            target_pts = cc[1].slider("Target (points)", 0.0, 40.0, 10.0, 0.25)
            tie = cc[2].radio("If both hit, assume", ["stop", "target"],
                              horizontal=True,
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

                if _section("sim_equity", "Equity curve", "📈"):
                    sim = sim.sort_values("EntryTime")
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(y=sim["Actual"].apply(u).cumsum(),
                                             name="Actual", line=dict(color=MUTED)))
                    fig.add_trace(go.Scatter(y=sim["Sim"].apply(u).cumsum(),
                                             name="Simulated", line=dict(color=GREEN, width=2)))
                    fig.update_layout(title="Equity — simulated stop/target vs actual",
                                      height=300, margin=dict(t=40),
                                      yaxis_title=usym.strip() or "$")
                    st.plotly_chart(fig, width='stretch')
                    st.caption(f"1 point = ${pv:g} · tie broken as '{tie}'. Trades that hit "
                               "neither level keep their real outcome.")

    # ---- TAB 6: trade explorer (per-trade candles + markers) ----
    elif view == "🕯 Trade explorer":
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
    elif view == "🤖 AI Coach":
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

    # ---- TAB 9: Filters & goals (its own nav view, under AI Coach) ----
    elif view == "🎚 Filters":
        st.subheader("⚙ Filters & goals")
        fc = st.columns([1.2, 1.6, 2.2, 1.4])
        fc[0].selectbox("Instrument", insts, key="f_inst")
        fc[1].radio("Data source", ["Realized fills", "Walk-forward backtest"],
                    key="f_source")
        fc[2].slider("ML gate threshold", 0, 100, key="f_thr")
        fc[3].radio("Display unit", ["$", "points", "ticks"], key="f_unit")
        gc = st.columns(3)
        gc[0].number_input("Daily goal ($)", step=50, key="f_gday")
        gc[1].number_input("Weekly goal ($)", step=100, key="f_gweek")
        gc[2].number_input("Monthly goal ($)", step=250, key="f_gmonth")
        ec = st.columns(3)
        ec[0].number_input("Account size ($)", step=5000, key="f_account_size")
        ec[1].number_input("Profit target ($)", step=250, key="f_profit_target")
        ec[2].number_input("Max trailing DD ($)", step=250, key="f_max_dd")
        # Account type tagging — drives the grouped selector (All Evaluation /
        # All Funded / All Demo). Saved to account_types.json.
        if accounts:
            st.markdown("**Account types** — group accounts for the selector")
            tcols = st.columns(min(len(accounts), 4))
            changed = {}
            for i, a in enumerate(accounts):
                pick = tcols[i % len(tcols)].selectbox(
                    _one_label(a), TYPE_ORDER, index=TYPE_ORDER.index(acct_type[a]),
                    key=f"acctype_{a}")
                if pick != acct_types_saved.get(a):
                    changed[a] = pick
            if changed:
                merged = dict(acct_types_saved)
                merged.update({a: ss[f"acctype_{a}"] for a in accounts})
                try:
                    _types_file.write_text(json.dumps(merged, indent=2),
                                           encoding="utf-8")
                except OSError:
                    pass


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
