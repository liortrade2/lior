"""Real-time scoring: read the latest bar features, write ProbOfTrue (0-100).

NinjaScript writes current_features.csv on each bar close and reads score.txt
back to allow/skip the signal (research doc §6, steps 3-4).
"""
import time

import joblib
import pandas as pd

from . import config
from .features import derive_features


def load_model(path=None):
    bundle = joblib.load(path or config.MODEL_FILE)
    return bundle


def score_features(bundle, features_row: pd.DataFrame) -> float:
    """Return ProbOfTrue as a 0-100 score for a single-row DataFrame."""
    # The exporter writes raw columns; the model expects the derived,
    # scale-free features (raw columns are kept, so old bundles work too).
    features_row = derive_features(features_row)
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


def _watch_targets():
    """Instrument folders to poll. The root itself is included as long as a
    legacy current_features.csv lives there (exporter from before the
    multi-instrument layout)."""
    targets = []
    if (config.DATA_ROOT / "current_features.csv").exists():
        targets.append(None)
    targets.extend(config.list_instruments())
    return targets


def watch(interval_seconds: float = 2.0):
    """Poll every instrument's current_features.csv and refresh its
    score.txt whenever it changes — one watch window serves all charts
    (C:\\LIOR_ML\\ES, C:\\LIOR_ML\\NQ, ...).

    Also watches for NEW Strategy Analyzer exports dropped into the data
    ROOT: saving an export retrains the right instrument automatically —
    no extra clicks, and old exports don't need to be deleted (newest wins).
    """
    # Refresh bar_scores.csv on startup so a chart (re)load shows scores
    # retroactively and in Playback. Skipped quietly where data is missing.
    from .score_history import score_history
    for name in _watch_targets():
        config.set_instrument(name)
        try:
            score_history()
        except FileNotFoundError:
            pass

    # Exports that already exist don't retrigger training — only new ones.
    _, last_export_mtime = _newest_export()

    print(f"Watching {config.DATA_ROOT} — one folder per instrument (Ctrl+C to stop)")
    print(f"Threshold: {config.get_threshold()} — trades below are skipped "
          f"(from {config.THRESHOLD_FILE.name}, shared by all instruments)")
    print(f"Auto-retrain: save a new Strategy Analyzer export into "
          f"{config.DATA_ROOT} and the right instrument retrains by itself.")
    bundles, feat_mtimes, missing_model = {}, {}, set()
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
                    bundles.clear()        # reload models lazily below
                    missing_model.clear()
                    print("-" * 46)
                    print("Model reloaded — live scores now use the NEW model.")
                    print("Reload the chart to refresh the historical labels.\n")
            except Exception as e:
                print(f"Auto-retrain failed: {e}\n")

        for name in _watch_targets():
            config.set_instrument(name)
            try:
                mtime = config.CURRENT_FEATURES_FILE.stat().st_mtime
            except FileNotFoundError:
                continue
            if mtime == feat_mtimes.get(name):
                continue
            feat_mtimes[name] = mtime
            if name not in bundles:
                try:
                    bundles[name] = load_model()
                except FileNotFoundError:
                    if name not in missing_model:
                        missing_model.add(name)
                        print(f"[{name or 'root'}] no model.pkl yet — save a "
                              "Strategy Analyzer export to train it.")
                    continue
            score = score_latest_bar(bundles[name])
            # Re-read each time so a threshold change in the panel applies
            # immediately, without restarting the watch.
            threshold = config.get_threshold()
            verdict = "ALLOW" if score >= threshold else "SKIP"
            label = f"[{name}] " if name else ""
            print(f"{label}ProbOfTrue: {score:5.1f}  ->  {verdict}  (min {threshold:g})")
        time.sleep(interval_seconds)
