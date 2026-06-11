"""Generate synthetic training data so the pipeline can be tested end-to-end
before NinjaTrader has exported real trades.

The synthetic market gives winners a mild edge on trend/momentum features so
a trained model should land at PMV > 0.5.
"""
import numpy as np
import pandas as pd

from . import config


def generate_training_data(n_trades: int = 500, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    price = 5000 + np.cumsum(rng.normal(0, 5, n_trades))
    atr20 = np.abs(rng.normal(8, 2, n_trades))
    ema9 = price + rng.normal(0, 3, n_trades)
    ema20 = price + rng.normal(0, 5, n_trades)
    ema50 = price + rng.normal(0, 8, n_trades)
    rsi14 = np.clip(rng.normal(50, 15, n_trades), 5, 95)
    adx14 = np.clip(rng.normal(25, 10, n_trades), 5, 60)
    dist_high = np.abs(rng.normal(12, 6, n_trades))
    dist_low = np.abs(rng.normal(12, 6, n_trades))
    vol_ratio = np.abs(rng.normal(1.0, 0.4, n_trades))
    bb_width = np.abs(rng.normal(20, 7, n_trades))
    zscore = rng.normal(0, 1, n_trades)

    # Edge: trending ADX, healthy volume, balanced location and momentum
    # tilt the win odds (per-feature thresholds a tree model can learn).
    edge = (
        0.20 * (adx14 > 25)
        + 0.15 * (vol_ratio > 1.0)
        + 0.15 * (np.abs(zscore) < 1.0)
        + 0.10 * (rsi14 > 50)
    )
    win_prob = np.clip(0.25 + edge, 0.05, 0.95)
    is_win = rng.random(n_trades) < win_prob
    pnl = np.where(is_win,
                   np.abs(rng.normal(120, 60, n_trades)),
                   -np.abs(rng.normal(90, 45, n_trades)))

    return pd.DataFrame({
        "TradeID": np.arange(1, n_trades + 1),
        "DateTime": pd.date_range("2026-05-01 09:30", periods=n_trades, freq="15min"),
        "Direction": rng.choice(["Long", "Short"], n_trades),
        "ATR20": atr20,
        "EMA9": ema9,
        "EMA20": ema20,
        "EMA50": ema50,
        "RSI14": rsi14,
        "ADX14": adx14,
        "Distance_SwingHigh": dist_high,
        "Distance_SwingLow": dist_low,
        "Volume_Ratio": vol_ratio,
        "BBand_Width": bb_width,
        "ZScore": zscore,
        "PnL": pnl.round(2),
    })


def write_sample_files(n_trades: int = 500):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    df = generate_training_data(n_trades)
    df.to_csv(config.TRAINING_FILE, index=False)
    df.tail(1)[config.FEATURES].to_csv(config.CURRENT_FEATURES_FILE, index=False)
    print(f"Wrote {n_trades} synthetic trades to {config.TRAINING_FILE}")
    print(f"Wrote sample bar features to {config.CURRENT_FEATURES_FILE}")
    return df
