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

PARAM_GRID = {
    "n_estimators": [100, 200],
    "max_depth": [2, 3, 4],
    "learning_rate": [0.05, 0.1],
}


def load_training_data(path=None, features=None) -> pd.DataFrame:
    path = path or config.TRAINING_FILE
    features = features or config.FEATURES
    df = pd.read_csv(path)
    missing = [c for c in features + [config.TARGET_COLUMN] if c not in df.columns]
    if missing:
        raise ValueError(f"Training file {path} is missing columns: {missing}")
    return df.dropna(subset=features + [config.TARGET_COLUMN])


def train(df: pd.DataFrame | None = None, features=None, verbose: bool = True):
    features = features or config.FEATURES
    if df is None:
        df = load_training_data(features=features)

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

    config.MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "scaler": scaler, "features": features, "pmv": pmv,
                 "threshold_report": report},
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
        print()
        print(format_threshold_report(report, baseline=y.mean() * 100))
        print(f"Model saved to:         {config.MODEL_FILE}")

    return model, scaler, pmv


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


def format_threshold_report(report, baseline=None):
    lines = ["Threshold analysis (on the held-out test set):",
             "  Thresh | Trades kept | Win rate"]
    for r in report:
        lines.append(f"    {r['threshold']:>3}  |  {r['trades_kept']:>4} / {r['total']:<4} |  {r['win_rate']:5.1f}%")
    if baseline is not None:
        lines.append(f"  Baseline (no filter): {baseline:.1f}% win rate")
    return "\n".join(lines)
