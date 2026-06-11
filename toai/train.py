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


def load_training_data(path=None) -> pd.DataFrame:
    path = path or config.TRAINING_FILE
    df = pd.read_csv(path)
    missing = [c for c in config.FEATURES + [config.TARGET_COLUMN] if c not in df.columns]
    if missing:
        raise ValueError(f"Training file {path} is missing columns: {missing}")
    return df.dropna(subset=config.FEATURES + [config.TARGET_COLUMN])


def train(df: pd.DataFrame | None = None, verbose: bool = True):
    if df is None:
        df = load_training_data()

    X = df[config.FEATURES]
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

    config.MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "scaler": scaler, "features": config.FEATURES, "pmv": pmv},
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
        print(f"Model saved to:         {config.MODEL_FILE}")

    return model, scaler, pmv
