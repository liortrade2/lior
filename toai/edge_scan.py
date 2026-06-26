"""Edge scan — run the 3-condition edge test across every candidate dataset.

The test for a real ML edge (PROJECT_STATUS §"המבחן ל-edge אמיתי"):
  1. Walk-forward AUC > 0.55  (the model RANKS unseen trades)
  2. win% rises with the score (monotone across score buckets)
  3. ALLOW equity beats "trade everything" (the filter makes money out-of-sample)

This loops over every *_training.csv it is given and prints a ranked table,
so we can see empirically whether ANY available strategy/TF clears the bar.
Pure read-only diagnostic — touches no model.pkl, no variants, no live files.

Run:  python -m toai.edge_scan  [glob ...]
"""
import sys
import glob
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from . import config
from .features import MODEL_FEATURES, derive_features


def walk_forward_oof(df, features, n_folds=4):
    """Chronological walk-forward — same split as train.walk_forward, but the
    pooled out-of-fold frame carries PnL too, so we can price the ALLOW edge."""
    features = list(features)
    if "DateTime" in df.columns:
        df = df.sort_values("DateTime").reset_index(drop=True)
    X = df[features].to_numpy()
    y = (df[config.TARGET_COLUMN] > 0).astype(int).to_numpy()
    pnl = df[config.TARGET_COLUMN].to_numpy()
    n = len(df)
    fold = n // (n_folds + 1)
    if fold == 0:
        return [], pd.DataFrame()
    aucs, rows = [], []
    for i in range(1, n_folds + 1):
        end = fold * (i + 1) if i < n_folds else n
        X_tr, y_tr = X[:fold * i], y[:fold * i]
        X_te, y_te = X[fold * i:end], y[fold * i:end]
        if len(set(y_tr)) < 2 or len(set(y_te)) < 2 or len(X_te) == 0:
            continue
        scaler = StandardScaler().fit(X_tr)
        model = GradientBoostingClassifier(
            random_state=config.RANDOM_STATE,
            n_estimators=200, max_depth=3, learning_rate=0.05)
        model.fit(scaler.transform(X_tr), y_tr)
        prob = model.predict_proba(scaler.transform(X_te))[:, 1]
        aucs.append(float(roc_auc_score(y_te, prob)))
        rows.append(pd.DataFrame({"prob": prob, "y": y_te,
                                  "pnl": pnl[fold * i:end]}))
    if not rows:
        return [], pd.DataFrame()
    return aucs, pd.concat(rows, ignore_index=True)


def monotonicity(oof, n_bins=4):
    """Win% per score-quartile (out-of-fold). Returns (bin_winrates, spearman)
    where spearman>0 means higher score -> higher win%."""
    if len(oof) < n_bins * 4:
        return [], float("nan")
    q = pd.qcut(oof["prob"].rank(method="first"), n_bins, labels=False)
    wr = oof.groupby(q)["y"].mean().to_numpy() * 100
    idx = np.arange(len(wr))
    sp = np.corrcoef(idx, wr)[0, 1] if len(wr) > 1 else float("nan")
    return wr.tolist(), float(sp)


def allow_edge(oof, threshold):
    """ALLOW = score>=threshold. Edge = ALLOW avg PnL - trade-everything avg PnL."""
    scores = oof["prob"] * 100
    allow = oof[scores >= threshold]
    everything = oof["pnl"].mean()
    if len(allow) == 0:
        return None
    return {
        "threshold": threshold,
        "allow_n": len(allow), "total_n": len(oof),
        "allow_winrate": allow["y"].mean() * 100,
        "allow_avg_pnl": allow["pnl"].mean(),
        "everything_avg_pnl": everything,
        "edge": allow["pnl"].mean() - everything,
        "selectivity": len(allow) / len(oof) * 100,
    }


def best_allow_edge(oof, thresholds=range(50, 81, 5)):
    best = None
    for t in thresholds:
        e = allow_edge(oof, t)
        if e is None or e["allow_n"] < max(10, len(oof) * 0.1):
            continue
        if best is None or e["edge"] > best["edge"]:
            best = e
    return best


def scan_file(path):
    df = pd.read_csv(path)
    need = config.FEATURES + [config.TARGET_COLUMN]
    if any(c not in df.columns for c in need):
        return {"path": path, "error": "missing columns"}
    from .train import usable_features
    df = derive_features(df)
    feats = usable_features(df)
    df = df.dropna(subset=feats + [config.TARGET_COLUMN])
    if len(df) < 150:
        return {"path": path, "error": f"too few rows ({len(df)})"}
    aucs, oof = walk_forward_oof(df, feats)
    if not aucs:
        return {"path": path, "error": "no valid folds"}
    wf_mean = float(np.mean(aucs))
    wr, sp = monotonicity(oof)
    best = best_allow_edge(oof)
    raw_win = (df[config.TARGET_COLUMN] > 0).mean() * 100
    raw_pnl = df[config.TARGET_COLUMN].mean()
    return {
        "path": path, "n": len(df), "wf_mean": wf_mean, "wf": aucs,
        "bins": wr, "spearman": sp, "best": best,
        "raw_win": raw_win, "raw_pnl": raw_pnl,
    }


def verdict(r):
    """3 conditions: WF>0.55, spearman>0, ALLOW edge>0."""
    if "error" in r:
        return "—"
    c1 = r["wf_mean"] > 0.55
    c2 = r.get("spearman", 0) > 0.10
    c3 = r["best"] is not None and r["best"]["edge"] > 0
    n = sum([c1, c2, c3])
    mark = lambda c: "OK " if c else "no "
    return f"WF:{mark(c1)} mono:{mark(c2)} $edge:{mark(c3)} ({n}/3)"


def main(argv):
    patterns = argv or [str(config.DATA_DIR / "MES" / "models" / "*_training.csv")]
    files = []
    for p in patterns:
        files.extend(sorted(glob.glob(p)))
    if not files:
        print("No files matched.")
        return
    results = [scan_file(f) for f in files]
    results.sort(key=lambda r: r.get("wf_mean", -1), reverse=True)

    print("=" * 100)
    print("EDGE SCAN - 3-condition test (WF>0.55 | win% rises with score | ALLOW beats trade-everything)")
    print("=" * 100)
    for r in results:
        name = r["path"].split("\\")[-1].replace("_training.csv", "")
        if "error" in r:
            print(f"\n{name}\n   SKIP: {r['error']}")
            continue
        print(f"\n{name}   [{r['n']} trades, raw win {r['raw_win']:.1f}% / {r['raw_pnl']:+.2f}$]")
        folds = " ".join(f"{a:.3f}" for a in r["wf"])
        print(f"   1) WF-AUC      : {r['wf_mean']:.3f}   (folds {folds})")
        bins = " -> ".join(f"{w:.0f}%" for w in r["bins"]) if r["bins"] else "n/a"
        print(f"   2) win% by Q   : {bins}   (spearman {r['spearman']:+.2f})")
        if r["best"]:
            b = r["best"]
            print(f"   3) ALLOW@{b['threshold']:>2}    : {b['allow_winrate']:.0f}% win / {b['allow_avg_pnl']:+.2f}$ "
                  f"vs all {b['everything_avg_pnl']:+.2f}$  -> edge {b['edge']:+.2f}$/trade "
                  f"(keeps {b['selectivity']:.0f}%)")
        else:
            print("   3) ALLOW       : no threshold keeps enough trades")
        print(f"   VERDICT        : {verdict(r)}")
    print("\n" + "=" * 100)
    print("Legend: 3/3 = real ML edge (build a variant). Mixed = partial. 0/3 = no edge (trade raw or drop).")


if __name__ == "__main__":
    main(sys.argv[1:])
