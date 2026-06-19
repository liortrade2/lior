"""Edgewonk export — reshape a NinjaTrader trade export into the exact column
layout Edgewonk imports (.xlsx), and tag each trade with the TOAI ML score so
you can slice your Edgewonk journal by the model's conviction.

NinjaTrader's Trade Performance export already carries every field Edgewonk
needs (plus extra fee columns). This keeps the 19 required columns in the exact
order, drops the rest, writes .xlsx (Edgewonk only imports .xlsx), and appends
"| ML:<score>" to each trade's Entry name (scored by that strategy's own model)
— turning Edgewonk into a place to study performance vs the TOAI score.
"""
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from . import config, variants
from .features import derive_features
from .merge import _find_col

# Edgewonk's required NinjaTrader column order (default).
EDGEWONK_COLUMNS = [
    "Trade number", "Instrument", "Account", "Strategy", "Market pos.", "Qty",
    "Entry price", "Exit price", "Entry time", "Exit time", "Entry name",
    "Exit name", "Profit", "Cum. net profit", "Commission",
    "MAE", "MFE", "ETD", "Bars",
]


def _read(path):
    p = str(path).lower()
    return pd.read_excel(path) if p.endswith((".xlsx", ".xls")) else pd.read_csv(path)


def _instrument_of(df):
    col = _find_col(df.columns, "instrument")
    if col is not None and len(df):
        v = str(df.iloc[0][col]).strip()
        return v.split()[0] if v else None
    return None


def _scores_for(df, instrument, src_stem):
    """Per-trade TOAI score, aligned to df rows, scored by the model of the
    matching strategy variant — so the tag reflects the gate that belongs to
    THIS strategy, not whatever model is currently active. None if no matching
    variant / data."""
    if not instrument:
        return None
    inst_dir = config.DATA_ROOT / instrument
    et = _find_col(df.columns, "entry", "time")
    if et is None:
        return None
    slug = variants.slug(src_stem)
    model_file = inst_dir / "models" / f"{slug}.pkl"
    reg = variants._load_registry(inst_dir)
    if slug not in reg or not model_file.exists():
        return None
    try:
        bundle = joblib.load(model_file)
        tf = reg[slug].get("timeframe")
        bars_path = inst_dir / f"bar_data_train_{tf}min.csv"
        if not bars_path.exists():
            bars_path = inst_dir / "bar_data.csv"
        bars = pd.read_csv(bars_path)
        bars["DateTime"] = pd.to_datetime(bars["DateTime"], errors="coerce")
        bars = (bars.dropna(subset=["DateTime"])
                .drop_duplicates(subset="DateTime", keep="last").sort_values("DateTime"))
        bars = derive_features(bars)

        t = pd.DataFrame({"EntryTime": pd.to_datetime(df[et], errors="coerce"),
                          "_i": range(len(df))})
        m = pd.merge_asof(t.sort_values("EntryTime"), bars,
                          left_on="EntryTime", right_on="DateTime",
                          direction="backward", tolerance=pd.Timedelta(minutes=60))
        m = m.sort_values("_i")
        feats = bundle["features"]
        valid = m[feats].notna().all(axis=1).to_numpy()
        scores = np.full(len(df), np.nan)
        if valid.any():
            X = bundle["scaler"].transform(m.loc[valid, feats])
            scores[valid] = (bundle["model"].predict_proba(X)[:, 1] * 100).round(0)
        return scores
    except Exception:
        return None


def to_edgewonk(src_path, out_path=None, tag_score=True, instrument=None):
    """Convert a NinjaTrader export to an Edgewonk-ready .xlsx. Returns
    (out_path, note)."""
    src_path = Path(src_path)
    df = _read(src_path)

    out = pd.DataFrame()
    for col in EDGEWONK_COLUMNS:
        out[col] = df[col] if col in df.columns else ""

    note = ""
    if tag_score:
        inst = instrument or _instrument_of(df)
        scores = _scores_for(df, inst, src_path.stem)
        if scores is not None and len(scores) == len(out):
            out["Entry name"] = [
                f"{n} | ML:{s:.0f}" if pd.notna(s) else f"{n}"
                for n, s in zip(out["Entry name"].astype(str), scores)]
            note = f"  (tagged with this strategy's TOAI score)"

    if out_path is None:
        dest = config.DATA_ROOT / "_edgewonk"
        dest.mkdir(exist_ok=True)
        out_path = dest / (src_path.stem + "_edgewonk.xlsx")
    out_path = Path(out_path)
    out.to_excel(out_path, index=False, engine="openpyxl")
    return out_path, note


def convert_all(src_dir=None, tag_score=True):
    """Convert every NinjaTrader trades export in a folder to Edgewonk .xlsx."""
    src_dir = Path(src_dir or config.DATA_ROOT)
    done = []
    for p in sorted(src_dir.glob("*.csv")):
        try:
            cols = pd.read_csv(p, nrows=0).columns
            if _find_col(cols, "entry", "time") is None:
                continue
            out, note = to_edgewonk(p, tag_score=tag_score)
            done.append((p.name, out.name, note))
        except Exception as e:
            done.append((p.name, f"ERROR: {e}", ""))
    return done


def export_all(tag_score=True):
    """Convert every NinjaTrader export in the data root AND _trained/ to
    Edgewonk .xlsx (in _edgewonk/). Returns [(src, out, note), …]."""
    done = []
    for d in (config.DATA_ROOT, config.DATA_ROOT / "_trained"):
        if Path(d).is_dir():
            done += convert_all(d, tag_score=tag_score)
    return done


# --------------------------------------------------------------------------- #
#  Live-trades export (the panel's button) — your REAL fills, not the backtest.
#  Source = <inst>/executions.csv (the AddOn's realized fills, full NinjaTrader
#  columns incl. prices), tagged with the EXACT gate score from journal.csv.
#  Per-instrument folder + timestamp, so each click keeps the prior file.
# --------------------------------------------------------------------------- #
def _journal_scores(inst_dir) -> dict:
    """{entry-timestamp -> Score} from the realized journal, so each live fill
    carries the exact score the gate gave it (no re-scoring)."""
    out = {}
    try:
        j = pd.read_csv(inst_dir / "journal.csv")
    except (OSError, ValueError, pd.errors.EmptyDataError):
        return out
    if "DateTime" not in j.columns or "Score" not in j.columns:
        return out
    for _, r in j.iterrows():
        ts = pd.to_datetime(r["DateTime"], errors="coerce")
        if pd.notna(ts):
            out[ts] = r["Score"]
    return out


def export_active(instrument, timestamp, tag_score=True):
    """Export the instrument's REALIZED live trades (executions.csv) to a
    timestamped Edgewonk .xlsx under _edgewonk/<INSTRUMENT>/ — NOT the backtest.
    Each click keeps the prior file (chronological, never overwritten).
    Returns (out_path|None, note)."""
    inst_dir = config.DATA_ROOT / instrument if instrument else config.DATA_ROOT
    src = inst_dir / "executions.csv"
    try:
        trades = pd.read_csv(src)
    except (OSError, ValueError, pd.errors.EmptyDataError):
        return None, "no live trades yet (executions.csv not found)"
    if trades.empty:
        return None, "no live trades yet (executions.csv empty)"

    out = pd.DataFrame()
    for col in EDGEWONK_COLUMNS:
        out[col] = trades[col] if col in trades.columns else ""

    if tag_score:
        scores = _journal_scores(inst_dir)
        et = (pd.to_datetime(trades["Entry time"], errors="coerce")
              if "Entry time" in trades.columns else None)
        base = out["Entry name"].astype(str)
        names = []
        for i in range(len(out)):
            n = base.iloc[i].strip() or "Live"
            s = scores.get(et.iloc[i]) if et is not None else None
            names.append(f"{n} | ML:{s:.0f}" if s is not None and s == s else n)
        out["Entry name"] = names

    dest_dir = config.DATA_ROOT / "_edgewonk" / (instrument or "root")
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / f"{instrument or 'root'}_live_{timestamp}.xlsx"
    out.to_excel(out_path, index=False, engine="openpyxl")
    return out_path, f"{len(out)} live trades"


def export_active_all(tag_score=True):
    """Export each instrument's REALIZED live trades into its own
    _edgewonk/<inst>/ folder, all stamped with one shared timestamp. Returns
    [(instrument, out_path|None, note), …]."""
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    results = []
    for inst in (config.list_instruments() or [None]):
        out, note = export_active(inst, ts, tag_score=tag_score)
        results.append((inst, out, note))
    return results


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        out, note = to_edgewonk(sys.argv[1])
        print(f"Wrote {out}{note}")
    else:
        for src, out, note in convert_all():
            print(f"{src}  ->  {out}{note}")
