"""TOAI-native trade journal — the realized side of the closed loop.

External journals (Edgewonk, TradeZella, TradesViz, Tradervue) are human-review
tools. The ones that auto-sync from NinjaTrader push fills to their cloud for a
person to read; closing the loop back into TOAI would mean depending on their
paid, rate-limited API. This journal is ours: it ingests the same NinjaTrader
trade export we already understand, scores and tags every trade with the gate's
decision, and appends it to a per-instrument append-only ledger
(`<inst>/journal.csv`) that survives retrains.

Two feeds:
  * `record_from_training()` — after a (re)train, log the export's trades
    (source="backtest"). Lets the journal accumulate the strategy's history.
  * `record_export(exec_file, source="live")` — log real executed fills as they
    land in `<inst>/executions.csv`. THIS is the realized-PnL record the
    autonomous loop validates against: every live trade next to the score the
    gate gave it.

The realized ledger reuses the scorecard's own chart/table/edge view via
`scorecard.scorecard_from_scored`, so "predicted (walk-forward)" and "realized
(actual fills)" are the same picture side by side — the real test of whether the
filter's backtest edge shows up in money.
"""
from datetime import datetime

import joblib
import pandas as pd

from . import config, variants
from .features import derive_features
from .merge import match_trades

JOURNAL_NAME = "journal.csv"
_LEDGER_COLS = (["DateTime", "Direction"] + config.FEATURES +
                ["PnL", "Score", "Verdict", "Variant", "Threshold",
                 "Source", "RecordedAt"])


def _inst_dir(instrument):
    return config.DATA_ROOT / instrument if instrument else config.DATA_ROOT


def _journal_path(inst_dir):
    return inst_dir / JOURNAL_NAME


def _key(dt, direction, pnl) -> str:
    try:
        p = round(float(pnl), 2)
    except (TypeError, ValueError):
        p = pnl
    return f"{dt}|{direction}|{p}"


def _append(out_df: pd.DataFrame, inst_dir, source: str) -> int:
    """Score a matched trade set with the instrument's live model, tag each
    trade with the gate decision, and append the new (deduped) rows to the
    ledger. Returns how many were added."""
    model_file = inst_dir / "model.pkl"
    if out_df is None or out_df.empty or not model_file.exists():
        return 0
    bundle = joblib.load(model_file)
    d = derive_features(out_df).dropna(subset=bundle["features"])
    if d.empty:
        return 0

    X = bundle["scaler"].transform(d[bundle["features"]])
    d = d.copy()
    d["Score"] = (bundle["model"].predict_proba(X)[:, 1] * 100).round(1)
    threshold = config.get_threshold()
    d["Verdict"] = ["ALLOW" if s >= threshold else "SKIP" for s in d["Score"]]
    _, vinfo = variants.active_variant(inst_dir)
    d["Variant"] = (vinfo or {}).get("name", "")
    d["Threshold"] = threshold
    d["Source"] = source
    d["RecordedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    d["DateTime"] = d["DateTime"].astype(str)

    new = d[_LEDGER_COLS].copy()
    jp = _journal_path(inst_dir)
    if jp.exists():
        try:
            existing = pd.read_csv(jp)
        except (OSError, pd.errors.EmptyDataError):
            existing = None
        if existing is not None and len(existing):
            seen = {_key(r.DateTime, r.Direction, r.PnL)
                    for r in existing[["DateTime", "Direction", "PnL"]].itertuples()}
            mask = [_key(r.DateTime, r.Direction, r.PnL) not in seen
                    for r in new[["DateTime", "Direction", "PnL"]].itertuples()]
            new = new[mask]
            if new.empty:
                return 0
            new = pd.concat([existing, new], ignore_index=True)
            n_added = len(new) - len(existing)
        else:
            n_added = len(new)
    else:
        n_added = len(new)

    inst_dir.mkdir(parents=True, exist_ok=True)
    new.to_csv(jp, index=False)
    return n_added


def record_from_training(inst_dir=None, source: str = "backtest",
                         verbose: bool = True) -> int:
    """Log the already-matched training_data.csv (produced by the last train).
    No re-matching — it's the freshest merged trade set for this instrument."""
    inst_dir = inst_dir or config.MODEL_FILE.parent
    tf = inst_dir / "training_data.csv"
    if not tf.exists():
        return 0
    try:
        df = pd.read_csv(tf)
    except (OSError, pd.errors.EmptyDataError):
        return 0
    n = _append(df, inst_dir, source)
    if verbose and n:
        print(f"Journal: +{n} {source} trades -> {_journal_path(inst_dir).name}")
    return n


def record_export(trades_file, source: str = "live", inst_dir=None,
                  verbose: bool = True) -> int:
    """Log an arbitrary NinjaTrader trade/executions export (matches to bars
    first). Use for live fills dropped into executions.csv."""
    inst_dir = inst_dir or config.MODEL_FILE.parent
    try:
        out, _, _ = match_trades(trades_file, bar_data_path=inst_dir / "bar_data.csv")
    except (ValueError, OSError, FileNotFoundError):
        return 0
    n = _append(out, inst_dir, source)
    if verbose and n:
        print(f"Journal: +{n} {source} fills -> {_journal_path(inst_dir).name}")
    return n


# --------------------------------------------------------------------------- #
#  Read side
# --------------------------------------------------------------------------- #
def live_scored(inst_dir=None, source: str | None = None):
    """The ledger as a scored DataFrame (Score, PnL, DateTime) for the scorecard
    assembler. source=None pools every feed; pass "live" for actual fills only."""
    inst_dir = inst_dir or config.MODEL_FILE.parent
    try:
        df = pd.read_csv(_journal_path(inst_dir))
    except (FileNotFoundError, OSError, pd.errors.EmptyDataError):
        return None
    if source:
        df = df[df["Source"] == source]
    if df.empty or "Score" not in df.columns:
        return None
    out = df[["Score", "PnL"]].copy()
    if "DateTime" in df.columns:
        out["DateTime"] = df["DateTime"].to_numpy()
    return out


def live_scorecard(inst_dir=None, source: str | None = None):
    """A Scorecard built from realized journal trades — same view as the
    walk-forward scorecard, but on actual outcomes (realized=True)."""
    from .scorecard import scorecard_from_scored
    inst_dir = inst_dir or config.MODEL_FILE.parent
    scored = live_scored(inst_dir, source)
    if scored is None:
        return None
    date_from = date_to = ""
    if "DateTime" in scored.columns:
        dt = pd.to_datetime(scored["DateTime"], errors="coerce").dropna()
        if len(dt):
            date_from, date_to = str(dt.min().date()), str(dt.max().date())
    return scorecard_from_scored(scored, config.get_threshold(), inst_dir.name,
                                 out_of_sample=False, realized=True,
                                 date_from=date_from, date_to=date_to)


def summary(inst_dir=None) -> dict | None:
    """Counts per feed for a quick 'what's in the journal' readout."""
    inst_dir = inst_dir or config.MODEL_FILE.parent
    try:
        df = pd.read_csv(_journal_path(inst_dir))
    except (FileNotFoundError, OSError, pd.errors.EmptyDataError):
        return None
    if df.empty:
        return None
    by_source = df["Source"].value_counts().to_dict() if "Source" in df else {}
    return {"total": len(df), "by_source": by_source}


# Instrument-name convenience wrappers (UI/CLI use these — no global mutation).
# The realized view defaults to live fills only — backtest trades scored by
# their own model are in-sample/optimistic, so the honest backtest view stays
# the walk-forward scorecard, and the journal shows what actually happened live.
def record_for_instrument(instrument, source="backtest"):
    return record_from_training(_inst_dir(instrument), source)


def live_scorecard_for(instrument, source="live"):
    return live_scorecard(_inst_dir(instrument), source)


def live_scored_for(instrument, source="live"):
    return live_scored(_inst_dir(instrument), source)


def summary_for(instrument):
    return summary(_inst_dir(instrument))
