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
#  Source = <inst>/executions.csv (the AddOn's realized fills). Written in
#  Edgewonk's NATIVE import layout (import with the "Edgewonk" importer, not
#  NinjaTrader), so we can carry the ML data as numeric Custom Stats:
#    Custom Stat 1 = ML score · 2 = Verdict · 3 = Variant · 4 = Threshold.
#  Commission + Highest/Lowest price (MAE/MFE) fill in once the AddOn writes
#  them to executions.csv (recompile TOAIExecutionLogger). One file per day.
# --------------------------------------------------------------------------- #
EDGEWONK_NATIVE_COLUMNS = [
    "Opening Time", "Type [buy/sell]", "Symbol", "Setup", "Size / Quantity",
    "Closing Time", "Entry Price", "Closing Price", "Swap", "Commission",
    "Net Profit", "Stop Loss (optional)", "Take Profit(optional)",
    "Highest price (optional)", "Lowest price (optional)", "Notes",
    "Pre Trade Comments", "Entry Comments", "Trade Management", "Exit Comments",
    "Breakeven?",
] + [f"Custom Stat {i}" for i in range(1, 21)]


def _journal_lookup(inst_dir) -> dict:
    """{entry-timestamp -> {Score, Verdict, Variant, Threshold}} from the
    realized journal, so each live fill carries the exact values the gate used
    (no re-scoring)."""
    out = {}
    try:
        j = pd.read_csv(inst_dir / "journal.csv")
    except (OSError, ValueError, pd.errors.EmptyDataError):
        return out
    if "DateTime" not in j.columns:
        return out
    for _, r in j.iterrows():
        ts = pd.to_datetime(r["DateTime"], errors="coerce")
        if pd.notna(ts):
            out[ts] = {k: r.get(k) for k in
                       ("Score", "Verdict", "Variant", "Threshold")}
    return out


def _native_rows(grp, jlook) -> pd.DataFrame:
    """Build Edgewonk-native rows for one day's executions group."""
    n = len(grp)

    def col(name, default=""):
        return list(grp[name]) if name in grp.columns else [default] * n

    def num(x):
        return x if (x is not None and x == x) else ""   # drop NaN/None -> blank

    out = {c: [""] * n for c in EDGEWONK_NATIVE_COLUMNS}
    pos = col("Market pos.", "")
    out["Opening Time"] = [str(x) for x in col("Entry time")]
    out["Closing Time"] = [str(x) for x in col("Exit time")]
    out["Type [buy/sell]"] = ["BUY" if str(p).lower().startswith("long")
                              else "SELL" for p in pos]
    out["Symbol"] = col("Instrument")
    out["Size / Quantity"] = col("Qty", 1)
    out["Entry Price"] = col("Entry price")
    out["Closing Price"] = col("Exit price")
    out["Net Profit"] = col("Profit")
    out["Commission"] = [num(x) for x in col("Commission", "")]
    out["Highest price (optional)"] = [num(x) for x in col("Highest price", "")]
    out["Lowest price (optional)"] = [num(x) for x in col("Lowest price", "")]
    out["Stop Loss (optional)"] = [num(x) for x in col("Stop Loss", "")]
    out["Take Profit(optional)"] = [num(x) for x in col("Take Profit", "")]
    out["Breakeven?"] = ["No"] * n

    setups, st1, st2, st3, st4 = [], [], [], [], []
    for t in grp["_et"]:
        info = jlook.get(t, {})
        sc, vr, va, th = (info.get("Score"), info.get("Verdict"),
                          info.get("Variant"), info.get("Threshold"))
        setups.append(va if (va and va == va) else "TOAI")
        st1.append(f"{sc:.0f}" if (sc is not None and sc == sc) else "")
        st2.append(vr if (vr and vr == vr) else "")
        st3.append(va if (va and va == va) else "")
        st4.append(num(th))
    out["Setup"] = setups
    out["Custom Stat 1"] = st1   # ML score
    out["Custom Stat 2"] = st2   # Verdict (ALLOW/SKIP)
    out["Custom Stat 3"] = st3   # Variant (strategy)
    out["Custom Stat 4"] = st4   # Threshold used
    return pd.DataFrame(out, columns=EDGEWONK_NATIVE_COLUMNS)


def export_live_by_day(instrument, tag_score=True, force=False):
    """Write ONE Edgewonk-native .xlsx per trading day from the instrument's
    realized fills (executions.csv), with the ML data as Custom Stats. Files are
    named by the trade DATE (<inst>_live_<YYYY-MM-DD>.xlsx) under
    _edgewonk/<INSTRUMENT>/, so the folder accumulates one file per day and a
    same-day refresh just rewrites that day's file (never loses prior days).

    Change-aware: a day's file is rewritten only when its trade count changed
    (i.e. new fills landed), so the auto-export doesn't keep touching unchanged
    files. force=True rewrites regardless (the manual 'export now' button).
    Returns [(date_str, out_path), …] for the files actually written."""
    inst_dir = config.DATA_ROOT / instrument if instrument else config.DATA_ROOT
    try:
        trades = pd.read_csv(inst_dir / "executions.csv")
    except (OSError, ValueError, pd.errors.EmptyDataError):
        return []
    if trades.empty or "Entry time" not in trades.columns:
        return []
    et = pd.to_datetime(trades["Entry time"], errors="coerce")
    trades = trades.assign(_date=et.dt.date, _et=et)
    trades = trades.dropna(subset=["_date"])
    if trades.empty:
        return []

    jlook = _journal_lookup(inst_dir) if tag_score else {}
    dest_dir = config.DATA_ROOT / "_edgewonk" / (instrument or "root")
    dest_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for day, grp in trades.groupby("_date"):
        out_path = dest_dir / f"{instrument or 'root'}_live_{day}.xlsx"
        # Skip the rewrite if this day's file already holds these trades (no new
        # fills) — unless force=True (manual export-now button).
        if not force and out_path.exists():
            try:
                if len(pd.read_excel(out_path)) == len(grp):
                    continue
            except Exception:
                pass   # unreadable -> rewrite it
        out = _native_rows(grp, jlook)
        out.to_excel(out_path, index=False, engine="openpyxl")
        written.append((str(day), out_path))
    return written


def _has_live_trades(instrument) -> bool:
    inst_dir = config.DATA_ROOT / instrument if instrument else config.DATA_ROOT
    try:
        return not pd.read_csv(inst_dir / "executions.csv").empty
    except (OSError, ValueError, pd.errors.EmptyDataError):
        return False


def export_active(instrument, tag_score=True, force=False):
    """Per-day live export for one instrument. With force=True (manual button)
    always rewrites today's file. Returns (latest_path|None, note)."""
    written = export_live_by_day(instrument, tag_score=tag_score, force=force)
    if written:
        written.sort(key=lambda dp: dp[0])
        return written[-1][1], f"{len(written)} day-file(s)"
    # Nothing written: distinguish 'no trades' from 'already up to date'.
    if _has_live_trades(instrument):
        return None, "already up to date"
    return None, "no live trades yet"


def export_active_all(tag_score=True, force=False):
    """Per-day live export for every instrument into its own _edgewonk/<inst>/
    folder. force=True (manual button) rewrites today's files regardless.
    Returns [(instrument, latest_path|None, note), …]."""
    results = []
    for inst in (config.list_instruments() or [None]):
        out, note = export_active(inst, tag_score=tag_score, force=force)
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
