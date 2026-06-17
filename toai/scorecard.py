"""Live Scorecard — does the ML filter actually make money?

The PMV / walk-forward AUC tells us the model *ranks* trades better than
random. It does NOT tell us the dollars. This module answers the question the
roadmap calls "the real validation": for every real trade, score it with a
model that NEVER saw that trade's time period (walk-forward, out-of-fold), then
bucket by score and report win-rate AND expectancy ($/trade) AND R:R — plus the
ALLOW vs SKIP split at the live threshold, which is the actual money the gate
adds or costs.

Why out-of-fold and not the live model.pkl: scoring a trade with the model that
trained on it is in-sample — exactly the inflated number this project bans
(golden rule: "walk-forward only; random-split is inflated"). We mirror
train.walk_forward's fold logic precisely, but carry PnL through instead of
collapsing it to win/loss, so each score sits next to its real dollar outcome.

Data source per instrument: training_data.csv (the merged backtest/Sim trades —
DateTime, Direction, the 11 raw features, PnL). It is rewritten on every train,
so the scorecard always reflects the latest real trades with no extra wiring:
export Sim101 trades -> auto-train -> scorecard updates.

Pure functions, explicit paths — no global config mutation, so the Control
Panel can compute any instrument's scorecard from its UI/worker thread without
fighting the background watch over the shared instrument state.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

from . import config
from .features import MODEL_FEATURES, derive_features

# Fixed score bands so the table is comparable across retrains and instruments.
# The ALLOW/SKIP summary uses the *live* threshold separately, so the bucket
# edges stay stable even when the threshold moves.
BUCKET_EDGES = [0, 50, 60, 70, 80, 90, 100]

# Walk-forward needs enough trades for each fold to have both wins and losses;
# below this we fall back to an in-sample score and flag it loudly.
MIN_OOS_TRADES = 150


@dataclass
class Bucket:
    lo: float
    hi: float
    n: int
    win_rate: float          # %
    expectancy: float        # $ / trade (mean PnL)
    total_pnl: float
    avg_win: float
    avg_loss: float          # negative (or 0 if no losers)
    rr: float | None         # avg_win / |avg_loss|


@dataclass
class Group:
    """A win-rate / expectancy summary over an arbitrary set of trades."""
    label: str
    n: int
    win_rate: float
    expectancy: float
    total_pnl: float
    rr: float | None
    profit_factor: float | None   # gross win / gross loss


@dataclass
class Scorecard:
    instrument: str | None
    n_trades: int
    threshold: float
    out_of_sample: bool      # True = walk-forward (honest); False = in-sample
    date_from: str
    date_to: str
    buckets: list[Bucket]
    all: Group
    allow: Group             # score >= threshold (the gate lets these through)
    skip: Group              # score <  threshold (the gate blocks these)

    @property
    def edge_per_trade(self) -> float:
        """Expectancy lift from filtering: ALLOW expectancy minus the
        no-filter baseline. Positive = the gate makes each taken trade worth
        more than trading everything."""
        return self.allow.expectancy - self.all.expectancy

    @property
    def pnl_avoided(self) -> float:
        """Dollars the gate kept off the table by skipping (negative total =
        the gate dodged a net loss)."""
        return self.skip.total_pnl

    @property
    def selectivity(self) -> float:
        """Share of trades the gate lets through (%). Low = picky filter."""
        return self.allow.n / self.all.n * 100 if self.all.n else 0.0


# --------------------------------------------------------------------------- #
#  Out-of-fold scoring (the honest score for every trade)
# --------------------------------------------------------------------------- #
def walk_forward_scores(df: pd.DataFrame, features=None, n_folds: int = 4):
    """Score every trade out-of-fold: train on the past, score the next unseen
    window. Mirrors train.walk_forward but returns each trade's (Score, PnL)
    instead of a per-fold AUC.

    Returns a DataFrame with columns Score (0-100) and PnL, or None when there
    is too little data for an honest walk-forward.
    """
    features = features or MODEL_FEATURES
    if len(df) < MIN_OOS_TRADES:
        return None
    if "DateTime" in df.columns:
        df = df.sort_values("DateTime")
    X = df[features].to_numpy()
    pnl = df[config.TARGET_COLUMN].to_numpy(dtype=float)
    y = (pnl > 0).astype(int)
    n = len(df)
    fold = n // (n_folds + 1)
    if fold == 0:
        return None

    out_score, out_pnl = [], []
    for i in range(1, n_folds + 1):
        end = fold * (i + 1) if i < n_folds else n
        X_tr, y_tr = X[:fold * i], y[:fold * i]
        X_te, pnl_te = X[fold * i:end], pnl[fold * i:end]
        if len(X_te) == 0 or len(set(y_tr)) < 2:
            continue
        scaler = StandardScaler().fit(X_tr)
        model = GradientBoostingClassifier(
            random_state=config.RANDOM_STATE,
            n_estimators=200, max_depth=3, learning_rate=0.05)
        model.fit(scaler.transform(X_tr), y_tr)
        prob = model.predict_proba(scaler.transform(X_te))[:, 1]
        out_score.append(prob * 100)
        out_pnl.append(pnl_te)

    if not out_score:
        return None
    return pd.DataFrame({"Score": np.concatenate(out_score),
                         "PnL": np.concatenate(out_pnl)})


def _in_sample_scores(df: pd.DataFrame, features=None):
    """Fallback for small datasets: train one model on everything and score
    the same trades. Optimistic (in-sample) — only used when there are too few
    trades for walk-forward, and always flagged out_of_sample=False."""
    features = features or MODEL_FEATURES
    X = df[features].to_numpy()
    pnl = df[config.TARGET_COLUMN].to_numpy(dtype=float)
    y = (pnl > 0).astype(int)
    if len(set(y)) < 2:
        return None
    scaler = StandardScaler().fit(X)
    model = GradientBoostingClassifier(
        random_state=config.RANDOM_STATE,
        n_estimators=200, max_depth=3, learning_rate=0.05)
    model.fit(scaler.transform(X), y)
    prob = model.predict_proba(scaler.transform(X))[:, 1]
    return pd.DataFrame({"Score": prob * 100, "PnL": pnl})


# --------------------------------------------------------------------------- #
#  Aggregation
# --------------------------------------------------------------------------- #
def _stats(pnl: np.ndarray):
    """(win_rate %, expectancy $, total $, avg_win, avg_loss, rr) for a set of
    trade PnLs. A win is PnL > 0; break-even/commission-only counts as a loss."""
    n = len(pnl)
    if n == 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0, None
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    win_rate = len(wins) / n * 100
    expectancy = float(pnl.mean())
    total = float(pnl.sum())
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    rr = (avg_win / abs(avg_loss)) if avg_loss != 0 else None
    return win_rate, expectancy, total, avg_win, avg_loss, rr


def _group(label: str, pnl: np.ndarray) -> Group:
    win_rate, expectancy, total, _, _, rr = _stats(pnl)
    gross_win = float(pnl[pnl > 0].sum())
    gross_loss = float(-pnl[pnl <= 0].sum())
    pf = (gross_win / gross_loss) if gross_loss > 0 else None
    return Group(label, len(pnl), win_rate, expectancy, total, rr, pf)


def _buckets(scored: pd.DataFrame) -> list[Bucket]:
    out = []
    for lo, hi in zip(BUCKET_EDGES[:-1], BUCKET_EDGES[1:]):
        # Right-closed on the final band so a perfect 100 lands somewhere.
        if hi == BUCKET_EDGES[-1]:
            mask = (scored["Score"] >= lo) & (scored["Score"] <= hi)
        else:
            mask = (scored["Score"] >= lo) & (scored["Score"] < hi)
        pnl = scored.loc[mask, "PnL"].to_numpy()
        win_rate, expectancy, total, avg_win, avg_loss, rr = _stats(pnl)
        out.append(Bucket(lo, hi, len(pnl), win_rate, expectancy,
                          total, avg_win, avg_loss, rr))
    return out


@dataclass
class ScoredTrades:
    """The expensive, threshold-independent part: every trade's out-of-fold
    score paired with its PnL. Cached by file mtime so reopening the scorecard
    or moving the threshold is instant — only a fresh retrain reruns it."""
    scored: pd.DataFrame     # columns Score, PnL
    out_of_sample: bool
    date_from: str
    date_to: str


# str(path) -> (mtime, ScoredTrades|None). Walk-forward over thousands of
# trades is a few seconds; the threshold-dependent aggregation below is
# microseconds, so we cache only the scoring and rebuild the rest each call.
_score_cache: dict[str, tuple[float, "ScoredTrades | None"]] = {}


def _score_trades_uncached(training_file) -> ScoredTrades | None:
    try:
        df = pd.read_csv(training_file)
    except (FileNotFoundError, OSError, pd.errors.EmptyDataError):
        return None
    if config.TARGET_COLUMN not in df.columns or df.empty:
        return None

    date_from = date_to = ""
    if "DateTime" in df.columns:
        dt = pd.to_datetime(df["DateTime"], errors="coerce").dropna()
        if len(dt):
            date_from = str(dt.min().date())
            date_to = str(dt.max().date())

    df = derive_features(df).dropna(subset=MODEL_FEATURES + [config.TARGET_COLUMN])
    if len(df) < 30:
        return None

    scored = walk_forward_scores(df)
    out_of_sample = scored is not None
    if scored is None:
        scored = _in_sample_scores(df)
    if scored is None:
        return None
    return ScoredTrades(scored, out_of_sample, date_from, date_to)


def score_trades(training_file, use_cache: bool = True) -> ScoredTrades | None:
    """Out-of-fold scores+PnL for a training file, cached by mtime."""
    p = Path(training_file)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    key = str(p)
    if use_cache:
        hit = _score_cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
    res = _score_trades_uncached(training_file)
    _score_cache[key] = (mtime, res)
    return res


def compute_scorecard(training_file, threshold: float,
                      instrument: str | None = None,
                      use_cache: bool = True) -> Scorecard | None:
    """Build the scorecard from a training_data.csv. Returns None if the file
    is missing/empty or lacks both winning and losing trades."""
    st = score_trades(training_file, use_cache=use_cache)
    if st is None:
        return None
    scored = st.scored
    pnl_all = scored["PnL"].to_numpy()
    allow = scored.loc[scored["Score"] >= threshold, "PnL"].to_numpy()
    skip = scored.loc[scored["Score"] < threshold, "PnL"].to_numpy()

    return Scorecard(
        instrument=instrument,
        n_trades=len(scored),
        threshold=threshold,
        out_of_sample=st.out_of_sample,
        date_from=st.date_from,
        date_to=st.date_to,
        buckets=_buckets(scored),
        all=_group("All trades (no filter)", pnl_all),
        allow=_group(f"ALLOW  (score >= {threshold:g})", allow),
        skip=_group(f"SKIP   (score < {threshold:g})", skip),
    )


def scorecard_for_instrument(instrument: str | None,
                             use_cache: bool = True) -> Scorecard | None:
    """Convenience wrapper: locate an instrument's training_data.csv under the
    data root and the shared threshold, without mutating global config."""
    inst_dir = config.DATA_ROOT / instrument if instrument else config.DATA_ROOT
    return compute_scorecard(inst_dir / "training_data.csv",
                             config.get_threshold(), instrument,
                             use_cache=use_cache)


# --------------------------------------------------------------------------- #
#  Text rendering (CLI / logs)
# --------------------------------------------------------------------------- #
def _rr(rr) -> str:
    return f"{rr:.2f}" if rr is not None else "  -"


def format_scorecard(sc: Scorecard) -> str:
    head = sc.instrument or "root"
    basis = ("walk-forward, out-of-sample"
             if sc.out_of_sample else "IN-SAMPLE (too few trades — optimistic!)")
    lines = [
        "=" * 66,
        f"  LIVE SCORECARD - {head}",
        "=" * 66,
        f"  {sc.n_trades} trades   {sc.date_from} -> {sc.date_to}",
        f"  Scoring basis: {basis}",
        f"  Live threshold: {sc.threshold:g}",
        "",
        "  By score bucket:",
        "   Score   |  N   | Win%  | Expectancy | Total $   | R:R",
        "  ---------+------+-------+------------+-----------+------",
    ]
    for b in sc.buckets:
        band = f"{b.lo:g}-{b.hi:g}"
        lines.append(
            f"   {band:<7} | {b.n:>4} | {b.win_rate:4.0f}% | "
            f"{b.expectancy:>+8.2f}   | {b.total_pnl:>+8.0f}  | {_rr(b.rr)}")
    lines += [
        "",
        "  Gate decision (at the live threshold):",
        "   Group                 |  N   | Win%  | Expectancy | Total $   | PF",
        "  -----------------------+------+-------+------------+-----------+------",
    ]
    for g in (sc.all, sc.allow, sc.skip):
        pf = f"{g.profit_factor:.2f}" if g.profit_factor is not None else "  -"
        lines.append(
            f"   {g.label:<21} | {g.n:>4} | {g.win_rate:4.0f}% | "
            f"{g.expectancy:>+8.2f}   | {g.total_pnl:>+8.0f}  | {pf}")
    lines += [
        "",
        f"  Edge added per taken trade: {sc.edge_per_trade:+.2f} $  "
        f"(ALLOW {sc.allow.expectancy:+.2f} vs all {sc.all.expectancy:+.2f})",
        f"  Selectivity: gate takes {sc.selectivity:.0f}% of trades "
        f"({sc.allow.n} of {sc.all.n})",
        f"  PnL the gate skipped:       {sc.pnl_avoided:+.0f} $  "
        f"over {sc.skip.n} blocked trades",
        "=" * 66,
    ]
    if not sc.out_of_sample:
        lines.append("  [!] In-sample numbers are optimistic - collect "
                     "150+ trades for the honest walk-forward scorecard.")
    return "\n".join(lines)


if __name__ == "__main__":
    for inst in (config.list_instruments() or [None]):
        sc = scorecard_for_instrument(inst)
        if sc:
            print(format_scorecard(sc))
            print()
