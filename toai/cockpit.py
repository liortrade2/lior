"""TOAI Cockpit — one screen, one button.

Drop a NinjaTrader Strategy-Analyzer trades export into C:\\LIOR_ML and make sure
a chart wrote bar_data.csv (with OHLC) over the same history, then press ONE
button: the cockpit builds the meta-labeling model end-to-end and shows a single
verdict — does it have real out-of-sample edge, and should you go live.

Pure front door: it reuses the proven engine (build_and_train / train / merge /
features / variants / scorecard / the score bridge). The full multi-tab dashboard
stays available via TOAI_Analytics_App.bat.
"""


def main():
    import joblib
    import pandas as pd
    import streamlit as st
    import plotly.graph_objects as go
    import plotly.io as pio

    try:
        from . import config, scorecard, variants
        from .dashboard import (THEME_CSS, _register_plotly_theme, _inst_dir,
                                instruments, scored_for)
        from .build_and_train import build_and_train, find_trades_export
    except ImportError:
        import pathlib
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from toai import config, scorecard, variants
        from toai.dashboard import (THEME_CSS, _register_plotly_theme, _inst_dir,
                                    instruments, scored_for)
        from toai.build_and_train import build_and_train, find_trades_export

    GREEN, RED, MUTED = "#16a34a", "#ef4444", "#6b7280"
    mode = config.MODE_LABEL
    st.set_page_config(page_title=f"TOAI Cockpit — {mode}", layout="wide")
    _register_plotly_theme(go, pio)
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    st.markdown(
        "<style>.block-container{padding-top:14px;max-width:1000px;}"
        ".ck-card{background:#fff;border:1px solid #eceef1;border-radius:14px;"
        "padding:16px 18px;box-shadow:0 1px 3px rgba(16,24,40,.06);margin:8px 0;}"
        ".ck-kpis{display:flex;gap:10px;}.ck-kpis>div{flex:1;background:#fff;"
        "border:1px solid #eceef1;border-radius:10px;padding:9px 13px;}"
        ".ck-kpis span{color:#6b7280;font-size:.72rem;font-weight:600;display:block;}"
        ".ck-kpis b{font-size:1.5rem;font-weight:800;}"
        ".st-key-buildbtn button{height:60px;font-size:1.15rem;font-weight:800;}"
        "</style>", unsafe_allow_html=True)
    ss = st.session_state

    st.markdown(f"<h1>🚀 TOAI Cockpit <span style='font-size:.9rem;color:{MUTED};"
                f"font-weight:600'>· {mode}</span></h1>", unsafe_allow_html=True)

    # ── Instrument + inputs status ─────────────────────────────────────────
    insts = instruments()
    if not insts:
        st.info("No instrument data yet. Add TOAIExporterGaugeTick to a chart "
                "(ExportBarData=true) and run the strategy in the Strategy Analyzer, "
                "then export the Trades tab into C:\\LIOR_ML.")
        return
    top = st.columns([2, 5])
    inst = (insts[0] if len(insts) == 1
            else top[0].selectbox("Instrument", insts, key="ck_inst"))
    if len(insts) == 1:
        top[0].markdown(f"**Instrument:** {inst}")
    d = _inst_dir(inst)
    config.set_instrument(inst)

    exp = find_trades_export()
    bar = d / "bar_data.csv"
    ohlc_pct = None
    if bar.exists():
        try:
            _b = pd.read_csv(bar, usecols=lambda c: c in ("Close",))
            ohlc_pct = (_b["Close"].notna().mean() * 100) if "Close" in _b else 0.0
        except (ValueError, OSError):
            ohlc_pct = 0.0

    def _row(ok, label):
        return f"{'✅' if ok else '⚠️'} {label}"
    top[1].markdown(
        _row(exp is not None,
             f"Trades export: **{exp.name}**" if exp else
             "No trades export found in C:\\LIOR_ML — export the Strategy "
             "Analyzer Trades tab.") + "  \n"
        + _row(bar.exists(), f"Bar data: **{bar.name}**" if bar.exists()
               else "No bar_data.csv — add the exporter to a chart.") + "  \n"
        + _row((ohlc_pct or 0) >= 50,
               f"OHLC coverage: **{ohlc_pct:.0f}%** "
               + ("(candle-shape features ON)" if (ohlc_pct or 0) >= 50
                  else "— re-export bar history with OHLC to unlock the "
                       "mean-reversion features")))

    # ── THE button ─────────────────────────────────────────────────────────
    bcol = st.columns([3, 2])
    incl_live = bcol[1].checkbox("Also learn from live fills (Sim101 + funded)",
                                 key="ck_live", value=False)
    if bcol[0].button("🚀  Build TOAI", type="primary", width="stretch",
                      key="buildbtn", disabled=exp is None):
        with st.spinner("Merging trades → bar features, labeling, training, "
                        "validating out-of-sample…"):
            try:
                ok = build_and_train(trades_file=exp, include_live=incl_live)
                ss["ck_built"] = bool(ok)
                ss["ck_err"] = None
            except Exception as e:       # noqa: BLE001 — surface any build error
                ss["ck_built"] = False
                ss["ck_err"] = str(e)
        st.rerun()
    if ss.get("ck_err"):
        st.error(f"Build failed: {ss['ck_err']}")

    # ── Verdict card ───────────────────────────────────────────────────────
    model_file = d / "model.pkl"
    if not model_file.exists():
        st.caption("Press **Build TOAI** to train a model and see the verdict.")
        return
    try:
        b = joblib.load(model_file)
    except Exception:
        st.warning("Could not read the model bundle.")
        return

    trust = b.get("trust") or "unknown"
    tcol = {"good": GREEN, "weak": "#d97706", "uncalibrated": "#d97706",
            "none": RED, "unknown": MUTED}.get(trust, MUTED)
    tmsg = {"good": "score is reliable — safe to gate live",
            "weak": "small edge — use a soft threshold",
            "uncalibrated": "ranks ok but the % is off",
            "none": "out-of-sample ≈ random — NO real edge yet",
            "unknown": "not enough data for walk-forward"}.get(trust, "")
    wf = b.get("wf_mean")
    feats = b.get("features") or []
    rev_on = any(f in ("BodyDir_ATR", "ClosePos", "LowerWick_ATR",
                       "UpperWick_ATR", "DipDepth_ATR") for f in feats)

    # Edge per trade + n, from the walk-forward backtest scorecard.
    edge = n_tr = None
    scored, _thr, oos, _df, _dt = scored_for(inst, "Walk-forward backtest")
    thr_live = config.get_threshold(d)
    if scored is not None and len(scored):
        sc = scorecard.scorecard_from_scored(scored, thr_live, inst,
                                             out_of_sample=oos)
        if sc:
            edge, n_tr = sc.edge_per_trade, sc.n_trades

    st.markdown(
        f"<div class='ck-card'><div style='font-size:1.2rem;font-weight:800;"
        f"color:{tcol}'>TRUST: {trust.upper()}</div>"
        f"<div style='color:{MUTED};margin-top:2px'>{tmsg}</div></div>",
        unsafe_allow_html=True)

    k = st.columns(4)
    k[0].metric("Out-of-sample AUC", f"{wf:.2f}" if wf is not None else "—",
                "purged walk-forward")
    k[1].metric("Edge / trade", f"${edge:+,.2f}" if edge is not None else "—",
                "ALLOW vs all")
    k[2].metric("Trades", f"{n_tr}" if n_tr is not None else "—")
    k[3].metric("Reversion features", "ON" if rev_on else "OFF",
                f"{len(feats)} features")

    # SHAP top drivers (present once train.py stores them; graceful if absent).
    shap_top = b.get("shap_top")
    if shap_top:
        chips = " · ".join(f"{name} ({imp:+.2f})" for name, imp in shap_top[:6])
        st.caption(f"**Why it scores this way (SHAP):** {chips}")

    # Strategy vs TOAI — the money the gate adds/saves on the backtest.
    if scored is not None and len(scored):
        try:
            all_eq, allow_eq = scorecard.equity_curves(scored, thr_live)
        except Exception:
            all_eq = allow_eq = None
        if all_eq is not None and len(all_eq):
            diff = float(allow_eq[-1] - all_eq[-1])
            fig = go.Figure()
            fig.add_trace(go.Scatter(y=all_eq, name="Strategy · all signals",
                                     line=dict(color=MUTED, width=2)))
            fig.add_trace(go.Scatter(
                y=allow_eq, name="TOAI · ALLOW only",
                line=dict(color=GREEN, width=2.5), fill="tonexty",
                fillcolor=("rgba(22,163,74,.12)" if diff >= 0
                           else "rgba(239,68,68,.10)")))
            fig.add_hline(y=0, line_color="#e5e7eb")
            fig.update_layout(title="Strategy vs TOAI — cumulative $ (backtest)",
                              height=260, margin=dict(t=36),
                              yaxis_title="cumulative $", xaxis_title="signal #",
                              legend=dict(orientation="h", y=1.0))
            st.plotly_chart(fig, width="stretch")
            st.caption(f"The gate {'added' if diff >= 0 else 'cost'} "
                       f"**{diff:+,.0f}$** vs taking every signal.")

    # ── Go live: threshold + activate ──────────────────────────────────────
    st.markdown("#### Go live")
    gc = st.columns([5, 1.6])
    ss.setdefault("ck_thr", int(thr_live))
    thr_val = gc[0].slider("Gate threshold — min ML score to ALLOW", 0, 100,
                           key="ck_thr")
    if gc[1].button("✅ Apply to chart", width="stretch", key="ck_apply"):
        config.set_threshold(float(thr_val), d)
        st.toast(f"Threshold {thr_val:g} pushed to the chart.", icon="✅")
    if int(thr_val) != int(thr_live):
        st.caption(f"● Pending — chart still on {int(thr_live)}. Click Apply.")

    # Activate the freshly built variant as the live model.
    reg = variants._load_registry(d)
    if reg:
        active = next((s for s, v in reg.items() if v.get("active")), None)
        slugs = list(reg)
        pick = st.selectbox(
            "Live model", slugs,
            index=slugs.index(active) if active in slugs else 0,
            format_func=lambda s: ("● " if s == active else "")
            + f"{reg[s].get('name', s)} · {reg[s].get('saved', '?')}",
            key="ck_variant")
        if st.button("Activate as live model", key="ck_activate"):
            variants.select_variant(pick, d, rescore=True)
            st.success(f"Activated {reg[pick].get('name', pick)} — model.pkl is "
                       "now this variant. Reload the chart.")

    st.caption("Full dashboard (calendar, simulator, breakdowns, AI Coach) is "
               "still available via TOAI_Analytics_App.bat.")


if __name__ == "__main__":
    main()
