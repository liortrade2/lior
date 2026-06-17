"""One-click pipeline: real backtest export -> training file -> trained model.

The trades export can have ANY file name (e.g. the strategy's name) —
just save it into C:\\LIOR_ML. The newest CSV that looks like a Strategy
Analyzer trades export is picked automatically; when a strategy name is
given, files containing that name are preferred. Run via TOAI_Train.bat
or the panel's "Refresh from Strategy Analyzer" button.
"""
import pandas as pd

from . import config
from .merge import _find_col, merge_backtest
from .train import train

# Files TOAI itself writes — never candidates for a trades export.
_OWN_FILES = {config.BAR_DATA_FILE.name, config.TRAINING_FILE.name,
              config.CURRENT_FEATURES_FILE.name, config.TRADE_LOG_FILE.name}


def _is_trades_export(path) -> bool:
    """A trades export has at least an entry-time and a profit column."""
    try:
        cols = pd.read_csv(path, nrows=0).columns
    except Exception:
        return False
    return (_find_col(cols, "entry", "time") is not None
            and _find_col(cols, "profit", exclude=("cum",)) is not None)


def _export_instrument(path) -> str | None:
    """Master instrument name from the export's Instrument column
    ("ES JUN26" -> "ES") — routes the export to the right data folder."""
    try:
        df = pd.read_csv(path, nrows=1)
    except Exception:
        return None
    col = _find_col(df.columns, "instrument")
    if col is None or df.empty:
        return None
    value = str(df.iloc[0][col]).strip()
    return value.split()[0] if value else None


def all_trades_exports():
    """Every trades-export CSV in the data ROOT (across all instruments).
    Exports are always saved to the root; the Instrument column routes each
    to its per-instrument folder."""
    return [p for p in config.DATA_ROOT.glob("*.csv")
            if p.name not in _OWN_FILES and _is_trades_export(p)]


def find_trades_export(strategy_name: str | None = None):
    """Newest trades-export CSV in the data ROOT, preferring files whose name
    contains the selected strategy's name."""
    candidates = all_trades_exports()
    if not candidates:
        return None
    if strategy_name:
        stem = strategy_name.lower().removesuffix(".bbs").strip()
        matching = [p for p in candidates if stem and stem in p.name.lower()]
        if matching:
            candidates = matching
    return max(candidates, key=lambda p: p.stat().st_mtime)


def build_and_train(strategy_name: str | None = None, trades_file=None):
    print("=" * 46)
    print("  TOAI — Build training file + train model")
    print("=" * 46)

    if trades_file is None:
        trades_file = find_trades_export(strategy_name)
    if trades_file is None:
        print(f"\nNo trades export found in {config.DATA_ROOT}")
        print("\nIn NinjaTrader:")
        print("  Strategy Analyzer -> run the backtest -> Trades tab")
        print("  -> right-click -> Export... -> save with any name (the")
        print(f"  strategy's name is best) into: {config.DATA_ROOT}")
        return False

    # Each instrument trains in its own folder (multi-chart support).
    instrument = _export_instrument(trades_file)
    if instrument:
        config.set_instrument(instrument)
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        print(f"\nInstrument: {instrument}  ->  {config.DATA_DIR}")

    if not config.BAR_DATA_FILE.exists():
        print(f"\nMissing bar data: {config.BAR_DATA_FILE}")
        print("\nIn NinjaTrader: open a chart of the SAME instrument and")
        print("timeframe as the backtest, with enough days loaded to cover")
        print("the whole backtest period, and add TOAIExporter with")
        print("ExportBarData = true. Wait for the chart to finish loading.")
        return False

    # Auto-detect the timeframe TOAI is training on (from the chart's bar_data),
    # so a 15-min strategy trained against 1-min bars (or vice-versa) is visible.
    from .merge import timeframe_minutes, consolidate_training_bars
    tf = timeframe_minutes()
    if tf:
        print(f"\nDetected bar_data timeframe: ~{tf:.0f} min "
              f"({config.BAR_DATA_FILE.name})")

    # Train against the FROZEN, full-history bar file (union of every bar ever
    # seen at this timeframe) — so loading 5 days for daily trading never wipes
    # the 600 days the model needs. Live scoring still uses the rolling
    # bar_data.csv; only training reads the consolidated history.
    train_bars = consolidate_training_bars(config.DATA_DIR, verbose=True)

    print(f"\nStep 1/2 — merging {trades_file.name} with {train_bars.name}")
    print("-" * 46)
    out = merge_backtest(trades_file, bar_data_path=train_bars)
    if len(out) == 0:
        print("\nNo trades matched the bar data. Most likely the chart")
        print("history does not cover the backtest dates — reload the chart")
        print("with more days and try again.")
        return False

    print(f"\nStep 2/2 — training on {len(out)} real trades")
    print("-" * 46)
    train()

    # Snapshot this model as a named strategy variant (keeps every variant's
    # model so you can switch between them later without retraining). The
    # export's file name is the variant name; re-training the same name
    # updates that variant.
    from . import variants
    vslug = variants.save_variant(trades_file.stem)
    if vslug:
        print(f"\nSaved strategy variant: {trades_file.stem}")

    # Retroactive display: score every bar in bar_data.csv so the chart
    # shows labels on historical bars and in Playback.
    from .score_history import score_history
    print()
    score_history()

    print("\nDone. Restart the watch window (TOAI_Watch.bat) so it picks")
    print("up the new model, then RELOAD the chart to see historical scores.")
    return True


if __name__ == "__main__":
    build_and_train()
