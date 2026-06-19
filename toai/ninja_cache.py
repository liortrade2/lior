"""Clear NinjaTrader's market-data cache (a routine maintenance fix for
corrupt/stale data). Deletes the CONTENTS of db\\cache, db\\day, db\\minute and
db\\tick — never the folders themselves — and reports what was freed.

NinjaTrader re-downloads this data on demand, so it is safe to clear, BUT
NinjaTrader must be CLOSED first or the files are locked (those show up as
errors in the result). Pure file ops, isolated here so the panel button and any
script can reuse it.
"""
import shutil
from pathlib import Path

# The four data caches the user asked to clear. The folders are kept; only
# their contents are removed.
DB_SUBDIRS = ("cache", "day", "minute", "tick")


def nt_db_dir(base=None) -> Path:
    """The NinjaTrader 8 db folder (…\\Documents\\NinjaTrader 8\\db)."""
    if base:
        return Path(base)
    return Path.home() / "Documents" / "NinjaTrader 8" / "db"


def _dir_size(p: Path) -> int:
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def clear_cache(base=None) -> dict:
    """Delete the contents of the four db caches. Returns
    {dir, removed, freed_mb, missing, errors}. Locked files (NinjaTrader still
    open) come back as errors rather than raising."""
    db = nt_db_dir(base)
    removed, freed, missing, errors = 0, 0, [], []
    for sub in DB_SUBDIRS:
        d = db / sub
        if not d.is_dir():
            missing.append(sub)
            continue
        for child in d.iterdir():
            try:
                if child.is_dir():
                    sz = _dir_size(child)
                    shutil.rmtree(child)
                else:
                    sz = child.stat().st_size
                    child.unlink()
                removed += 1
                freed += sz
            except OSError as e:
                errors.append(f"{sub}\\{child.name}: {e.strerror or e}")
    return {"dir": str(db), "removed": removed, "freed_mb": freed / 1e6,
            "missing": missing, "errors": errors}


if __name__ == "__main__":
    r = clear_cache()
    print(f"Cleared {r['removed']} items, freed {r['freed_mb']:.1f} MB from {r['dir']}")
    if r["missing"]:
        print("Missing subfolders:", ", ".join(r["missing"]))
    for e in r["errors"][:10]:
        print("  !", e)
