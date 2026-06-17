"""Strategy-variant model management.

Every trained backtest export is saved BOTH as the live model.pkl AND as a
named snapshot under <instrument>/models/<slug>.pkl, with its metrics recorded
in <instrument>/variants.json. This lets you keep several variants (e.g. the
"1- BBTMP…" and "2- BBTMP…" exports) and switch the active one WITHOUT
retraining.

- Re-training an export with the SAME name updates that variant (same slug).
- A newly trained variant becomes the active model automatically.
- select_variant() copies a saved variant back onto model.pkl and rescores.

Every function takes an optional inst_dir (the instrument's data folder). When
omitted it uses the globally selected instrument (config.MODEL_FILE.parent).
The control panel passes inst_dir explicitly so it can read/delete variants of
any instrument WITHOUT mutating the shared global config that the background
watch thread relies on.
"""
import json
import shutil
from datetime import datetime

import joblib

from . import config


def _dir(inst_dir=None):
    return inst_dir if inst_dir is not None else config.MODEL_FILE.parent


def _models_dir(inst_dir=None):
    d = _dir(inst_dir) / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _registry_path(inst_dir=None):
    return _dir(inst_dir) / "variants.json"


def _load_registry(inst_dir=None) -> dict:
    try:
        return json.loads(_registry_path(inst_dir).read_text())
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save_registry(reg: dict, inst_dir=None):
    _registry_path(inst_dir).write_text(json.dumps(reg, indent=2))


def slug(name: str) -> str:
    """Filesystem-safe key from an export name ('1- BBTMP …' -> '1__BBTMP…')."""
    s = "".join(c if c.isalnum() else "_" for c in name).strip("_")
    return s[:60] or "variant"


def save_variant(export_name: str, inst_dir=None):
    """Snapshot the freshly trained model.pkl as a named variant, mark it the
    active one, and record its metrics. Returns the slug (or None)."""
    model = _dir(inst_dir) / "model.pkl"
    if not model.exists():
        return None
    s = slug(export_name)
    shutil.copy2(model, _models_dir(inst_dir) / f"{s}.pkl")
    b = joblib.load(model)
    wf = b.get("walk_forward") or []
    reg = _load_registry(inst_dir)
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
    _save_registry(reg, inst_dir)
    return s


def list_variants(inst_dir=None):
    """[(slug, info), …] for variants whose model file still exists,
    newest first."""
    md = _models_dir(inst_dir)
    items = [(k, v) for k, v in _load_registry(inst_dir).items()
             if (md / f"{k}.pkl").exists()]
    items.sort(key=lambda kv: kv[1].get("saved", ""), reverse=True)
    return items


def active_variant(inst_dir=None):
    for k, v in _load_registry(inst_dir).items():
        if v.get("active"):
            return k, v
    return None, None


def select_variant(s: str, inst_dir=None, rescore: bool = True) -> bool:
    """Make variant <slug> the active model.pkl and rescore history. When
    rescore is True this uses the GLOBAL config, so call it only from the
    thread that owns the global instrument (the watch), or with the matching
    instrument selected."""
    src = _models_dir(inst_dir) / f"{s}.pkl"
    if not src.exists():
        return False
    shutil.copy2(src, _dir(inst_dir) / "model.pkl")
    reg = _load_registry(inst_dir)
    for k in reg:
        reg[k]["active"] = (k == s)
    _save_registry(reg, inst_dir)
    if rescore:
        try:
            from .score_history import score_history
            score_history()
        except FileNotFoundError:
            pass
    return True


def delete_variant(s: str, inst_dir=None) -> bool:
    """Remove a saved variant (its model snapshot + registry entry). Pure file
    ops — safe to call from any thread. Does not touch the live model.pkl."""
    f = _models_dir(inst_dir) / f"{s}.pkl"
    if f.exists():
        f.unlink()
    reg = _load_registry(inst_dir)
    if s in reg:
        del reg[s]
        _save_registry(reg, inst_dir)
        return True
    return False
