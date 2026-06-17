"""Strategy-variant model management.

Every trained backtest export is saved BOTH as the live model.pkl AND as a
named snapshot under <instrument>/models/<slug>.pkl, with its metrics recorded
in <instrument>/variants.json. This lets you keep several variants (e.g. the
"1- BBTMP…" and "2- BBTMP…" exports) and switch the active one WITHOUT
retraining.

- Re-training an export with the SAME name updates that variant (same slug).
- A newly trained variant becomes the active model automatically.
- select_variant() copies a saved variant back onto model.pkl and rescores.
"""
import json
import shutil
from datetime import datetime

import joblib

from . import config


def _models_dir():
    d = config.MODEL_FILE.parent / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _registry_path():
    return config.MODEL_FILE.parent / "variants.json"


def _load_registry() -> dict:
    try:
        return json.loads(_registry_path().read_text())
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save_registry(reg: dict):
    _registry_path().write_text(json.dumps(reg, indent=2))


def slug(name: str) -> str:
    """Filesystem-safe key from an export name ('1- BBTMP …' -> '1__BBTMP…')."""
    s = "".join(c if c.isalnum() else "_" for c in name).strip("_")
    return s[:60] or "variant"


def save_variant(export_name: str):
    """Snapshot the freshly trained model.pkl as a named variant, mark it the
    active one, and record its metrics. Returns the slug (or None)."""
    if not config.MODEL_FILE.exists():
        return None
    s = slug(export_name)
    shutil.copy2(config.MODEL_FILE, _models_dir() / f"{s}.pkl")
    b = joblib.load(config.MODEL_FILE)
    wf = b.get("walk_forward") or []
    reg = _load_registry()
    for k in reg:
        reg[k]["active"] = False
    reg[s] = {
        "name": export_name,
        "saved": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pmv": round(float(b.get("pmv", 0)), 4),
        "wf_mean": round(sum(wf) / len(wf), 4) if wf else None,
        "wf": [round(a, 3) for a in wf] if wf else None,
        "active": True,
    }
    _save_registry(reg)
    return s


def list_variants():
    """[(slug, info), …] for variants whose model file still exists,
    newest first."""
    md = _models_dir()
    items = [(k, v) for k, v in _load_registry().items()
             if (md / f"{k}.pkl").exists()]
    items.sort(key=lambda kv: kv[1].get("saved", ""), reverse=True)
    return items


def active_variant():
    for k, v in _load_registry().items():
        if v.get("active"):
            return k, v
    return None, None


def select_variant(s: str, rescore: bool = True) -> bool:
    """Make variant <slug> the active model.pkl and rescore history."""
    src = _models_dir() / f"{s}.pkl"
    if not src.exists():
        return False
    shutil.copy2(src, config.MODEL_FILE)
    reg = _load_registry()
    for k in reg:
        reg[k]["active"] = (k == s)
    _save_registry(reg)
    if rescore:
        try:
            from .score_history import score_history
            score_history()
        except FileNotFoundError:
            pass
    return True


def delete_variant(s: str) -> bool:
    """Remove a saved variant (its model snapshot + registry entry). Does not
    touch the live model.pkl."""
    f = _models_dir() / f"{s}.pkl"
    if f.exists():
        f.unlink()
    reg = _load_registry()
    if s in reg:
        del reg[s]
        _save_registry(reg)
        return True
    return False
