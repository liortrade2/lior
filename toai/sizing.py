"""Position-sizing simulator (roadmap Tier 2) — does score-tiered sizing beat
uniform sizing, and what are the right multipliers?

The scorecard proved expectancy rises with score, which tempts bigger size on
higher-score trades. But tiering (a) amplifies the noisiest buckets, (b)
invalidates the equal-size walk-forward we validated, and (c) needs principled
multipliers, not an arbitrary 1/2/3. This answers those BEFORE anything is wired
live: it scores every trade out-of-fold, splits the ALLOW trades into score
tiers, and compares uniform vs tiered sizing **at equal total exposure** — so it
measures allocation skill, not leverage. If tiered beats uniform at the same
risk budget, the edge is real; if not, tiering only adds noise and complexity.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, scorecard


def _bands(threshold: float, edges):
    """[(lo, hi), …] score bands for the ALLOW region, split at `edges`."""
    pts = [threshold] + [e for e in edges if e > threshold] + [100.000001]
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]


def _band_index(score, bands):
    for i, (lo, hi) in enumerate(bands):
        if lo <= score < hi:
            return i
    return len(bands) - 1


def _metrics(pnl: np.ndarray, sizes: np.ndarray) -> dict:
    p = pnl * sizes
    equity = np.cumsum(p)
    peak = np.maximum.accumulate(equity)
    dd = float((peak - equity).max()) if len(p) else 0.0
    net = float(equity[-1]) if len(p) else 0.0
    mean = float(p.mean()) if len(p) else 0.0
    std = float(p.std(ddof=1)) if len(p) > 1 else 0.0
    return {
        "net": net, "maxDD": dd, "exp": mean,
        "net_dd": (net / dd) if dd > 0 else float("inf"),
        "sharpe": (mean / std * np.sqrt(len(p))) if std > 0 else 0.0,
    }


def _norm_avg1(sizes: np.ndarray) -> np.ndarray:
    """Scale sizes so the average is 1 — i.e., the SAME total contracts as
    uniform sizing. This isolates allocation (where the size goes) from leverage
    (just trading bigger)."""
    s = sizes.astype(float)
    m = s.mean()
    return s / m if m > 0 else s


def _active_training_file(instrument):
    """The active variant's own trade snapshot (so we size the model that's
    actually live), falling back to training_data.csv."""
    from . import variants
    from .merge import live_timeframe
    inst_dir = config.DATA_ROOT / instrument if instrument else config.DATA_ROOT
    s, _ = variants.active_variant_for_tf(live_timeframe(inst_dir), inst_dir)
    if s is None:
        s, _ = variants.active_variant(inst_dir)
    snap = variants.variant_training_file(s, inst_dir) if s else None
    return snap or scorecard.training_file_for(instrument)


def simulate(instrument, edges=(80, 90), threshold=None, training_file=None):
    """Compare uniform vs score-tiered sizing on an instrument's active model,
    out-of-fold, at equal exposure. Returns a dict or None."""
    threshold = config.get_threshold() if threshold is None else threshold
    tf = training_file or _active_training_file(instrument)
    st = scorecard.score_trades(tf)            # out-of-fold (Score, PnL[, DateTime])
    if st is None:
        return None
    scored = st.scored
    allow = scored[scored["Score"] >= threshold]
    if len(allow) < 30:
        return None
    score = allow["Score"].to_numpy()
    pnl = allow["PnL"].to_numpy(dtype=float)

    bands = _bands(threshold, edges)
    idx = np.array([_band_index(s, bands) for s in score])
    band_n = [int((idx == i).sum()) for i in range(len(bands))]
    band_exp = [float(pnl[idx == i].mean()) if (idx == i).any() else 0.0
                for i in range(len(bands))]

    # --- three sizing schemes, all normalized to equal exposure -------------
    uniform = np.ones(len(pnl))
    fixed_mult = np.array([i + 1 for i in range(len(bands))], dtype=float)  # 1,2,3
    fixed = _norm_avg1(fixed_mult[idx])
    # expectancy-proportional (principled): weight ∝ band expectancy, no shorts.
    w = np.array([max(e, 0.0) for e in band_exp])
    if w.sum() == 0:
        w = np.ones(len(bands))
    prop = _norm_avg1(w[idx])

    out_of_sample = st.out_of_sample
    return {
        "instrument": instrument, "threshold": threshold,
        "out_of_sample": out_of_sample,
        "bands": bands, "band_n": band_n, "band_exp": band_exp,
        "uniform": _metrics(pnl, uniform),
        "tiered_fixed": _metrics(pnl, fixed),
        "tiered_prop": _metrics(pnl, prop),
        # the recommended (principled) multipliers, normalized to avg 1
        "prop_mult": [round(float(w[i] / (np.average(w[idx]))), 2) if len(idx) else 0
                      for i in range(len(bands))],
    }


def format_report(r) -> str:
    if r is None:
        return "Not enough ALLOW trades to simulate sizing."
    basis = "out-of-sample" if r["out_of_sample"] else "IN-SAMPLE (small — optimistic)"
    lines = [
        "=" * 64,
        f"  POSITION SIZING — {r['instrument']}   ({basis})",
        "=" * 64,
        f"  threshold {r['threshold']:g}   ·   compared at EQUAL total exposure",
        "",
        "  Score tiers (ALLOW region):",
    ]
    for (lo, hi), n, e, m in zip(r["bands"], r["band_n"], r["band_exp"], r["prop_mult"]):
        hi_disp = 100 if hi > 100 else hi
        lines.append(f"   {lo:g}-{hi_disp:g} | n={n:>4} | exp {e:+7.2f}$ | "
                     f"recommended size ×{m:.2f}")
    lines += [
        "",
        "  Scheme              | Net $    | maxDD $ | net/DD | Sharpe",
        "  --------------------+----------+---------+--------+-------",
    ]
    for tag, key in (("uniform (1×)", "uniform"),
                     ("tiered fixed 1/2/3", "tiered_fixed"),
                     ("tiered expectancy", "tiered_prop")):
        m = r[key]
        lines.append(f"   {tag:<19}| {m['net']:>+8.0f} | {m['maxDD']:>7.0f} | "
                     f"{m['net_dd']:>6.2f} | {m['sharpe']:>5.2f}")
    # verdict
    u, t = r["uniform"], r["tiered_prop"]
    better = t["net_dd"] > u["net_dd"] and t["net"] > u["net"]
    lines += [
        "",
        f"  Allocation alpha (expectancy-tiered vs uniform, same exposure): "
        f"net {t['net'] - u['net']:+.0f}$, net/DD {t['net_dd'] - u['net_dd']:+.2f}",
        f"  -> {'TIERED HELPS — worth wiring' if better else 'no clear gain — tiering only adds complexity'}",
        "=" * 64,
    ]
    if not r["out_of_sample"]:
        lines.append("  [!] small sample — rerun on a large-trade model before trusting.")
    return "\n".join(lines)


def report(instrument, edges=(80, 90)) -> str:
    return format_report(simulate(instrument, edges=edges))


if __name__ == "__main__":
    for inst in (config.list_instruments() or [None]):
        print(report(inst))
        print()
