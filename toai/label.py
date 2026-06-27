"""Triple-barrier meta-labeling (López de Prado, *Advances in Financial ML*).

Instead of labeling a trade only by the sign of its final P&L, label it by **which
barrier it would hit first**: the take-profit (win = 1), the stop-loss (loss = 0),
or neither within the trade (neutral → fall back to the realized P&L sign). For
**meta-labeling** we return a binary 0/1 "should I have taken this signal" target.

The barriers come from the trade's own recorded **Stop Loss / Take Profit** (in
price) vs its **MAE / MFE** excursions (recorded in **dollars** — see
toai-mae-mfe-units), converted to points with the contract's point value. When
those columns are absent (older training_data), it degrades gracefully to
`PnL > 0`, so existing data trains exactly as before.
"""
import numpy as np
import pandas as pd

from . import config

# Dollars-per-point per micro/mini future (mirrors dashboard.CONTRACTS; kept here
# to avoid importing the Streamlit module into the training path).
_POINT_VALUE = {
    "MES": 5.0, "ES": 50.0, "MNQ": 2.0, "NQ": 20.0, "MYM": 0.5, "YM": 5.0,
    "M2K": 5.0, "RTY": 50.0, "MCL": 100.0, "CL": 1000.0, "MGC": 10.0,
    "GC": 100.0, "MBT": 0.1,
}

_BARRIER_COLS = ("MAE", "MFE", "StopLoss", "TakeProfit", "EntryPrice")


def point_value(instrument) -> float:
    return _POINT_VALUE.get(str(instrument or "").upper(), 5.0)


def _current_instrument() -> str:
    try:
        return config.MODEL_FILE.parent.name
    except Exception:
        return ""


def meta_label(df: pd.DataFrame, instrument=None, tie: str = "stop") -> pd.Series:
    """Binary meta-label per trade (1 = take/win, 0 = skip/loss).

    Triple-barrier when the trade carries MAE/MFE + Stop/Take + EntryPrice;
    otherwise `PnL > 0`. `tie='stop'` is the conservative choice when both the
    stop and the target would have been touched (their order is unknown)."""
    pnl = pd.to_numeric(df.get(config.TARGET_COLUMN), errors="coerce")
    base = (pnl > 0).astype(int)
    if not all(c in df.columns for c in _BARRIER_COLS):
        return base                      # graceful fallback — old data path

    pv = point_value(instrument or _current_instrument())
    qty = pd.to_numeric(df.get("Qty", 1), errors="coerce").fillna(1).replace(0, 1)
    denom = pv * qty
    mae_pts = pd.to_numeric(df["MAE"], errors="coerce") / denom      # $ → points
    mfe_pts = pd.to_numeric(df["MFE"], errors="coerce") / denom
    entry = pd.to_numeric(df["EntryPrice"], errors="coerce")
    tp = pd.to_numeric(df["TakeProfit"], errors="coerce")
    sl = pd.to_numeric(df["StopLoss"], errors="coerce")
    tp_dist = (tp - entry).abs()         # price units == points for these futures
    sl_dist = (entry - sl).abs()

    tgt_hit = (tp_dist > 0) & (mfe_pts >= tp_dist)
    stop_hit = (sl_dist > 0) & (mae_pts >= sl_dist)

    label = base.copy()
    # target first → win; stop first → loss; both → tie; neither → keep PnL sign.
    label = label.mask(tgt_hit & ~stop_hit, 1)
    label = label.mask(stop_hit & ~tgt_hit, 0)
    if tie == "stop":
        label = label.mask(tgt_hit & stop_hit, 0)
    else:
        label = label.mask(tgt_hit & stop_hit, 1)
    # rows lacking usable barriers fall back to the PnL-sign base label
    no_barrier = ~(tgt_hit | stop_hit) & (tp_dist.isna() | sl_dist.isna()
                                          | mae_pts.isna() | mfe_pts.isna())
    label = label.mask(no_barrier, base)
    return label.astype(int)


def has_barriers(df: pd.DataFrame) -> bool:
    """True when the frame carries the columns triple-barrier labeling needs."""
    return all(c in df.columns for c in _BARRIER_COLS)
