"""TOAI configuration — paths, features, thresholds."""
import os
import platform
from pathlib import Path

# On the trading machine (Windows) NinjaTrader writes to C:\LIOR_ML.
# Anywhere else (development, testing) we use a local ./data directory.
if platform.system() == "Windows":
    DATA_DIR = Path(os.environ.get("TOAI_DATA_DIR", r"C:\LIOR_ML"))
    TEMPLATES_DIR = Path(os.environ.get(
        "TOAI_TEMPLATES_DIR",
        Path.home() / "Documents" / "NinjaTrader 8" / "templates" / "BlackBird"))
else:
    DATA_DIR = Path(os.environ.get("TOAI_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    TEMPLATES_DIR = Path(os.environ.get(
        "TOAI_TEMPLATES_DIR", Path(__file__).resolve().parent.parent / "templates"))

TRAINING_FILE = DATA_DIR / "training_data.csv"
BAR_DATA_FILE = DATA_DIR / "bar_data.csv"
TRADE_LOG_FILE = DATA_DIR / "trade_log.csv"
CURRENT_FEATURES_FILE = DATA_DIR / "current_features.csv"
MODEL_FILE = DATA_DIR / "model.pkl"
SCORE_FILE = DATA_DIR / "score.txt"
BAR_SCORES_FILE = DATA_DIR / "bar_scores.csv"
THRESHOLD_FILE = DATA_DIR / "threshold.txt"

# The 11 features from the LIOR Quant System build map.
# Names must match the CSV header written by the NinjaScript Exporter.
FEATURES = [
    "ATR20",                # Volatility 1D
    "EMA9",                 # Trend 2C
    "EMA20",
    "EMA50",
    "RSI14",                # Momentum 3A
    "ADX14",                # Trend 1C
    "Distance_SwingHigh",   # S/R 1B1
    "Distance_SwingLow",    # S/R 1B2
    "Volume_Ratio",         # Volume 1E (Volume / SMA20)
    "BBand_Width",          # Momentum 4A
    "ZScore",               # Location
]

TARGET_COLUMN = "PnL"       # target = PnL > 0

# Probability of Win Minimum — trades scoring below this are skipped.
#
# Single source of truth: threshold.txt in the data dir. The GUI panel
# writes it, and EVERY consumer reads it — the Python watch, TOAIExporter
# on the chart, TOAISignalLabel, and BloodHound's internal copy of
# TOAIExporter. Change it in ONE place (the panel) and all stay in sync.
DEFAULT_THRESHOLD = 55.0


def get_threshold() -> float:
    """Current threshold from threshold.txt (DEFAULT_THRESHOLD if missing)."""
    try:
        return float(THRESHOLD_FILE.read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return DEFAULT_THRESHOLD


def set_threshold(value: float) -> float:
    """Write the threshold everyone reads. Returns the stored value."""
    value = float(value)
    if not 0 <= value <= 100:
        raise ValueError("Threshold must be between 0 and 100.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    THRESHOLD_FILE.write_text(f"{value:g}")
    global MIN_PROBABILITY_THRESHOLD
    MIN_PROBABILITY_THRESHOLD = value
    return value


MIN_PROBABILITY_THRESHOLD = get_threshold()

TEST_SIZE = 0.3
RANDOM_STATE = 42
