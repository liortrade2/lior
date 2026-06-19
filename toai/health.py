"""Model health (roadmap #8) — staleness + live-vs-backtest drift alerts.

Two questions, both answerable from data already on disk:
  * Staleness — how old is the active model? Past STALE_DAYS it should be
    retrained (the golden rule: retrain monthly / after 50 new trades).
  * Drift — does the LIVE realized edge still match the backtest's? Once enough
    real fills are journalled, a live ALLOW expectancy that has collapsed below
    the backtest's is the early warning that the edge has decayed.

Pure reads, no global-config mutation, so the panel can call it per instrument.
"""
from datetime import datetime

from . import config, journal, scorecard, variants

STALE_DAYS = 30        # retrain reminder threshold
MIN_REALIZED = 15      # need this many live fills before judging drift


def _active_info(inst_dir):
    from .merge import live_timeframe
    s, info = variants.active_variant_for_tf(live_timeframe(inst_dir), inst_dir)
    if s is None:
        s, info = variants.active_variant(inst_dir)
    return info or {}


def _age_days(inst_dir):
    saved = _active_info(inst_dir).get("saved")
    try:
        return (datetime.now() - datetime.strptime(saved, "%Y-%m-%d %H:%M")).days
    except (TypeError, ValueError):
        return None


def check(instrument) -> dict:
    """Health for one instrument: staleness + drift, with short messages.
    {stale, age_days, drift: 'ok'|'warn'|None, messages: [...]}."""
    inst_dir = config.DATA_ROOT / instrument if instrument else config.DATA_ROOT
    out = {"instrument": instrument, "stale": False, "age_days": None,
           "drift": None, "messages": []}

    age = _age_days(inst_dir)
    out["age_days"] = age
    if age is not None and age >= STALE_DAYS:
        out["stale"] = True
        out["messages"].append(f"model {age}d old — retrain (>{STALE_DAYS}d)")

    try:
        bt = scorecard.scorecard_for_instrument(instrument)
        rl = journal.live_scorecard_for(instrument, source="live")
    except Exception:
        bt = rl = None
    if bt and rl and rl.allow.n >= MIN_REALIZED:
        be, re = bt.allow.expectancy, rl.allow.expectancy
        # In Playback the "realized" fills are replayed, not real money — so
        # don't label them "live".
        word = "replay" if config.IS_PLAYBACK else "live"
        if re < 0 <= be:
            out["drift"] = "warn"
            out["messages"].append(
                f"{word} edge {re:+.2f}$ vs backtest {be:+.2f}$ — edge gone {word}")
        elif be > 0 and re < be * 0.5:
            out["drift"] = "warn"
            out["messages"].append(
                f"{word} edge {re:+.2f}$ < ½ of backtest {be:+.2f}$ — decaying")
        else:
            out["drift"] = "ok"
    return out


def format_report(instrument) -> str:
    h = check(instrument)
    head = instrument or "root"
    age = f"{h['age_days']}d" if h["age_days"] is not None else "?"
    lines = [f"  {head:<6} | model age {age:<5} | drift {h['drift'] or '—'}"]
    for m in h["messages"]:
        lines.append(f"           ⚠ {m}")
    if not h["messages"]:
        lines.append("           ✓ healthy")
    return "\n".join(lines)


if __name__ == "__main__":
    print("MODEL HEALTH")
    for inst in (config.list_instruments() or [None]):
        print(format_report(inst))
