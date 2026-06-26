"""Expectancy objective (roadmap Tier 1 #1) — train on money, not win/loss.

The live model targets PnL>0, so a +$50 win and a +$2 win are the same label,
and a -$3 loss and a -$50 loss are the same label. The scorecard showed why that
leaves money on the table: R:R ≈ 0.68 (wins smaller than losses), so the edge
rides on frequency, not magnitude. Weighting each training sample by |PnL| turns
the win/loss classifier into an expectancy model — it learns to dodge the costly
losses and favour the fat wins.

This module PROVES it before anything goes live: it runs the same honest
walk-forward twice on the same trades — once plain (win-rate objective), once
weighted by |PnL| (expectancy objective) — and reports the out-of-sample dollar
edge of each. Only if the weighted objective wins do we operationalize it.
"""
from datetime import datetime

import joblib
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from . import config, scorecard, variants
from .features import MODEL_FEATURES, derive_features


def objective_scorecards(instrument, threshold=None):
    """(win_rate_scorecard, expectancy_scorecard) for an instrument — same
    trades, same folds, only the training objective differs. Either is None if
    there isn't enough data."""
    tf = scorecard.training_file_for(instrument)
    inst_dir = config.DATA_ROOT / instrument if instrument else config.DATA_ROOT
    threshold = config.get_threshold(inst_dir) if threshold is None else threshold
    base = scorecard.compute_scorecard(tf, threshold, instrument, weight_by_pnl=False)
    exp = scorecard.compute_scorecard(tf, threshold, instrument, weight_by_pnl=True)
    return base, exp


def _line(tag, sc):
    if sc is None:
        return f"  {tag:<11}: (not enough data)"
    a = sc.allow
    pf = f"{a.profit_factor:.2f}" if a.profit_factor else "  -"
    return (f"  {tag:<11}: ALLOW {a.n:>4} | win {a.win_rate:4.0f}% | "
            f"exp {a.expectancy:+6.2f}$ | PF {pf} | "
            f"edge {sc.edge_per_trade:+.2f}$ | total {a.total_pnl:+,.0f}$")


def format_comparison(instrument, base, exp) -> str:
    head = instrument or "root"
    lines = [
        "=" * 70,
        f"  OBJECTIVE COMPARISON — {head}   (out-of-sample, same trades)",
        "=" * 70,
        _line("win-rate", base),
        _line("expectancy", exp),
        "",
    ]
    if base and exp:
        d_edge = exp.edge_per_trade - base.edge_per_trade
        d_exp = exp.allow.expectancy - base.allow.expectancy
        d_total = exp.allow.total_pnl - base.allow.total_pnl
        verdict = ("EXPECTANCY WINS" if d_exp > 0 else
                   "no improvement — keep win-rate")
        lines += [
            f"  Δ ALLOW expectancy: {d_exp:+.2f}$/trade   "
            f"Δ edge: {d_edge:+.2f}$   Δ total: {d_total:+,.0f}$",
            f"  -> {verdict}",
        ]
    lines.append("=" * 70)
    return "\n".join(lines)


def compare(instrument, threshold=None) -> str:
    base, exp = objective_scorecards(instrument, threshold)
    return format_comparison(instrument, base, exp)


# --------------------------------------------------------------------------- #
#  Operationalize — train the expectancy model and save it as a variant
# --------------------------------------------------------------------------- #
def _entry_window(df, inst_dir):
    """Reuse the live model's entry window (same trades, same window); else
    derive it from the trades' time-of-day, padded a bar."""
    try:
        b = joblib.load(inst_dir / "model.pkl")
        if b.get("entry_window"):
            return b["entry_window"]
    except Exception:
        pass
    if "TimeOfDay_Min" in df.columns:
        tod = df["TimeOfDay_Min"].dropna()
        if len(tod):
            return (float(tod.min()) - 15, float(tod.max()) + 15)
    return None


def train_expectancy(instrument=None, source_trades=None, base_name=None,
                     timeframe=None):
    """Train a |PnL|-weighted (expectancy) model on the instrument's trades and
    save it as an INACTIVE variant '<base> [expectancy]' — the live model.pkl is
    untouched, so you compare it (⚖) and activate only if it wins.

    source_trades: optional DataFrame (DateTime, Direction, raw features, PnL).
    Defaults to the instrument's training_data.csv."""
    inst_dir = config.DATA_ROOT / instrument if instrument else config.DATA_ROOT
    if source_trades is None:
        source_trades = pd.read_csv(inst_dir / "training_data.csv")
    raw = source_trades.copy()

    from .train import usable_features
    d = derive_features(raw)
    feats = usable_features(d)
    d = d.dropna(subset=feats + [config.TARGET_COLUMN])
    if len(d) < 150:
        raise ValueError(f"need 150+ trades to train, have {len(d)}")
    X = d[feats].to_numpy()
    pnl = d[config.TARGET_COLUMN].to_numpy(dtype=float)
    y = (pnl > 0).astype(int)
    if len(set(y)) < 2:
        raise ValueError("training data needs both winning and losing trades")

    w = scorecard.pnl_weights(pnl)
    scaler = StandardScaler().fit(X)
    model = GradientBoostingClassifier(
        random_state=config.RANDOM_STATE,
        n_estimators=200, max_depth=3, learning_rate=0.05)
    model.fit(scaler.transform(X), y, sample_weight=w)
    pmv = float(roc_auc_score(y, model.predict_proba(scaler.transform(X))[:, 1]))

    # Honest (out-of-fold) pooled AUC for the variant card.
    wf = None
    oof = scorecard.walk_forward_scores(d, features=feats, weight_by_pnl=True)
    if oof is not None:
        yy = (oof["PnL"].to_numpy() > 0).astype(int)
        if len(set(yy)) > 1:
            wf = [round(float(roc_auc_score(yy, oof["Score"].to_numpy())), 3)]

    bundle = {"model": model, "scaler": scaler, "features": feats,
              "pmv": round(pmv, 4), "walk_forward": wf,
              "threshold_report": None, "wf_threshold_report": None,
              "entry_window": _entry_window(d, inst_dir), "weight_by_pnl": True}

    if base_name is None or timeframe is None:
        _, ainfo = variants.active_variant(inst_dir)
        ainfo = ainfo or {}
        if base_name is None:
            base_name = ainfo.get("name", "model")
        if timeframe is None:
            timeframe = ainfo.get("timeframe")
    name = f"{base_name} [expectancy]"
    # Distinct slug: variants.slug() truncates to 60 chars, which would clip the
    # "[expectancy]" suffix and collide with the base variant's slug — so build
    # an explicit, collision-proof key.
    slug = variants.slug(base_name)[:45].rstrip("_") + "_EXP"

    models_dir = inst_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, models_dir / f"{slug}.pkl")
    # Snapshot the trades (raw columns) so the comparison can score this variant
    # on its own data.
    cols = ["DateTime", "Direction"] + config.FEATURES + [config.TARGET_COLUMN]
    raw[[c for c in cols if c in raw.columns]].to_csv(
        models_dir / f"{slug}_training.csv", index=False)

    reg = variants._load_registry(inst_dir)
    reg[slug] = {
        "name": name,
        "saved": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pmv": round(pmv, 4),
        "wf_mean": round(sum(wf) / len(wf), 4) if wf else None,
        "wf": wf,
        "timeframe": timeframe,
        "active": False,
        "weight_by_pnl": True,
    }
    variants._save_registry(reg, inst_dir)
    return slug


if __name__ == "__main__":
    for inst in (config.list_instruments() or [None]):
        print(compare(inst))
        print()
