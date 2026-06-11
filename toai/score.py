"""Real-time scoring: read the latest bar features, write ProbOfTrue (0-100).

NinjaScript writes current_features.csv on each bar close and reads score.txt
back to allow/skip the signal (research doc §6, steps 3-4).
"""
import time

import joblib
import pandas as pd

from . import config


def load_model(path=None):
    bundle = joblib.load(path or config.MODEL_FILE)
    return bundle


def score_features(bundle, features_row: pd.DataFrame) -> float:
    """Return ProbOfTrue as a 0-100 score for a single-row DataFrame."""
    X = features_row[bundle["features"]]
    X_scaled = bundle["scaler"].transform(X)
    prob = bundle["model"].predict_proba(X_scaled)[0][1]
    return round(prob * 100, 1)


def score_latest_bar(bundle=None) -> float:
    """Score the last row of current_features.csv and write score.txt."""
    if bundle is None:
        bundle = load_model()
    df = pd.read_csv(config.CURRENT_FEATURES_FILE)
    score = score_features(bundle, df.tail(1))
    config.SCORE_FILE.write_text(str(score))
    return score


def watch(interval_seconds: float = 2.0):
    """Poll current_features.csv and refresh score.txt whenever it changes."""
    bundle = load_model()
    print(f"Watching {config.CURRENT_FEATURES_FILE} (Ctrl+C to stop)")
    print(f"Threshold: {config.MIN_PROBABILITY_THRESHOLD} — trades below are skipped")
    last_mtime = 0.0
    while True:
        try:
            mtime = config.CURRENT_FEATURES_FILE.stat().st_mtime
        except FileNotFoundError:
            time.sleep(interval_seconds)
            continue
        if mtime != last_mtime:
            last_mtime = mtime
            score = score_latest_bar(bundle)
            verdict = "ALLOW" if score >= config.MIN_PROBABILITY_THRESHOLD else "SKIP"
            print(f"ProbOfTrue: {score:5.1f}  ->  {verdict}")
        time.sleep(interval_seconds)
