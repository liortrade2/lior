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
]


def derive_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add the MODEL_FEATURES columns, derived from the raw exporter columns.

    Raw columns are kept alongside, so a model bundle trained on the old
    raw feature names still finds its columns and keeps scoring.
    """
    df = df.copy()
    atr = df["ATR20"].replace(0, np.nan)
    df["ATR_Pct"] = df["ATR20"] / df["EMA20"].replace(0, np.nan) * 100
    df["EMA9_vs_EMA20"] = (df["EMA9"] - df["EMA20"]) / atr
    df["EMA20_vs_EMA50"] = (df["EMA20"] - df["EMA50"]) / atr
    df["SwingHigh_ATR"] = df["Distance_SwingHigh"] / atr
    df["SwingLow_ATR"] = df["Distance_SwingLow"] / atr
    df["BB_Width_ATR"] = df["BBand_Width"] / atr
    return df
