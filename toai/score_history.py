"""Precompute a score for every bar in bar_data.csv -> bar_scores.csv.

NinjaScript (TOAIExporter / TOAISignalLabel) loads bar_scores.csv when the
chart loads, so scores and SKIP labels appear retroactively on historical
bars and during Playback (Market Replay) — not only on live bars.

Re-run after every training (build_and_train does it automatically) and
whenever the chart exported new history into bar_data.csv.
"""
import pandas as pd

from . import config
from .score import load_model


def score_history(verbose: bool = True) -> pd.DataFrame:
    bundle = load_model()
    df = pd.read_csv(config.BAR_DATA_FILE)

    # The chart re-exports its history on every load, so bar_data.csv
    # accumulates duplicate rows — keep the newest row per bar.
    df = df.drop_duplicates(subset="DateTime", keep="last")
    df = df.dropna(subset=bundle["features"]).sort_values("DateTime")

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
