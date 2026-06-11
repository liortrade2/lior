"""One-click pipeline: real backtest export -> training file -> trained model.

Looks for the Strategy Analyzer trades export at a fixed location
(C:\\LIOR_ML\\trades_export.csv), joins it with bar_data.csv, trains,
and prints the PMV + threshold analysis. Run via TOAI_Train.bat.
"""
from . import config
from .merge import merge_backtest
from .train import train

TRADES_EXPORT_FILE = config.DATA_DIR / "trades_export.csv"


def build_and_train():
    print("=" * 46)
    print("  TOAI — Build training file + train model")
    print("=" * 46)

    if not TRADES_EXPORT_FILE.exists():
        print(f"\nMissing trades export: {TRADES_EXPORT_FILE}")
        print("\nIn NinjaTrader:")
        print("  Strategy Analyzer -> run the backtest -> Trades tab")
        print("  -> right-click -> Export... -> save as:")
        print(f"     {TRADES_EXPORT_FILE}")
        return False

    if not config.BAR_DATA_FILE.exists():
        print(f"\nMissing bar data: {config.BAR_DATA_FILE}")
        print("\nIn NinjaTrader: open a chart of the SAME instrument and")
        print("timeframe as the backtest, with enough days loaded to cover")
        print("the whole backtest period, and add TOAIExporter with")
        print("ExportBarData = true. Wait for the chart to finish loading.")
        return False

    print(f"\nStep 1/2 — merging {TRADES_EXPORT_FILE.name} with bar_data.csv")
    print("-" * 46)
    out = merge_backtest(TRADES_EXPORT_FILE)
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
