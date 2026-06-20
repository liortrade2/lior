"""AI Coach (Phase C) — off-path Claude analysis of the realized journal.

This is the off-path use of Claude the roadmap always intended: NOT in the
per-bar gate (latency / cost / non-determinism rule it out there), but for
post-trade review, a daily summary, and a chat over your real fills — each fed
the ML score and the gate's verdict, so the advice is TOAI-aware in a way no
generic journal coach can be.

Uses the official Anthropic SDK with claude-opus-4-8 and adaptive thinking.
Needs ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) in the environment. The
`anthropic` package is imported lazily so the rest of the dashboard works
without it installed.
"""
from __future__ import annotations

import os

import pandas as pd

try:
    from . import config
except ImportError:
    import pathlib
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from toai import config

MODEL = "claude-opus-4-8"
MAX_TOKENS = 3000

SYSTEM = (
    "You are a disciplined futures-trading coach embedded in TOAI, a local ML "
    "trade-filter for NinjaTrader. Each trade carries an ML score (0-100, the "
    "model's win-probability) and the gate's verdict (ALLOW if score >= the live "
    "threshold, else SKIP). MAE = max adverse excursion, MFE = max favorable "
    "excursion, both in points. The instrument is a CME future.\n\n"
    "Your job: give specific, evidence-grounded, honest feedback. Lead with the "
    "single most important takeaway, then support it. Tie observations to the ML "
    "score where relevant (e.g. did high-score trades behave better?). Be concrete "
    "about exits using MAE/MFE. Do NOT give generic platitudes, do NOT invent data "
    "not present, and do NOT tell the user to trade more or less without evidence. "
    "Keep it tight — a few short paragraphs or a short list, not an essay."
)


def available() -> bool:
    """True when an API credential is present in the environment."""
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _client():
    import anthropic
    return anthropic.Anthropic()


def _digest(ex: pd.DataFrame, instrument, max_rows: int = 60) -> str:
    """Compact, token-light text of the realized trades for the model to read."""
    if ex.empty:
        return "(no realized trades)"
    cols = ["EntryTime", "Direction", "EntryPrice", "ExitPrice", "Profit",
            "MAE", "MFE", "Score", "Verdict", "Variant"]
    have = [c for c in cols if c in ex.columns]
    df = ex[have].tail(max_rows).copy()
    if "EntryTime" in df.columns:
        df["EntryTime"] = pd.to_datetime(df["EntryTime"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")
    lines = [f"Instrument: {instrument}", "Trades (most recent last):",
             "  " + " | ".join(have)]
    for _, r in df.iterrows():
        lines.append("  " + " | ".join("" if pd.isna(r[c]) else str(r[c]) for c in have))
    p = pd.to_numeric(ex["Profit"], errors="coerce").dropna()
    if len(p):
        lines.append(f"\nTotals: {len(p)} trades, net {p.sum():+.2f}, "
                     f"win% {(p > 0).mean() * 100:.0f}, avg {p.mean():+.2f}")
    return "\n".join(lines)


def _ask(messages: list[dict], system: str = SYSTEM) -> str:
    """One non-streaming Claude call; returns the text, or a readable error."""
    try:
        client = _client()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=messages,
        )
        if resp.stop_reason == "refusal":
            return "⚠️ The model declined to answer this request."
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text or "(no response)"
    except ImportError:
        return ("⚠️ The `anthropic` package isn't installed.\n\n"
                "Run:  pip install -r requirements.txt")
    except Exception as e:                       # surface the problem, don't crash the UI
        name = type(e).__name__
        if name == "AuthenticationError":
            return "⚠️ Invalid/missing ANTHROPIC_API_KEY."
        if name == "RateLimitError":
            return "⚠️ Rate limited — try again in a moment."
        return f"⚠️ AI Coach error: {e}"


def daily_summary(ex: pd.DataFrame, instrument) -> str:
    """Coach's read on the most recent trading day's realized fills."""
    if ex.empty:
        return "No realized trades to summarize yet."
    ex = ex.copy()
    ex["EntryTime"] = pd.to_datetime(ex["EntryTime"], errors="coerce")
    last_day = ex["EntryTime"].dt.date.max()
    day = ex[ex["EntryTime"].dt.date == last_day]
    prompt = (f"Here are my realized fills for {last_day}. Give me a daily debrief: "
              f"what went well, what to fix, and whether the ML score tracked outcome.\n\n"
              + _digest(day, instrument))
    return _ask([{"role": "user", "content": prompt}])


def review_trade(row: pd.Series, instrument) -> str:
    """Coach's review of a single trade."""
    fields = {k: row.get(k) for k in
              ("EntryTime", "ExitTime", "Direction", "EntryPrice", "ExitPrice",
               "Profit", "MAE", "MFE", "Score", "Verdict", "Variant", "RMultiple")}
    body = "\n".join(f"  {k}: {v}" for k, v in fields.items() if v is not None and v == v)
    prompt = ("Review this single trade. Was the entry justified given the ML score, "
              "and was the exit good given MAE/MFE? One concrete lesson.\n\n" + body)
    return _ask([{"role": "user", "content": prompt}])


def chat(question: str, ex: pd.DataFrame, instrument, history: list[dict] | None = None) -> str:
    """Free-form Q&A over the realized journal. `history` is prior {role, content}."""
    digest = _digest(ex, instrument)
    msgs = list(history or [])
    msgs.append({"role": "user",
                 "content": f"My journal:\n{digest}\n\nQuestion: {question}"})
    return _ask(msgs)
