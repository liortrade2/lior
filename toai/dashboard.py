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
    from . import config, journal, scorecard
except ImportError:
    import pathlib
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from toai import config, journal, scorecard

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
#  Streamlit UI (imports the heavy libs lazily, so the helpers above stay light)
# --------------------------------------------------------------------------- #
def main():
    import streamlit as st
    import plotly.graph_objects as go

    GREEN, RED, MUTED, ACCENT = "#1b8a3a", "#c0392b", "#8a8a8a", "#8e44ad"
    mode = config.MODE_LABEL  # LIVE / PLAYBACK

    st.set_page_config(page_title=f"TOAI Analytics — {mode}", layout="wide")
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

    scored, _thr, oos, dfrom, dto = scored_for(inst, source)
    ex = load_realized(inst)

    # ---- top KPI row (realized) ----
    k = kpis(ex)
    if k:
        cols = st.columns(5)
        cols[0].metric("Trades", k["trades"])
        cols[1].metric("Net P&L", f"${k['net']:,.2f}")
        cols[2].metric("Win rate", f"{k['win_rate']:.0f}%")
        cols[3].metric("Expectancy", f"${k['expectancy']:,.2f}/trade")
        cols[4].metric("Profit factor",
                       f"{k['profit_factor']:.2f}" if k["profit_factor"] else "—")
    else:
        st.info("No realized fills yet — showing the walk-forward view where available.")

    tab_edge, tab_break, tab_explore = st.tabs(
        ["🎯 ML edge", "🔬 Breakdowns", "🕯 Trade explorer"])

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

    # ---- TAB 3: trade explorer (per-trade candles + markers) ----
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
                w = trade_bars(bars, r["EntryTime"], r["ExitTime"])
                fig = go.Figure()
                if has_ohlc:
                    fig.add_trace(go.Candlestick(
                        x=w["DateTime"], open=w["Open"], high=w["High"],
                        low=w["Low"], close=w["Close"], name="price"))
                else:
                    fig.add_trace(go.Scatter(x=w["DateTime"], y=w["EMA20"],
                                             name="EMA20 (no OHLC yet)",
                                             line=dict(color=MUTED)))
                    st.caption("bar_data has no OHLC yet — showing the EMA20 line. "
                               "Recompile TOAIExporterGaugeTick to get real candles.")
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
