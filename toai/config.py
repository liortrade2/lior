"""TOAI configuration — paths, features, thresholds."""
import os
import platform
from pathlib import Path

# On the trading machine (Windows) NinjaTrader writes to C:\LIOR_ML.
# Anywhere else (development, testing) we use a local ./data directory.
if platform.system() == "Windows":
    DATA_ROOT = Path(os.environ.get("TOAI_DATA_DIR", r"C:\LIOR_ML"))
    TEMPLATES_DIR = Path(os.environ.get(
        "TOAI_TEMPLATES_DIR",
        Path.home() / "Documents" / "NinjaTrader 8" / "templates" / "BlackBird"))
else:
    DATA_ROOT = Path(os.environ.get("TOAI_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    TEMPLATES_DIR = Path(os.environ.get(
        "TOAI_TEMPLATES_DIR", Path(__file__).resolve().parent.parent / "templates"))

# Multi-instrument layout: every instrument gets its own subdirectory under
# DATA_ROOT (C:\LIOR_ML\ES, C:\LIOR_ML\NQ, ...) holding its bar data, model
# and scores — so several charts run side by side without overwriting each
# other. TOAIExporter picks the folder from the chart's instrument; here the
# active folder is selected with set_instrument(). INSTRUMENT = None keeps
# the legacy single-instrument layout (everything directly in the root).
# threshold.txt always stays at the ROOT — one threshold for all charts.
INSTRUMENT = os.environ.get("TOAI_INSTRUMENT") or None

# PLAYBACK vs LIVE. TOAI_Playback.bat points DATA_ROOT at C:\LIOR_ML_PLAYBACK
# (NinjaTrader Market Replay / Playback101). Everything the panel shows then
# comes from replayed history, NOT real fills — so the UI must say so and must
# not call replay results "live". Detected purely from the root path.
IS_PLAYBACK = "PLAYBACK" in str(DATA_ROOT).upper()
MODE_LABEL = "PLAYBACK" if IS_PLAYBACK else "LIVE"

THRESHOLD_FILE = DATA_ROOT / "threshold.txt"
# Manual training-timeframe override (None/"auto" = auto-detect from the export
# file name "…Xmin…", falling back to the chart's current TF). Set from the
# Control Panel when experimenting across timeframes; lives at the ROOT.
TRAIN_TF_FILE = DATA_ROOT / "train_tf.txt"


def get_train_tf(inst_dir=None):
    """Training-TF override (int minutes) for the next training, or None =
    auto-detect. PER-INSTRUMENT: reads <inst_dir>/train_tf.txt first, then the
    root train_tf.txt as a global default — so MES can train as 2-min while MNQ
    trains as 5-min. inst_dir=None uses the currently selected instrument."""
    base = inst_dir if inst_dir is not None else DATA_DIR
    for p in (base / "train_tf.txt", TRAIN_TF_FILE):
        try:
            v = p.read_text().strip().lower()
        except (FileNotFoundError, OSError):
            continue
        if v in ("", "auto"):
            return None
        try:
            return int(float(v))
        except ValueError:
            return None
    return None


def set_train_tf(tf, inst_dir=None):
    """Persist the per-instrument training-TF override ('auto'/None to clear)."""
    base = inst_dir if inst_dir is not None else DATA_DIR
    base.mkdir(parents=True, exist_ok=True)
    (base / "train_tf.txt").write_text(
        "auto" if tf in (None, "auto") else str(int(tf)))


def set_instrument(name: str | None):
    """Point all data paths at DATA_ROOT/<name> (None = the root itself)."""
    global INSTRUMENT, DATA_DIR, TRAINING_FILE, BAR_DATA_FILE, TRADE_LOG_FILE, \
        CURRENT_FEATURES_FILE, MODEL_FILE, SCORE_FILE, BAR_SCORES_FILE
    INSTRUMENT = name or None
    DATA_DIR = DATA_ROOT / INSTRUMENT if INSTRUMENT else DATA_ROOT
    TRAINING_FILE = DATA_DIR / "training_data.csv"
    BAR_DATA_FILE = DATA_DIR / "bar_data.csv"
    TRADE_LOG_FILE = DATA_DIR / "trade_log.csv"
    CURRENT_FEATURES_FILE = DATA_DIR / "current_features.csv"
    MODEL_FILE = DATA_DIR / "model.pkl"
    SCORE_FILE = DATA_DIR / "score.txt"
    BAR_SCORES_FILE = DATA_DIR / "bar_scores.csv"


set_instrument(INSTRUMENT)


def _parse_minutes(s: str) -> float:
    """'9:30' -> 570; plain numbers pass through as minutes."""
    s = s.strip()
    if ":" in s:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    return float(s)


def resolve_entry_window(auto_window):
    """entry_window_manual.txt (hand-edited, '9:30-16:00' or minutes, in the
    chart clock = true US Eastern, the same clock as the BlackBird scheduler)
    overrides the window auto-derived from the backtest's entry times. For an
    RTH strategy set it to 9:30-16:00 to gate the whole session rather than
    only the bars where trades happened to fire."""
    manual = MODEL_FILE.parent / "entry_window_manual.txt"
    try:
        lo, hi = manual.read_text().strip().split("-")
        return (_parse_minutes(lo), _parse_minutes(hi))
    except (FileNotFoundError, ValueError, OSError):
        return auto_window


def write_entry_window(window):
    """Publish the resolved window for NinjaScript in chart-clock minutes.
    NinjaTrader stamps are already DST-aware US Eastern, so the indicators
    compare it directly against each bar's time (no timezone conversion)."""
    if window:
        (MODEL_FILE.parent / "entry_window.txt").write_text(
            f"{window[0]:g}-{window[1]:g}")


def list_instruments() -> list[str]:
    """Instrument subdirectories under DATA_ROOT that contain TOAI data."""
    if not DATA_ROOT.is_dir():
        return []
    return sorted(
        p.name for p in DATA_ROOT.iterdir()
        if p.is_dir() and any((p / f).exists() for f in
                              ("current_features.csv", "bar_data.csv", "model.pkl")))

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


def get_threshold(inst_dir=None) -> float:
    """Passing score. PER-INSTRUMENT: <inst_dir>/threshold.txt first, then the
    root threshold.txt as the global default (DEFAULT_THRESHOLD if neither).
    inst_dir=None reads the global. So MES and MNQ can run different gates while
    instruments without their own file follow the global one."""
    paths = []
    if inst_dir is not None:
        paths.append(Path(inst_dir) / "threshold.txt")
    paths.append(THRESHOLD_FILE)
    for p in paths:
        try:
            return float(p.read_text().strip())
        except (FileNotFoundError, ValueError, OSError):
            continue
    return DEFAULT_THRESHOLD


def set_threshold(value: float, inst_dir=None) -> float:
    """Write the threshold. inst_dir=None -> global root threshold (the default
    for all instruments); inst_dir -> that instrument's own threshold."""
    value = float(value)
    if not 0 <= value <= 100:
        raise ValueError("Threshold must be between 0 and 100.")
    base = Path(inst_dir) if inst_dir is not None else DATA_ROOT
    base.mkdir(parents=True, exist_ok=True)
    (base / "threshold.txt").write_text(f"{value:g}")
    if inst_dir is None:
        global MIN_PROBABILITY_THRESHOLD
        MIN_PROBABILITY_THRESHOLD = value
    return value


MIN_PROBABILITY_THRESHOLD = get_threshold()

TEST_SIZE = 0.3
RANDOM_STATE = 42
