"""Real-time scoring: read the latest bar features, write ProbOfTrue (0-100).

NinjaScript writes current_features.csv on each bar close and reads score.txt
back to allow/skip the signal (research doc §6, steps 3-4).
"""
import os
import shutil
import time

import joblib
import pandas as pd

from . import config
from .features import derive_features


def _read_features_with_retry(path, attempts=6, delay=0.04):
    """Read current_features.csv defensively. The NinjaScript exporter
    rewrites it every bar (and a second BloodHound copy may too), so a read
    can hit a momentary lock or a half-written file — retry briefly instead
    of crashing the watch."""
    last = None
    for _ in range(attempts):
        try:
            df = pd.read_csv(path)
            if len(df) and "ATR20" in df.columns:
                return df
        except (PermissionError, OSError, pd.errors.EmptyDataError,
                pd.errors.ParserError) as e:
            last = e
        time.sleep(delay)
    if last:
        raise last
    raise ValueError("current_features.csv empty/partial after retries")


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


def score_latest_bar(bundle=None, score_file=None) -> float:
    """Score the last row of current_features.csv and write it to score_file
    (default score.txt). The score_file override lets the portfolio write a
    separate gate file per strategy (score_<slug>.txt)."""
    if bundle is None:
        bundle = load_model()
    df = _read_features_with_retry(config.CURRENT_FEATURES_FILE)
    score = score_features(bundle, df.tail(1))
    score_file = score_file or config.SCORE_FILE
    # Atomic write (temp + replace) so the NinjaScript reader never sees a
    # half-written file.
    tmp = score_file.with_suffix(".tmp")
    tmp.write_text(str(score))
    os.replace(tmp, score_file)
    return score


def _watch_targets():
    """Instrument folders to poll. The root itself is included as long as a
    legacy current_features.csv lives there (exporter from before the
    multi-instrument layout)."""
    targets = []
    if (config.DATA_ROOT / "current_features.csv").exists():
        targets.append(None)
    targets.extend(config.list_instruments())
    return targets


def watch(interval_seconds: float = 2.0, stop_event=None, reload_event=None,
          switch_queue=None):
    """Poll every instrument's current_features.csv and refresh its
    score.txt whenever it changes — one watch window serves all charts
    (C:\\LIOR_ML\\ES, C:\\LIOR_ML\\NQ, ...).

    stop_event / reload_event (threading.Event, optional) let the control
    panel run this in a background thread: set stop_event to end the loop,
    set reload_event after switching a variant so the next tick reloads the
    affected model.

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

    # Exports present at startup are treated as already processed (a restart
    # doesn't retrain). Only NEW or re-saved exports retrain — and ALL of
    # them, across every instrument, not just the newest.
    from .build_and_train import all_trades_exports, build_and_train
    trained = {str(p): p.stat().st_mtime for p in all_trades_exports()}

    print(f"Watching {config.DATA_ROOT} — one folder per instrument (Ctrl+C to stop)")
    print(f"Threshold: {config.get_threshold()} — trades below are skipped "
          f"(from {config.THRESHOLD_FILE.name}, shared by all instruments)")
    print(f"Auto-retrain: drop one or more Strategy Analyzer exports into "
          f"{config.DATA_ROOT} — each retrains its instrument by itself.")
    bundles, feat_mtimes, missing_model = {}, {}, set()
    exec_mtimes, bardata_mtimes, live_models = {}, {}, {}
    portfolio_bundles = {}
    from . import journal, variants
    from .merge import consolidate_training_bars, live_timeframe
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        # Variant switches requested by the control panel — performed here
        # because this thread owns the global instrument state.
        if switch_queue is not None:
            while not switch_queue.empty():
                inst, vslug = switch_queue.get()
                config.set_instrument(inst)
                try:
                    if variants.select_variant(vslug):
                        bundles.clear()
                        missing_model.clear()
                        portfolio_bundles.clear()
                        print(f"[{inst}] switched to variant {vslug}")
                except Exception as e:
                    print(f"[{inst}] variant switch failed: {e}")
        if reload_event is not None and reload_event.is_set():
            bundles.clear()        # a variant was switched in the panel
            missing_model.clear()
            portfolio_bundles.clear()
            reload_event.clear()
        # Any new / re-saved export? Train each (after a short grace period so
        # we never read a file NinjaTrader is still writing). Routed to the
        # right instrument by its Instrument column inside build_and_train.
        for p in all_trades_exports():
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            key = str(p)
            if mtime <= trained.get(key, 0) + 0.5 or time.time() - mtime <= 5:
                continue
            trained[key] = mtime
            print(f"\nNew trades export detected: {p.name}")
            print("Retraining automatically…\n" + "-" * 46)
            try:
                if build_and_train(trades_file=p):
                    bundles.clear()        # reload models lazily below
                    missing_model.clear()
                    portfolio_bundles.clear()
                    print("-" * 46)
                    print(f"Trained from {p.name}.")
                    # Auto-archive the processed export so it never retrains and
                    # the root stays clean. The variant is permanent — switch
                    # strategies in the panel, no reprocessing. Re-dropping a new
                    # export later trains it again.
                    try:
                        dest = config.DATA_ROOT / "_trained"
                        dest.mkdir(exist_ok=True)
                        shutil.move(str(p), str(dest / p.name))
                        print(f"Archived {p.name} -> _trained/ (won't retrain).")
                    except OSError as e:
                        print(f"(couldn't archive {p.name}: {e})")
                    print("Reload that instrument's chart to refresh labels.\n")
            except Exception as e:
                print(f"Auto-retrain failed for {p.name}: {e}\n")

        for name in _watch_targets():
            config.set_instrument(name)
            # Multi-TF auto-adapt: make model.pkl the active variant for the
            # chart's CURRENT timeframe (read live from bar_data_tf.txt). When
            # you switch the chart's TF — or pick a different strategy in the
            # panel — the live model follows, no restart needed.
            try:
                from .merge import live_timeframe
                from . import variants
                ltf = live_timeframe(config.DATA_DIR)
                tslug, _ = variants.active_variant_for_tf(ltf, config.DATA_DIR)
                if tslug is None:
                    tslug, _ = variants.active_variant(config.DATA_DIR)
                if tslug is not None and tslug != live_models.get(name):
                    variants.sync_live_model(rescore=True)
                    live_models[name] = tslug
                    bundles.pop(name, None)
                    portfolio_bundles.clear()
                    missing_model.discard(name)
                    print(f"[{name or 'root'}] live model -> {tslug} ({ltf}min)")
            except Exception:
                pass
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
            try:
                score = score_latest_bar(bundles[name])
            except Exception as e:
                # A persistent file lock shouldn't kill the watch — skip this
                # tick and try again on the next one.
                print(f"[{name or 'root'}] score skipped (file busy): {e}")
                continue
            # Re-read each time so a threshold change in the panel applies
            # immediately, without restarting the watch.
            threshold = config.get_threshold()
            verdict = "ALLOW" if score >= threshold else "SKIP"
            label = f"[{name}] " if name else ""
            print(f"{label}ProbOfTrue: {score:5.1f}  ->  {verdict}  (min {threshold:g})")

            # Portfolio: also score each portfolio strategy with its OWN model
            # -> <inst>/score_<slug>.txt, so several BloodHound strategies can
            # run together, each gated independently. A portfolio.txt manifest
            # maps each file to its strategy (paste the file name into that
            # strategy's TOAIExporter ScoreFileName).
            try:
                ltf2 = live_timeframe(config.DATA_DIR)
                pf = [(s, i) for s, i in variants.portfolio_variants(config.DATA_DIR)
                      if i.get("timeframe") == ltf2]
                manifest = []
                for s, info in pf:
                    pb = portfolio_bundles.get((name, s))
                    if pb is None:
                        pb = load_model(config.DATA_DIR / "models" / f"{s}.pkl")
                        portfolio_bundles[(name, s)] = pb
                    psc = score_latest_bar(pb, score_file=config.DATA_DIR / f"score_{s}.txt")
                    manifest.append(f"score_{s}.txt\t{info.get('name', '')}\t{psc}")
                if pf:
                    (config.DATA_DIR / "portfolio.txt").write_text(
                        "file\tstrategy\tlast_score\n" + "\n".join(manifest))
            except Exception as e:
                print(f"[{name or 'root'}] portfolio score skipped: {e}")

        # Realized side of the loop: when live fills land in <inst>/executions.csv
        # (appended by NinjaTrader / the executions logger), record each against
        # the score the gate gave it. Deduped, so re-reads are free.
        for name in _watch_targets():
            config.set_instrument(name)
            # Grow the frozen training history as live bars arrive, so loading
            # 5 days for daily trading never loses the full history needed to
            # retrain. Light pass (no archive re-scan).
            try:
                bmt = config.BAR_DATA_FILE.stat().st_mtime
                if bmt != bardata_mtimes.get(name):
                    bardata_mtimes[name] = bmt
                    consolidate_training_bars(config.DATA_DIR, include_archives=False)
            except OSError:
                pass
            ep = config.DATA_DIR / "executions.csv"
            try:
                emt = ep.stat().st_mtime
            except OSError:
                continue
            if emt == exec_mtimes.get(name) or time.time() - emt <= 5:
                continue
            exec_mtimes[name] = emt
            try:
                added = journal.record_export(ep, source="live",
                                              inst_dir=config.MODEL_FILE.parent)
                if added:
                    print(f"[{name or 'root'}] journal: +{added} live fills logged")
            except Exception as e:
                print(f"[{name or 'root'}] journal (live) skipped: {e}")
        time.sleep(interval_seconds)
