"""Playback mode — a second, isolated data root for testing in Market Replay.

Live trading writes to C:\\LIOR_ML; Market Replay (the NinjaTrader "Playback101"
connection) writes to C:\\LIOR_ML_PLAYBACK instead — the v4 indicators route
there when PlaybackMode=true, and the execution logger routes the Playback101
account there automatically. The ENTIRE Python stack (watch, journal,
scorecard, Edgewonk export) then works on the playback root unchanged: just
launch the Control Panel with TOAI_DATA_DIR=C:\\LIOR_ML_PLAYBACK
(see TOAI_Playback.bat).

This module seeds the playback root with the LIVE models so the gate scores
replay bars with the real strategies. It copies model artifacts only — never
the live bar_data / journal / executions (the playback root keeps its own).
"""
import platform
import shutil
from pathlib import Path

from . import config

# Per-instrument model artifacts to mirror live -> playback. Deliberately NOT
# bar_data.csv / training_data.csv / journal.csv / executions.csv — playback
# generates and keeps its own.
_INST_FILES = ("model.pkl", "variants.json", "bar_data_tf.txt",
               "entry_window.txt", "entry_window_manual.txt")


def live_root() -> Path:
    """The LIVE data root, independent of any TOAI_DATA_DIR override (so this
    works even when called from the playback-pointed Control Panel)."""
    if platform.system() == "Windows":
        return Path(r"C:\LIOR_ML")
    return Path(__file__).resolve().parent.parent / "data"


def playback_root() -> Path:
    if platform.system() == "Windows":
        return Path(r"C:\LIOR_ML_PLAYBACK")
    return Path(__file__).resolve().parent.parent / "data_playback"


def _instrument_dirs(root: Path):
    if not root.is_dir():
        return []
    return [p for p in root.iterdir() if p.is_dir()
            and ((p / "model.pkl").exists() or (p / "models").is_dir())]


def sync(live=None, pb=None, verbose: bool = True) -> int:
    """Copy the live models/variants into the playback root so the playback gate
    uses the real strategies. Refreshes models without touching the playback
    root's own bar_data / journal / executions. Returns instruments synced."""
    live = Path(live) if live else live_root()
    pb = Path(pb) if pb else playback_root()
    if live.resolve() == pb.resolve():
        raise ValueError("playback root must differ from the live root")
    pb.mkdir(parents=True, exist_ok=True)

    # One shared threshold to start from (playback can diverge afterwards).
    thr = live / "threshold.txt"
    if thr.exists() and not (pb / "threshold.txt").exists():
        shutil.copy2(thr, pb / "threshold.txt")

    n = 0
    for src in _instrument_dirs(live):
        dst = pb / src.name
        dst.mkdir(parents=True, exist_ok=True)
        for f in _INST_FILES:
            if (src / f).exists():
                shutil.copy2(src / f, dst / f)
        if (src / "models").is_dir():
            shutil.copytree(src / "models", dst / "models", dirs_exist_ok=True)
        n += 1
        if verbose:
            print(f"  synced {src.name} -> {dst}")
    if verbose:
        print(f"Playback models synced: {n} instrument(s) -> {pb}")
        if n == 0:
            print(f"(no trained instruments found in {live})")
    return n


if __name__ == "__main__":
    sync()
