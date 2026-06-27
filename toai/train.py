"""Train the ML filter and report the PMV (AUC-ROC) score.

Pipeline (research doc §6):
  load training CSV -> target = PnL > 0 -> normalize -> 70/30 split
  -> GridSearchCV over Gradient Boosting -> PMV = AUC-ROC -> save model.pkl
"""
import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.preprocessing import StandardScaler

# LightGBM is the primary estimator (best-in-class on tabular); fall back to
# sklearn's GradientBoosting if it isn't installed, so training never breaks.
try:
    from lightgbm import LGBMClassifier

    def _make_estimator(**kw):
        return LGBMClassifier(random_state=config.RANDOM_STATE, verbosity=-1,
                              min_child_samples=5, **kw)
    _ESTIMATOR = "lightgbm"
except ImportError:                       # pragma: no cover
    from sklearn.ensemble import GradientBoostingClassifier

    def _make_estimator(**kw):
        return GradientBoostingClassifier(random_state=config.RANDOM_STATE, **kw)
    _ESTIMATOR = "gradient_boosting"


def _ece(y_true, y_prob, bins: int = 10) -> float:
    """Expected Calibration Error: average |predicted prob − actual win rate|
    across probability bins. 0 = perfectly calibrated; lower is better."""
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    if len(y_true) == 0:
        return float("nan")
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(y_prob, edges[1:-1]), 0, bins - 1)
    err = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            err += m.mean() * abs(y_prob[m].mean() - y_true[m].mean())
    return float(err)


def _trust(wf_mean: float | None, ece: float | None) -> str:
    """One-word verdict on whether the live score can be trusted, from the
    out-of-sample edge (walk-forward AUC) and calibration error."""
    if wf_mean is None:
        return "unknown"
    if wf_mean < 0.52:
        return "none"          # ranking ≈ random — score is noise
    if wf_mean < 0.55:
        return "weak"
    if ece is not None and ece > 0.12:
        return "uncalibrated"  # ranks ok but the % is off
    return "good"

from . import config
from .features import MODEL_FEATURES, derive_features
from .label import meta_label

PARAM_GRID = {
    "n_estimators": [100, 200],
    "max_depth": [2, 3, 4],
    "learning_rate": [0.05, 0.1],
}


def usable_features(df: pd.DataFrame, features=None, min_coverage: float = 0.8):
    """The subset of `features` the data can actually supply. The candle-shape
    (mean-reversion) features need OHLC, which older bar-history lacks — so they
    are dropped until enough OHLC-rich bars accumulate, then switch on by
    themselves. Keeps the pipeline working on any data, old or new."""
    features = features or MODEL_FEATURES
    return [f for f in features
            if f in df.columns and df[f].notna().mean() >= min_coverage]


def load_training_data(path=None, features=None) -> pd.DataFrame:
    path = path or config.TRAINING_FILE
    features = features or MODEL_FEATURES
    df = pd.read_csv(path)
    # The file holds the RAW exporter columns; the model features are
    # derived from them (relative/scale-free — see features.py).
    missing = [c for c in config.FEATURES + [config.TARGET_COLUMN] if c not in df.columns]
    if missing:
        raise ValueError(f"Training file {path} is missing columns: {missing}")
    df = derive_features(df)
    feats = usable_features(df, features)
    return df.dropna(subset=feats + [config.TARGET_COLUMN])


def train(df: pd.DataFrame | None = None, features=None, verbose: bool = True):
    features = features or MODEL_FEATURES
    if df is None:
        df = load_training_data(features=features)
    elif any(f not in df.columns for f in features):
        df = derive_features(df)
    # Adaptive feature set: train only on features the data populates (see
    # usable_features). The candle-shape features activate automatically once
    # OHLC-rich bar history exists; until then the model uses the base set.
    features = usable_features(df, features)
    df = df.dropna(subset=features + [config.TARGET_COLUMN])

    X = df[features]
    # Triple-barrier meta-label (take/win vs skip/loss) when the trade carries
    # MAE/MFE + Stop/Take; otherwise PnL>0 (label.meta_label handles both).
    y = meta_label(df)

    if y.nunique() < 2:
        raise ValueError("Training data needs both winning and losing trades.")

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y,
        test_size=config.TEST_SIZE,
        random_state=config.RANDOM_STATE,
        stratify=y,
    )

    search = GridSearchCV(
        _make_estimator(),
        PARAM_GRID,
        scoring="roc_auc",
        cv=3,
        n_jobs=-1,
    )
    search.fit(X_train, y_train)
    raw = search.best_estimator_
    raw_prob = raw.predict_proba(X_test)[:, 1]

    # Calibrate the probabilities so the live score reflects the TRUE win rate
    # instead of the model's raw, extreme-leaning output (the "18% that won"
    # problem). Platt/sigmoid is the robust choice on small samples; isotonic
    # overfits. AUC is unchanged by this monotonic mapping — only the % moves.
    model = CalibratedClassifierCV(
        _make_estimator(**search.best_params_), method="sigmoid", cv=3)
    model.fit(X_train, y_train)

    # SHAP feature attributions (on the uncalibrated tree model) — the "why" the
    # cockpit shows. Best-effort; never block training if shap is unavailable.
    shap_top = None
    try:
        import shap
        sv = shap.TreeExplainer(raw).shap_values(X_train)
        if isinstance(sv, list):                 # some shap versions: [class0, class1]
            sv = sv[-1]
        sv = np.asarray(sv)
        imp = np.abs(sv).mean(axis=0)
        signed = sv.mean(axis=0)
        order = np.argsort(imp)[::-1]
        shap_top = [(features[i], float(signed[i])) for i in order[:8]]
    except Exception:
        shap_top = None

    y_prob = model.predict_proba(X_test)[:, 1]
    pmv = roc_auc_score(y_test, y_prob)
    brier_raw = float(brier_score_loss(y_test, raw_prob))
    brier_cal = float(brier_score_loss(y_test, y_prob))
    report = threshold_report(y_test.to_numpy(), y_prob)
    wf_aucs, wf_y, wf_prob = walk_forward(df, features=features)
    wf_mean = (sum(wf_aucs) / len(wf_aucs)) if wf_aucs else None
    wf_ece = _ece(wf_y, wf_prob) if len(wf_y) else None
    trust = _trust(wf_mean, wf_ece)
    # The honest threshold table: built from walk-forward predictions only,
    # where every score was produced by a model that never saw that trade's
    # time period. The random-split table is optimistic (time leakage).
    wf_report = threshold_report(wf_y, wf_prob) if len(wf_y) else None

    # The strategy only enters during a time window (all training entries
    # fall inside it). Outside that window the model has never seen a trade
    # and its score is extrapolation — score_history skips those bars so the
    # chart shows no misleading badge there. Padded by one bar.
    entry_window = None
    if "TimeOfDay_Min" in df.columns:
        tod = df["TimeOfDay_Min"].dropna()
        if len(tod):
            entry_window = (float(tod.min()) - 15, float(tod.max()) + 15)

    config.MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "scaler": scaler, "features": features, "pmv": pmv,
                 "walk_forward": wf_aucs,
                 "threshold_report": report,
                 "wf_threshold_report": wf_report,
                 "entry_window": entry_window,
                 "calibrated": True, "brier_raw": brier_raw, "brier_cal": brier_cal,
                 "wf_mean": wf_mean, "wf_ece": wf_ece, "trust": trust,
                 "estimator": _ESTIMATOR, "shap_top": shap_top,
                 "label": "triple_barrier"},
                config.MODEL_FILE)
    # NinjaScript reads the window too (banner + gate outside it).
    # entry_window_manual.txt, when present, overrides the auto window.
    config.write_entry_window(config.resolve_entry_window(entry_window))

    # On-chart HUD mode label — auto from this model's features, unless a
    # mode_manual.txt override is set (write_mode handles both).
    try:
        from .score import write_mode
        write_mode({"features": features})
    except Exception:
        pass

    if verbose:
        _rev = [f for f in features if f in ("BodyDir_ATR", "ClosePos",
                "LowerWick_ATR", "UpperWick_ATR", "DipDepth_ATR")]
        print(f"Trades in training set: {len(df)}")
        print(f"Win rate in data:       {y.mean() * 100:.1f}%")
        print(f"Features used:          {len(features)}  "
              + (f"(candle-shape/mean-reversion ON: {len(_rev)})" if _rev
                 else "(candle-shape OFF — needs OHLC-rich bar history; "
                      "re-export bars to enable)"))
        print(f"Best params:            {search.best_params_}")
        print(f"PMV (AUC-ROC):          {pmv:.4f}")
        if pmv > 0.5:
            print("PMV > 0.5 — the model adds value over random. ✔")
        else:
            print("PMV <= 0.5 — the model does NOT add value yet. Collect more trades.")
        if wf_aucs:
            folds = "  ".join(f"{a:.3f}" for a in wf_aucs)
            print(f"Walk-forward PMV:       {wf_mean:.4f}  (folds: {folds})")
            if wf_mean > 0.5:
                print("Walk-forward > 0.5 — the edge holds on unseen future data. ✔")
            else:
                print("Walk-forward <= 0.5 — the edge does NOT hold forward in time.")
        # Calibration: the score is now a Platt-calibrated probability, so e.g.
        # "40" means ~40% of such trades won historically. Lower Brier = better.
        print(f"Brier (raw -> calibrated): {brier_raw:.4f} -> {brier_cal:.4f}"
              + ("  ✔ improved" if brier_cal <= brier_raw else "  (no gain)"))
        if wf_ece is not None:
            print(f"Calibration error (ECE):   {wf_ece:.3f}  (lower is better)")
        verdict = {
            "good": "TRUST: good — the score ranks AND its % is reliable. ✔",
            "weak": "TRUST: weak — small out-of-sample edge; use a soft threshold.",
            "uncalibrated": "TRUST: ranks ok but the % is off — needs more data.",
            "none": "TRUST: none — out-of-sample ranking ≈ random. The % is just the "
                    "base rate; collect more trades / add reversion features before "
                    "trusting the gate.",
            "unknown": "TRUST: unknown — not enough data for walk-forward.",
        }.get(trust, trust)
        print(verdict)
        print()
        if wf_report:
            print(format_threshold_report(
                wf_report, baseline=float(wf_y.mean()) * 100,
                title="Threshold analysis (walk-forward — use THIS to pick the threshold):"))
            print()
        print(format_threshold_report(
            report, baseline=y.mean() * 100,
            title="Threshold analysis (random test set — optimistic, for reference only):"))
        print(f"Model saved to:         {config.MODEL_FILE}")

    return model, scaler, pmv


def walk_forward(df, features=None, n_folds=4):
    """Chronological walk-forward validation: train only on the past,
    test on the next unseen window — the honest version of PMV.

    Returns (aucs, y_true, y_prob): one AUC per fold plus the pooled
    out-of-fold predictions (empty when there is too little data).
    """
    import numpy as np
    features = features or MODEL_FEATURES
    empty = ([], np.array([]), np.array([]))
    if len(df) < 150:
        return empty
    if "DateTime" in df.columns:
        df = df.sort_values("DateTime")
    X = df[features].to_numpy()
    y = meta_label(df).to_numpy()
    n = len(df)
    fold = n // (n_folds + 1)
    # Purge/embargo: drop a small gap of samples between the train end and the
    # test start so adjacent-in-time trades can't leak (CPCV-lite).
    embargo = max(1, int(round(n * 0.01)))
    aucs, all_y, all_prob = [], [], []
    for i in range(1, n_folds + 1):
        end = fold * (i + 1) if i < n_folds else n
        X_tr, y_tr = X[:max(0, fold * i - embargo)], y[:max(0, fold * i - embargo)]
        X_te, y_te = X[fold * i:end], y[fold * i:end]
        if len(set(y_tr)) < 2 or len(set(y_te)) < 2:
            continue
        scaler = StandardScaler().fit(X_tr)
        model = _make_estimator(n_estimators=200, max_depth=3, learning_rate=0.05)
        model.fit(scaler.transform(X_tr), y_tr)
        prob = model.predict_proba(scaler.transform(X_te))[:, 1]
        aucs.append(float(roc_auc_score(y_te, prob)))
        all_y.append(y_te)
        all_prob.append(prob)
    if not aucs:
        return empty
    return aucs, np.concatenate(all_y), np.concatenate(all_prob)


def threshold_report(y_true, y_prob, thresholds=(50, 55, 60, 65, 70)):
    """For each candidate threshold: how many test trades pass, and their win rate.

    This is how the passing score is chosen — pick the threshold where the
    filtered win rate clearly beats the unfiltered baseline while keeping
    enough trades per day.
    """
    rows = []
    scores = y_prob * 100
    for t in thresholds:
        mask = scores >= t
        kept = int(mask.sum())
        win_rate = float(y_true[mask].mean() * 100) if kept else 0.0
        rows.append({"threshold": t, "trades_kept": kept,
                     "total": len(y_true), "win_rate": win_rate})
    return rows


def format_threshold_report(report, baseline=None, title=None):
    if title is None:
        title = "Threshold analysis (on the held-out test set):"
    lines = [title, "  Thresh | Trades kept | Win rate"]
    for r in report:
        lines.append(f"    {r['threshold']:>3}  |  {r['trades_kept']:>4} / {r['total']:<4} |  {r['win_rate']:5.1f}%")
    if baseline is not None:
        lines.append(f"  Baseline (no filter): {baseline:.1f}% win rate")
    return "\n".join(lines)
