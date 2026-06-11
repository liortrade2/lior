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


def merge_backtest(trades_path, bar_data_path=None, output_path=None,
                   tolerance_minutes: int = 30, verbose: bool = True):
    bar_data_path = bar_data_path or config.BAR_DATA_FILE
    output_path = output_path or config.TRAINING_FILE

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
    bars["DateTime"] = pd.to_datetime(bars["DateTime"])
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
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)

    if verbose:
        wins = (out["PnL"] > 0).mean() * 100
        print(f"Trades in export:        {len(trades)}")
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
