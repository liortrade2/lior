"""Reset a trading account's history.

Removes every trace of one account from an instrument's store so the calendar,
KPIs, the prop-evaluation tracker AND the "Realized fills" scorecard go back to
a clean slate. Two layers are cleaned, because the dashboard reads from both:

* ``<inst>/executions.csv`` (current session) + ``<inst>/executions_*.csv``
  (per-day archives) — the fills that drive the calendar / KPIs / evaluation.
* ``<inst>/journal.csv`` — one scored row per fill (Score/Verdict), the source
  of the "Realized fills" trade count. The journal has no Account column, so it
  is reconciled by time: a journal row is kept only if a *remaining* execution
  (any account) backs it within 5 minutes — the same nearest-within-5-min join
  the dashboard uses to display trades. Everything else (the reset account's
  rows, plus stale orphans with no backing fill) is dropped.

Safety: every file that changes is first copied to
``DATA_ROOT/_reset_backups/<account>_<timestamp>/`` (mirroring the per-
instrument layout), so a reset is reversible.

Intended for SIM/Demo accounts (NinjaTrader ``Sim101`` …); see ``is_sim``.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config

_SIM_KEYS = ("sim", "demo", "playback")
_TOL = pd.Timedelta(minutes=5)  # journal↔execution match window (matches the UI)


def is_sim(account) -> bool:
    """True for simulation/demo accounts (matched by name, like the dashboard)."""
    al = str(account).lower()
    return any(k in al for k in _SIM_KEYS)


def sim_accounts(accounts) -> list[str]:
    """The subset of `accounts` that look like simulation/demo accounts."""
    return [a for a in accounts if is_sim(a)]


def _instrument_dirs(root: Path):
    """Per-instrument data dirs under root (skip _journal / _reset_backups …)."""
    if not root.exists():
        return
    for p in sorted(root.iterdir()):
        if p.is_dir() and not p.name.startswith(("_", ".")):
            yield p


def _exec_files(inst_dir: Path):
    """Executions files (current + archives) inside one instrument dir."""
    archives = sorted(inst_dir.glob("executions_*.csv"))
    return [f for f in archives + [inst_dir / "executions.csv"] if f.exists()]


def _read_csv(path: Path):
    try:
        return pd.read_csv(path)
    except (OSError, ValueError, pd.errors.EmptyDataError):
        return None


def count_rows(account: str, root: Path | None = None) -> int:
    """Trades the reset would clear: the account's fills, plus — when the account
    has no fills left but stale journal orphans remain — those orphan rows (so a
    half-cleaned state is still resettable from the UI)."""
    root = Path(root or config.DATA_ROOT)
    account = str(account)
    fills = 0
    for inst_dir in _instrument_dirs(root):
        for f in _exec_files(inst_dir):
            df = _read_csv(f)
            if df is not None and "Account" in df.columns:
                fills += int((df["Account"].astype(str) == account).sum())
    if fills:
        return fills
    # No fills for this account anywhere → surface orphaned journal rows (fills
    # gone but journal left behind, e.g. by an older reset) so they're clearable.
    orphans = 0
    for inst_dir in _instrument_dirs(root):
        remaining = _remaining_entry_times(inst_dir, drop_account=None)
        j = _read_csv(inst_dir / "journal.csv")
        if j is not None and "DateTime" in j.columns:
            orphans += int((~_journal_backed(j, remaining)).sum())
    return orphans


def _remaining_entry_times(inst_dir: Path, drop_account: str | None) -> pd.Series:
    """Entry times of all executions in `inst_dir` that would REMAIN after
    dropping `drop_account` (pass None to count everything currently present)."""
    times = []
    for f in _exec_files(inst_dir):
        df = _read_csv(f)
        if df is None or "Entry time" not in df.columns:
            continue
        if drop_account is not None and "Account" in df.columns:
            df = df[df["Account"].astype(str) != str(drop_account)]
        times.append(pd.to_datetime(df["Entry time"], errors="coerce"))
    if not times:
        return pd.Series([], dtype="datetime64[ns]")
    return pd.concat(times, ignore_index=True).dropna()


def _journal_backed(journal: pd.DataFrame, remaining: pd.Series) -> pd.Series:
    """Boolean mask: journal rows backed by a remaining execution (±5 min)."""
    jt = pd.to_datetime(journal["DateTime"], errors="coerce")
    if remaining.empty:
        return pd.Series(False, index=journal.index)
    rem = remaining.to_numpy(dtype="datetime64[ns]")
    backed = []
    for t in jt:
        if pd.isna(t):
            backed.append(False)
        else:
            backed.append(bool((abs(rem - t.to_datetime64()) <= _TOL.to_timedelta64()).any()))
    return pd.Series(backed, index=journal.index)


def reset_account(account: str, root: Path | None = None) -> dict:
    """Remove every fill for `account` and reconcile each instrument's journal,
    backing up changed files first. Returns a summary dict."""
    root = Path(root or config.DATA_ROOT)
    account = str(account)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = root / "_reset_backups" / f"{account}_{stamp}"

    def _backup(f: Path):
        dest = backup / f.relative_to(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)

    removed_fills = 0
    files_changed = 0
    journal_rows_removed = 0

    for inst_dir in _instrument_dirs(root):
        # 1) Strip the account's rows from every executions file.
        for f in _exec_files(inst_dir):
            df = _read_csv(f)
            if df is None or "Account" not in df.columns:
                continue
            mask = df["Account"].astype(str) == account
            if not mask.any():
                continue
            _backup(f)
            removed_fills += int(mask.sum())
            files_changed += 1
            kept = df[~mask]
            if kept.empty:
                f.unlink()
            else:
                kept.to_csv(f, index=False)

        # 2) Reconcile the journal against whatever executions now remain.
        jpath = inst_dir / "journal.csv"
        j = _read_csv(jpath)
        if j is None or "DateTime" not in j.columns or j.empty:
            continue
        remaining = _remaining_entry_times(inst_dir, drop_account=None)
        keep = _journal_backed(j, remaining)
        if keep.all():
            continue  # every journal row still has a backing fill
        _backup(jpath)
        journal_rows_removed += int((~keep).sum())
        kept_j = j[keep]
        if kept_j.empty:
            jpath.unlink()
        else:
            kept_j.to_csv(jpath, index=False)

    return {
        "account": account,
        "removed": removed_fills,
        "journal_removed": journal_rows_removed,
        "files_changed": files_changed,
        "backup": str(backup) if (files_changed or journal_rows_removed) else None,
    }
