"""Build a TOAI install package — a single .zip with everything needed to run
TOAI on a fresh machine, and nothing else (no git, no caches, no trade data).

Run:  python make_installer.py        ->  dist/TOAI_install_<timestamp>.zip

What goes IN (the runtime project):
  * toai/                        the Python package
  * main.py, requirements.txt    entry point + dependencies
  * ninjascript_v4_gauge_tick/   the live indicators to paste into NinjaTrader
  * the TOAI_*.bat launchers      (Control / Menu / Train / Update / Backup)
  * CLAUDE.md, docs/, RESTORE_POINTS.md   docs + handoff
  * INSTALL.md                    generated fresh install steps (see below)

What stays OUT:
  * .git/, .claude/, __pycache__/   dev / local / regenerated
  * any model, score or trade data  (lives in C:\\LIOR_ML, never shipped)
  * ninjascript/ (legacy v1)        the fallback restore point — not needed to
                                    install; it stays in the repo as a safety net
"""
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Explicit allow-list — only these reach the package.
INCLUDE_FILES = [
    "main.py",
    "requirements.txt",
    "CLAUDE.md",
    "RESTORE_POINTS.md",
    "TOAI_Control.bat",
    "TOAI_Playback.bat",
    "TOAI_Menu.bat",
    "TOAI_Train.bat",
    "TOAI_Update.bat",
    "TOAI_Backup.bat",
]
INCLUDE_DIRS = [
    "toai",
    "ninjascript_v4_gauge_tick",
    "docs",
]
# Never package these, even inside an included dir.
EXCLUDE_PARTS = {"__pycache__", ".git", ".claude"}
EXCLUDE_SUFFIXES = {".pkl", ".pyc"}


def _wanted(p: Path) -> bool:
    if any(part in EXCLUDE_PARTS for part in p.parts):
        return False
    return p.suffix.lower() not in EXCLUDE_SUFFIXES


INSTALL_MD = """# TOAI — Installation

## 1. Python side (the ML filter)
1. Install Python 3.10+ (tick "Add Python to PATH").
2. Open a terminal in this folder and run:
       python -m pip install --upgrade pip
       pip install -r requirements.txt
3. Launch the Control Panel:  double-click **TOAI_Control.bat**
   (runs the live watch in-window + scorecard + variant switching).

Other launchers:
  * TOAI_Menu.bat    interactive CLI menu (main.py)
  * TOAI_Train.bat   train from a Strategy Analyzer export
  * TOAI_Update.bat  pull the latest code from GitHub
  * TOAI_Backup.bat  back up C:\\LIOR_ML + NinjaTrader templates + this project

Data lives in **C:\\LIOR_ML** (one sub-folder per instrument). It is created on
first run and is NOT part of this package — nothing to copy.

## 2. NinjaTrader side (the indicators)
From `ninjascript_v4_gauge_tick/`, in the NinjaScript Editor:
  1. New Indicator -> paste each of the three .cs indicators -> F5 (compile):
     TOAIExporterGaugeTick, TOAIGaugeHUD, TOAISignalLabelGaugeTick.
  2. New AddOn -> paste TOAIExecutionLogger.cs -> F5 (logs live fills, install once).
  3. On the chart: add TOAIExporterGaugeTick (ExportBarData=true, ShowTextHud=false),
     TOAIGaugeHUD, and TWO TOAISignalLabelGaugeTick (Long + Short Confidence).
  4. BloodHound solver: gate on **TOAIExporterGaugeTick.MLPass >= 1** for BOTH
     Long and Short. Test in Sim first.

See `docs/PROJECT_STATUS.md` for the full picture.
"""


def build() -> Path:
    files: list[Path] = []
    for name in INCLUDE_FILES:
        p = ROOT / name
        if p.is_file():
            files.append(p)
        else:
            print(f"  ! missing (skipped): {name}")
    for d in INCLUDE_DIRS:
        base = ROOT / d
        if not base.is_dir():
            print(f"  ! missing dir (skipped): {d}")
            continue
        files.extend(p for p in base.rglob("*") if p.is_file() and _wanted(p))

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"TOAI_install_{stamp}.zip"

    # Pack under a top-level "TOAI/" folder so it extracts cleanly.
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, Path("TOAI") / f.relative_to(ROOT))
        z.writestr("TOAI/INSTALL.md", INSTALL_MD)

    size_mb = out.stat().st_size / 1e6
    print(f"\nPackaged {len(files) + 1} files -> {out}  ({size_mb:.2f} MB)")
    print("Copy this .zip to the new machine, extract, and follow INSTALL.md.")
    return out


if __name__ == "__main__":
    build()
