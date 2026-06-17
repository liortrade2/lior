"""Build the real training file from NinjaTrader exports.

Inputs:
  1. Trades CSV — Strategy Analyzer > Trades tab > right-click > Export
     (works with the default NinjaTrader grid columns)
  2. bar_data.csv — written by TOAIExporter with ExportBarData = true
     (one row per bar: DateTime + the 11 features)

Each trade's entry time is matched to the most recent closed bar, so the
features are exactly what the model would have seen at the entry decision.
Output: training_data.csv ready for training.
"""
import re

import pandas as pd

from . import config


def _money(value):
    """Parse NinjaTrader currency strings: '$1,020.00', '($242.50)' -> -242.5"""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    negative = (s.startswith("(") and s.endswith(")")) or s.startswith("-")
    s = re.sub(r"[^\d.]", "", s)
    if not s:
        return float("nan")
    return -float(s) if negative else float(s)


def _find_col(columns, *required_words, exclude=()):
    for col in columns:
        lc = col.lower()
        if all(w in lc for w in required_words) and not any(x in lc for x in exclude):
            return col
    return None


def match_trades(trades_path, bar_data_path=None, tolerance_minutes: int = 30):
    """Match each trade's entry to the most recent closed bar and return the
    feature rows + PnL — WITHOUT writing any file. Shared by merge_backtest
    (which trains) and the journal (which logs realized fills). Returns
    (out_df, n_trades, n_unmatched)."""
    bar_data_path = bar_data_path or config.BAR_DATA_FILE

    trades = pd.read_csv(trades_path)
    entry_time_col = _find_col(trades.columns, "entry", "time")
    profit_col = _find_col(trades.columns, "profit", exclude=("cum",))
    direction_col = (_find_col(trades.columns, "market", "pos")
                     or _find_col(trades.columns, "direction"))
    if entry_time_col is None or profit_col is None:
        raise ValueError(
            f"Could not find entry-time/profit columns in {trades_path}. "
            f"Columns found: {list(trades.columns)}")

    trades["EntryTime"] = pd.to_datetime(trades[entry_time_col])
    trades["PnL"] = trades[profit_col].map(_money)
    trades["Direction"] = trades[direction_col] if direction_col else ""
    trades = trades.dropna(subset=["EntryTime", "PnL"])

    bars = pd.read_csv(bar_data_path)
    # errors="coerce" + dropna: a half-written final row (the live exporter may
    # be mid-append) parses to NaT and is dropped instead of crashing.
    bars["DateTime"] = pd.to_datetime(bars["DateTime"], errors="coerce")
    bars = bars.dropna(subset=["DateTime"])
    # Chart reloads append duplicate bars — keep the latest row per bar.
    bars = (bars.drop_duplicates(subset="DateTime", keep="last")
                .sort_values("DateTime"))

    merged = pd.merge_asof(
        trades.sort_values("EntryTime"),
        bars,
        left_on="EntryTime",
        right_on="DateTime",
        direction="backward",
        tolerance=pd.Timedelta(minutes=tolerance_minutes),
    )

    matched = merged.dropna(subset=config.FEATURES)
    unmatched = len(merged) - len(matched)

    out = matched[["EntryTime", "Direction"] + config.FEATURES + ["PnL"]].copy()
    out = out.rename(columns={"EntryTime": "DateTime"})
    return out, len(trades), unmatched


def timeframe_minutes(bar_data_path=None):
    """Infer the bar_data timeframe (minutes) from the median gap between bars —
    so the pipeline can detect whether it's a 1-min, 5-min, 15-min… export and
    warn on a mismatch instead of silently training on the wrong timeframe."""
    bar_data_path = bar_data_path or config.BAR_DATA_FILE
    try:
        d = pd.to_datetime(pd.read_csv(bar_data_path, usecols=["DateTime"])["DateTime"],
                           errors="coerce").dropna().sort_values()
    except (OSError, ValueError, KeyError):
        return None
    if len(d) < 3:
        return None
    gaps = d.diff().dropna().dt.total_seconds() / 60
    gaps = gaps[gaps > 0]
    return float(gaps.median()) if len(gaps) else None


def merge_backtest(trades_path, bar_data_path=None, output_path=None,
                   tolerance_minutes: int = 30, verbose: bool = True):
    output_path = output_path or config.TRAINING_FILE

    out, n_trades, unmatched = match_trades(trades_path, bar_data_path,
                                            tolerance_minutes)
    # Never overwrite a good training_data.csv with an empty one. Zero matches
    # almost always means the chart's bar_data doesn't cover the backtest
    # period (or is the wrong timeframe) — writing the empty result is what
    # wiped training_data on 2026-06-17. Leave the existing file intact.
    if len(out) == 0:
        if verbose:
            print("No trades matched the bar data — training_data.csv left "
                  "UNCHANGED (load chart history that covers the backtest, or "
                  "check the timeframe).")
        return out
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)

    if verbose:
        wins = (out["PnL"] > 0).mean() * 100 if len(out) else 0.0
        print(f"Trades in export:        {n_trades}")
        print(f"Matched to bar data:     {len(out)}")
        if unmatched:
            print(f"Unmatched (no bar within {tolerance_minutes}min): {unmatched}")
        print(f"Win rate:                {wins:.1f}%")
        print(f"Training file written:   {output_path}")
        if len(out) >= 200:
            print("200+ real trades — ready for real training! ✔")
        else:
            print(f"Note: {len(out)} trades < 200 — per the golden rules, "
                  "collect more before trusting the model.")
    return out
