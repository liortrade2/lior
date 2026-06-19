"""Start-of-day / end-of-day routines, shared by the Control Panel buttons and
the scheduled .bat scripts (TOAI_StartDay.bat / TOAI_EndDay.bat).

  START OF DAY:  clear NinjaTrader's data cache -> launch NinjaTrader.
                 (the scheduled .bat also launches the Control Panel.)
  END OF DAY:    save the Edgewonk journal files -> close NinjaTrader.

NinjaTrader is found at TOAI_NT_EXE, else the usual install paths. Closing is
GRACEFUL by default (a normal close request, never a force-kill of a live
trading app) — pass force=True only if you accept an abrupt termination.
"""
import os
import platform
import subprocess
from pathlib import Path

from . import ninja_cache

NT_PROCESS = "NinjaTrader.exe"
_NT_PATHS = (
    r"C:\Program Files\NinjaTrader 8\bin\NinjaTrader.exe",
    r"C:\Program Files (x86)\NinjaTrader 8\bin\NinjaTrader.exe",
)


def nt_exe():
    """Path to NinjaTrader.exe (TOAI_NT_EXE env wins), or None if not found."""
    env = os.environ.get("TOAI_NT_EXE")
    if env and Path(env).exists():
        return env
    for c in _NT_PATHS:
        if Path(c).exists():
            return c
    return None


def is_nt_running() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {NT_PROCESS}"],
                             capture_output=True, text=True, timeout=15)
        return NT_PROCESS.lower() in (out.stdout or "").lower()
    except Exception:
        return False


def launch_ninjatrader() -> str:
    exe = nt_exe()
    if not exe:
        raise FileNotFoundError(
            "NinjaTrader.exe not found — set the TOAI_NT_EXE environment variable.")
    subprocess.Popen([exe], cwd=str(Path(exe).parent))
    return exe


def close_ninjatrader(force: bool = False) -> dict:
    """Ask NinjaTrader to close (graceful). force=True hard-kills it — avoid on
    a live account. Returns {closed, detail}."""
    if platform.system() != "Windows":
        return {"closed": False, "detail": "not Windows"}
    if not is_nt_running():
        return {"closed": False, "detail": "not running"}
    cmd = ["taskkill", "/IM", NT_PROCESS] + (["/F"] if force else [])
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {"closed": out.returncode == 0,
                "detail": (out.stdout or out.stderr or "").strip()}
    except Exception as e:
        return {"closed": False, "detail": str(e)}


def start_of_day(clear_cache: bool = True, launch: bool = True) -> dict:
    """Clear the NT data cache (NT should be CLOSED), then launch NinjaTrader."""
    res = {"cache": None, "launched": None, "errors": []}
    if clear_cache:
        if is_nt_running():
            res["errors"].append("NinjaTrader is running — close it for a full "
                                  "cache clear (locked files were skipped).")
        res["cache"] = ninja_cache.clear_cache()
    if launch:
        try:
            res["launched"] = launch_ninjatrader()
        except Exception as e:
            res["errors"].append(str(e))
    return res


def end_of_day(export: bool = True, close: bool = True,
               force_close: bool = False) -> dict:
    """Save the Edgewonk journal files, then close NinjaTrader."""
    res = {"exported": [], "closed": None, "errors": []}
    if export:
        try:
            from . import edgewonk
            done = edgewonk.export_active_all(force=True)
            res["exported"] = [(i, str(o)) for i, o, _ in done if o is not None]
        except Exception as e:
            res["errors"].append(f"edgewonk: {e}")
    if close:
        res["closed"] = close_ninjatrader(force=force_close)
    return res


if __name__ == "__main__":
    import sys
    what = sys.argv[1].lower() if len(sys.argv) > 1 else "start"
    if what.startswith("start"):
        r = start_of_day()
        c = r["cache"]
        if c:
            print(f"Cache cleared: {c['removed']} items, {c['freed_mb']:.1f} MB")
        print(f"NinjaTrader launched: {r['launched']}")
    elif what.startswith("end"):
        r = end_of_day()
        print(f"Edgewonk saved for {len(r['exported'])} instrument(s)")
        print(f"NinjaTrader close: {r['closed']}")
    else:
        print("usage: python -m toai.routines [start|end]")
    for e in r["errors"]:
        print("  !", e)
