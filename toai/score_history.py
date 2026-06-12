"""Precompute a score for every bar in bar_data.csv -> bar_scores.csv.

NinjaScript (TOAIExporter / TOAISignalLabel) loads bar_scores.csv when the
chart loads, so scores and SKIP labels appear retroactively on historical
bars and during Playback (Market Replay) — not only on live bars.

Re-run after every training (build_and_train does it automatically) and
whenever the chart exported new history into bar_data.csv.
"""
import os
import time

import pandas as pd

from . import config
from .features import derive_features
from .score import load_model


def _compact_bar_data(deduped: pd.DataFrame, raw_rows: int):
    """Rewrite bar_data.csv without the duplicate rows that chart reloads
    append. Skipped while NinjaTrader might still be writing the file."""
    try:
        if time.time() - config.BAR_DATA_FILE.stat().st_mtime < 60:
            return
        tmp = config.BAR_DATA_FILE.with_suffix(".tmp")
        deduped.to_csv(tmp, index=False)
        os.replace(tmp, config.BAR_DATA_FILE)
        print(f"Compacted {config.BAR_DATA_FILE.name}: "
              f"{raw_rows} -> {len(deduped)} rows")
    except OSError:
        pass


def score_history(verbose: bool = True) -> pd.DataFrame:
    bundle = load_model()
    df = pd.read_csv(config.BAR_DATA_FILE)
    raw_rows = len(df)

    # The chart re-exports its history on every load, so bar_data.csv
    # accumulates duplicate rows — keep the newest row per bar.
    df = df.drop_duplicates(subset="DateTime", keep="last").sort_values("DateTime")
    if len(df) < raw_rows:
        _compact_bar_data(df, raw_rows)

    df = derive_features(df)
    df = df.dropna(subset=bundle["features"])

    # Score only bars inside the strategy's entry window (when known).
    # Outside it the strategy never trades and the model never saw data —
    # a badge there would be a guess, not a prediction.
    window = bundle.get("entry_window")
    if window:
        df = df[df["TimeOfDay_Min"].between(*window)]

    X = bundle["scaler"].transform(df[bundle["features"]])
    probs = bundle["model"].predict_proba(X)[:, 1] * 100

    out = pd.DataFrame({"DateTime": df["DateTime"], "Score": probs.round(1)})
    out.to_csv(config.BAR_SCORES_FILE, index=False)
    if verbose:
        print(f"Scored {len(out)} bars -> {config.BAR_SCORES_FILE}")
        print("Reload the chart so NinjaTrader picks up the new scores.")
    return out


if __name__ == "__main__":
    score_history()
