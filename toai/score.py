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


def _newest_export():
    """Newest Strategy Analyzer export in the data dir (path, mtime)."""
    from .build_and_train import find_trades_export
    try:
        p = find_trades_export()
        return (p, p.stat().st_mtime) if p else (None, 0.0)
    except Exception:
        return (None, 0.0)


def watch(interval_seconds: float = 2.0):
    """Poll current_features.csv and refresh score.txt whenever it changes.

    Also watches for NEW Strategy Analyzer exports dropped into the data
    dir: saving an export retrains the model automatically — no extra
    clicks, and old exports don't need to be deleted (newest wins).
    """
    bundle = load_model()

    # Refresh bar_scores.csv on startup so a chart (re)load shows scores
    # retroactively and in Playback. Skipped quietly if bar data is missing.
    try:
        from .score_history import score_history
        score_history()
    except FileNotFoundError:
        print(f"(no {config.BAR_DATA_FILE.name} yet — historical scores skipped)")

    # Exports that already exist don't retrigger training — only new ones.
    _, last_export_mtime = _newest_export()

    print(f"Watching {config.CURRENT_FEATURES_FILE} (Ctrl+C to stop)")
    print(f"Threshold: {config.get_threshold()} — trades below are skipped "
          f"(from {config.THRESHOLD_FILE.name})")
    print(f"Auto-retrain: save a new Strategy Analyzer export into "
          f"{config.DATA_DIR} and the model retrains by itself.")
    last_mtime = 0.0
    while True:
        # New backtest export? Retrain automatically (after a short grace
        # period so we never read a file NinjaTrader is still writing).
        export_path, export_mtime = _newest_export()
        if (export_path is not None and export_mtime > last_export_mtime
                and time.time() - export_mtime > 5):
            last_export_mtime = export_mtime
            print(f"\nNew trades export detected: {export_path.name}")
            print("Retraining automatically…\n" + "-" * 46)
            try:
                from .build_and_train import build_and_train
                if build_and_train():
                    bundle = load_model()
                    print("-" * 46)
                    print("Model reloaded — live scores now use the NEW model.")
                    print("Reload the chart to refresh the historical labels.\n")
            except Exception as e:
                print(f"Auto-retrain failed: {e}\n")

        try:
            mtime = config.CURRENT_FEATURES_FILE.stat().st_mtime
        except FileNotFoundError:
            time.sleep(interval_seconds)
            continue
        if mtime != last_mtime:
            last_mtime = mtime
            score = score_latest_bar(bundle)
            # Re-read each time so a threshold change in the panel applies
            # immediately, without restarting the watch.
            threshold = config.get_threshold()
            verdict = "ALLOW" if score >= threshold else "SKIP"
            print(f"ProbOfTrue: {score:5.1f}  ->  {verdict}  (min {threshold:g})")
        time.sleep(interval_seconds)
