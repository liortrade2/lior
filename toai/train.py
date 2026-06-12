"""Train the ML filter and report the PMV (AUC-ROC) score.

Pipeline (research doc §6):
  load training CSV -> target = PnL > 0 -> normalize -> 70/30 split
  -> GridSearchCV over Gradient Boosting -> PMV = AUC-ROC -> save model.pkl
"""
import joblib
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.preprocessing import StandardScaler

from . import config
from .features import MODEL_FEATURES, derive_features

PARAM_GRID = {
    "n_estimators": [100, 200],
    "max_depth": [2, 3, 4],
    "learning_rate": [0.05, 0.1],
}


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
    return df.dropna(subset=features + [config.TARGET_COLUMN])


def train(df: pd.DataFrame | None = None, features=None, verbose: bool = True):
    features = features or MODEL_FEATURES
    if df is None:
        df = load_training_data(features=features)
    if any(f not in df.columns for f in features):
        df = derive_features(df).dropna(subset=features + [config.TARGET_COLUMN])

    X = df[features]
    y = (df[config.TARGET_COLUMN] > 0).astype(int)

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
        GradientBoostingClassifier(random_state=config.RANDOM_STATE),
        PARAM_GRID,
        scoring="roc_auc",
        cv=3,
        n_jobs=-1,
    )
    search.fit(X_train, y_train)
    model = search.best_estimator_

    y_prob = model.predict_proba(X_test)[:, 1]
    pmv = roc_auc_score(y_test, y_prob)
    report = threshold_report(y_test.to_numpy(), y_prob)
    wf_aucs, wf_y, wf_prob = walk_forward(df, features=features)
    # The honest threshold table: built from walk-forward predictions only,
    # where every score was produced by a model that never saw that trade's
    # time period. The random-split table is optimistic (time leakage).
    wf_report = threshold_report(wf_y, wf_prob) if len(wf_y) else None

    config.MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "scaler": scaler, "features": features, "pmv": pmv,
                 "walk_forward": wf_aucs,
                 "threshold_report": report,
                 "wf_threshold_report": wf_report},
                config.MODEL_FILE)

    if verbose:
        print(f"Trades in training set: {len(df)}")
        print(f"Win rate in data:       {y.mean() * 100:.1f}%")
        print(f"Best params:            {search.best_params_}")
        print(f"PMV (AUC-ROC):          {pmv:.4f}")
        if pmv > 0.5:
            print("PMV > 0.5 — the model adds value over random. ✔")
        else:
            print("PMV <= 0.5 — the model does NOT add value yet. Collect more trades.")
        if wf_aucs:
            wf_mean = sum(wf_aucs) / len(wf_aucs)
            folds = "  ".join(f"{a:.3f}" for a in wf_aucs)
            print(f"Walk-forward PMV:       {wf_mean:.4f}  (folds: {folds})")
            if wf_mean > 0.5:
                print("Walk-forward > 0.5 — the edge holds on unseen future data. ✔")
            else:
                print("Walk-forward <= 0.5 — the edge does NOT hold forward in time.")
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
    y = (df[config.TARGET_COLUMN] > 0).astype(int).to_numpy()
    n = len(df)
    fold = n // (n_folds + 1)
    aucs, all_y, all_prob = [], [], []
    for i in range(1, n_folds + 1):
        end = fold * (i + 1) if i < n_folds else n
        X_tr, y_tr = X[:fold * i], y[:fold * i]
        X_te, y_te = X[fold * i:end], y[fold * i:end]
        if len(set(y_tr)) < 2 or len(set(y_te)) < 2:
            continue
        scaler = StandardScaler().fit(X_tr)
        model = GradientBoostingClassifier(
            random_state=config.RANDOM_STATE,
            n_estimators=200, max_depth=3, learning_rate=0.05)
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
