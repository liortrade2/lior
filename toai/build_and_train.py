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


def find_trades_export(strategy_name: str | None = None):
    """Newest trades-export CSV in the data dir, preferring files whose
    name contains the selected strategy's name."""
    candidates = [p for p in config.DATA_DIR.glob("*.csv")
                  if p.name not in _OWN_FILES and _is_trades_export(p)]
    if not candidates:
        return None
    if strategy_name:
        stem = strategy_name.lower().removesuffix(".bbs").strip()
        matching = [p for p in candidates if stem and stem in p.name.lower()]
        if matching:
            candidates = matching
    return max(candidates, key=lambda p: p.stat().st_mtime)


def build_and_train(strategy_name: str | None = None):
    print("=" * 46)
    print("  TOAI — Build training file + train model")
    print("=" * 46)

    trades_file = find_trades_export(strategy_name)
    if trades_file is None:
        print(f"\nNo trades export found in {config.DATA_DIR}")
        print("\nIn NinjaTrader:")
        print("  Strategy Analyzer -> run the backtest -> Trades tab")
        print("  -> right-click -> Export... -> save with any name (the")
        print(f"  strategy's name is best) into: {config.DATA_DIR}")
        return False

    if not config.BAR_DATA_FILE.exists():
        print(f"\nMissing bar data: {config.BAR_DATA_FILE}")
        print("\nIn NinjaTrader: open a chart of the SAME instrument and")
        print("timeframe as the backtest, with enough days loaded to cover")
        print("the whole backtest period, and add TOAIExporter with")
        print("ExportBarData = true. Wait for the chart to finish loading.")
        return False

    print(f"\nStep 1/2 — merging {trades_file.name} with bar_data.csv")
    print("-" * 46)
    out = merge_backtest(trades_file)
    if len(out) == 0:
        print("\nNo trades matched the bar data. Most likely the chart")
        print("history does not cover the backtest dates — reload the chart")
        print("with more days and try again.")
        return False

    print(f"\nStep 2/2 — training on {len(out)} real trades")
    print("-" * 46)
    train()

    print("\nDone. Restart the watch window (TOAI_Watch.bat) so it picks")
    print("up the new model, then check the scores on the chart.")
    return True


if __name__ == "__main__":
    build_and_train()
