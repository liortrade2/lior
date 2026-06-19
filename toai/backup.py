"""Automatic model backup (roadmap #7) — runs after every train so a disk
failure never loses the trained models/variants (which live only in the data
root, not git). Snapshots are timestamped and pruned to the last N.

Destination: TOAI_BACKUP_DIR env var, else D:\\TOAI_Backups if a D: drive is
present (the user's backup disk), else <data root>\\_backups.
"""
import os
import platform
import shutil
from datetime import datetime
from pathlib import Path

from . import config

# Only the model artifacts — never bar_data / journal / executions / raw exports.
_FILES = ("model.pkl", "variants.json", "threshold.txt", "train_tf.txt",
          "bar_data_tf.txt", "entry_window.txt", "entry_window_manual.txt")
_KEEP = 12   # how many timestamped snapshots to retain


def backup_root() -> Path:
    env = os.environ.get("TOAI_BACKUP_DIR")
    if env:
        return Path(env)
    if platform.system() == "Windows" and Path("D:/").exists():
        return Path(r"D:\TOAI_Backups")
    return config.DATA_ROOT / "_backups"


def backup_instrument(inst_dir=None, verbose: bool = True) -> Path | None:
    """Snapshot one instrument's models/variants into a timestamped folder."""
    inst_dir = Path(inst_dir) if inst_dir else config.MODEL_FILE.parent
    if not inst_dir.is_dir():
        return None
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest = backup_root() / stamp / inst_dir.name
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for f in _FILES:
            if (inst_dir / f).exists():
                shutil.copy2(inst_dir / f, dest / f)
        if (inst_dir / "models").is_dir():
            shutil.copytree(inst_dir / "models", dest / "models", dirs_exist_ok=True)
    except OSError as e:
        if verbose:
            print(f"(backup skipped: {e})")
        return None
    _prune()
    if verbose:
        print(f"Backup -> {dest}")
    return dest


def _prune(keep: int = _KEEP):
    root = backup_root()
    try:
        stamps = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return
    for old in stamps[:-keep]:
        shutil.rmtree(old, ignore_errors=True)
