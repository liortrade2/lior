"""Derived, scale-free model features.

The NinjaScript exporter writes RAW columns (config.FEATURES) — among them
EMA9/EMA20/EMA50 as absolute price levels. Absolute levels are
non-stationary twice over: the market drifts across a year of history, and
NinjaTrader's MergeBackAdjusted rollover shifts the WHOLE back-adjusted
series every quarter. A model trained on them ends up scoring "price is
higher than anything I saw in training" instead of trade quality.

Training and scoring therefore run on DERIVED features that are relative
and scale-free. Derivation happens here, in one place, at train/score
time — the CSV contract with NinjaScript stays untouched, and existing
bar_data.csv / training_data.csv files work as-is.
"""
import numpy as np
import pandas as pd

# The features the model actually trains on.
MODEL_FEATURES = [
    "ATR_Pct",          # ATR20 as % of price — volatility level, scale-free
    "EMA9_vs_EMA20",    # (EMA9 - EMA20) / ATR20 — short-term trend, ATR units
    "EMA20_vs_EMA50",   # (EMA20 - EMA50) / ATR20 — medium-term trend, ATR units
    "RSI14",            # already 0-100
    "ADX14",            # already 0-100
    "SwingHigh_ATR",    # Distance_SwingHigh / ATR20 — room above, ATR units
    "SwingLow_ATR",     # Distance_SwingLow / ATR20 — room below, ATR units
    "Volume_Ratio",     # already a ratio
    "BB_Width_ATR",     # BBand_Width / ATR20 — band width vs true range
    "ZScore",           # already standardized
    "TimeOfDay_Min",    # minutes since midnight in the chart clock, which
                        # NinjaTrader already exports as true US Eastern
                        # (DST-aware). Late entries get truncated by the
                        # session-close exit and win rate falls with entry
                        # hour, so the model gets the entry time directly.
    # ── Candle-shape features for MEAN REVERSION: a reversion entry is taken as
    #    a falling move EXHAUSTS and the bar turns back up. These let the model
    #    see that turn directly, instead of only the dip. Derived from the OHLC
    #    the exporter already writes (live + bar_data), so no NinjaScript change.
    "BodyDir_ATR",      # (Close-Open)/ATR — signed body; >0 = bar closed up (the
                        #   reversal); the core "bar changed direction" signal.
    "ClosePos",         # (Close-Low)/(High-Low) — 0=closed on low, 1=on high.
    "LowerWick_ATR",    # (min(O,C)-Low)/ATR — long lower wick = lows rejected.
    "UpperWick_ATR",    # (High-max(O,C))/ATR — long upper wick = highs rejected.
    "DipDepth_ATR",     # (EMA20-Close)/ATR — how far below the mean (dip depth).
]


def _session_minutes(ts: pd.Series) -> pd.Series:
    """Minutes since midnight in the chart's clock — no timezone math.

    NinjaTrader already exports DST-aware US Eastern timestamps. Verified
    on 2679 MES backtest entries: RTH entries sit at 09:42-16:00 in BOTH
    winter and summer, with no seasonal flip. So the raw stamp clock is
    the session clock; an earlier UTC-5->Eastern conversion (based on an
    apparent flip in a smaller, messier sample) only added a spurious
    one-hour summer shift and has been removed.
    """
    return ts.dt.hour * 60 + ts.dt.minute


def derive_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add the MODEL_FEATURES columns, derived from the raw exporter columns.

    Raw columns are kept alongside, so a model bundle trained on the old
    raw feature names still finds its columns and keeps scoring.
    """
    df = df.copy()
    if "DateTime" in df.columns:
        t = pd.to_datetime(df["DateTime"], errors="coerce")
        df["TimeOfDay_Min"] = _session_minutes(t)
    else:
        now = pd.Series([pd.Timestamp.now()])
        df["TimeOfDay_Min"] = float(_session_minutes(now).iloc[0])
    atr = df["ATR20"].replace(0, np.nan)
    df["ATR_Pct"] = df["ATR20"] / df["EMA20"].replace(0, np.nan) * 100
    df["EMA9_vs_EMA20"] = (df["EMA9"] - df["EMA20"]) / atr
    df["EMA20_vs_EMA50"] = (df["EMA20"] - df["EMA50"]) / atr
    df["SwingHigh_ATR"] = df["Distance_SwingHigh"] / atr
    df["SwingLow_ATR"] = df["Distance_SwingLow"] / atr
    df["BB_Width_ATR"] = df["BBand_Width"] / atr

    # Candle-shape (mean-reversion) features — computed when the OHLC columns the
    # exporter writes are present; otherwise left NaN so old data still loads and
    # the dropna in training simply ignores rows that lack them.
    ohlc = ("Open", "High", "Low", "Close")
    if all(c in df.columns for c in ohlc):
        o, h, l, c = (df["Open"], df["High"], df["Low"], df["Close"])
        rng = (h - l).replace(0, np.nan)
        body_lo = pd.concat([o, c], axis=1).min(axis=1)
        body_hi = pd.concat([o, c], axis=1).max(axis=1)
        df["BodyDir_ATR"] = (c - o) / atr
        df["ClosePos"] = (c - l) / rng
        df["LowerWick_ATR"] = (body_lo - l) / atr
        df["UpperWick_ATR"] = (h - body_hi) / atr
        df["DipDepth_ATR"] = (df["EMA20"] - c) / atr
    else:
        for col in ("BodyDir_ATR", "ClosePos", "LowerWick_ATR",
                    "UpperWick_ATR", "DipDepth_ATR"):
            df[col] = np.nan
    return df
