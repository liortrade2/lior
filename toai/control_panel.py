"""TOAI Control Panel — replaces TOAI_Watch.bat with a desktop window.

Runs the watch loop (live scoring + auto-train) in a background thread, and
shows one card per instrument with:
  * a live badge (score + ALLOW / SKIP / CLOSED, window-aware),
  * selectable variant radios with a metrics info row,
  * delete per variant.

The UI thread never mutates the global config: it reads each instrument's
files directly (inst_dir) and hands variant switches to the watch thread via
a queue, so the two threads don't fight over the shared instrument state.

Run:  python -m toai.control_panel   (or main.py option 5)
"""
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from . import config, scorecard, variants
from .score import watch

GREEN, RED, MUTED = "#1b8a3a", "#c0392b", "#8a8a8a"


def _inst_dir(inst):
    return config.DATA_ROOT / inst


def _status(inst):
    """(score|None, verdict, color) for an instrument, read straight from its
    files — no global-config mutation."""
    d = _inst_dir(inst)
    score = None
    try:
        score = float((d / "score.txt").read_text().strip())
    except (OSError, ValueError):
        pass
    threshold = config.get_threshold()
    in_window = True
    try:
        lo, hi = (float(x) for x in (d / "entry_window.txt").read_text().strip().split("-"))
        now_min = datetime.now().hour * 60 + datetime.now().minute
        in_window = lo <= now_min <= hi
    except (OSError, ValueError):
        pass
    if score is None:
        return None, "no score", MUTED
    if not in_window:
        return score, "CLOSED", MUTED
    if score >= threshold:
        return score, "ALLOW", GREEN
    return score, "SKIP", RED


def _money(v):
    return f"{v:+,.2f}"


class ScorecardWindow(tk.Toplevel):
    """Per-instrument Live Scorecard: win-rate + expectancy by score bucket,
    and the ALLOW/SKIP edge at the live threshold. The walk-forward scoring is
    a few seconds of CPU, so it runs in a worker thread and the window fills in
    when it lands — the panel never freezes."""

    def __init__(self, master, inst):
        super().__init__(master)
        self.inst = inst
        self._result = None        # (scorecard|None, err|None), set by the worker
        self.title(f"Live Scorecard — {inst}")
        self.geometry("680x600")
        self.minsize(560, 480)

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text=f"Live Scorecard — {inst}",
                  font=("Segoe UI", 14, "bold")).pack(side="left")
        self.refresh_btn = ttk.Button(top, text="Refresh", command=self._load)
        self.refresh_btn.pack(side="right")

        self.body = ttk.Frame(self, padding=(10, 0, 10, 10))
        self.body.pack(fill="both", expand=True)
        self.status = ttk.Label(self.body, foreground=MUTED,
                                text="Computing walk-forward scorecard…")
        self.status.pack(anchor="w", pady=20)
        self._load()

    def _load(self):
        for w in self.body.winfo_children():
            w.destroy()
        self.status = ttk.Label(self.body, foreground=MUTED,
                                text="Computing walk-forward scorecard…")
        self.status.pack(anchor="w", pady=20)
        self.refresh_btn.config(state="disabled")
        self._result = None
        threading.Thread(target=self._compute, daemon=True).start()
        self.after(150, self._poll)        # poll for the result on the UI thread

    def _compute(self):
        # Worker thread: NEVER touch widgets here (Tkinter is single-threaded).
        # Stash the result; the main thread picks it up in _poll.
        try:
            self._result = (scorecard.scorecard_for_instrument(self.inst), None)
        except Exception as e:        # never let a worker crash take the panel
            self._result = (None, str(e))

    def _poll(self):
        if not self.winfo_exists():
            return
        if self._result is None:
            self.after(150, self._poll)
            return
        sc, err = self._result
        self._render(sc, err)

    def _render(self, sc, err):
        if not self.winfo_exists():
            return
        self.refresh_btn.config(state="normal")
        for w in self.body.winfo_children():
            w.destroy()
        if err is not None:
            ttk.Label(self.body, foreground=RED, wraplength=620,
                      text=f"Could not compute scorecard:\n{err}").pack(anchor="w", pady=20)
            return
        if sc is None:
            ttk.Label(self.body, foreground=MUTED, wraplength=620,
                      text="No scorecard yet — this instrument needs a trained "
                           "model with both winning and losing trades in "
                           "training_data.csv. Train a backtest export first.").pack(
                anchor="w", pady=20)
            return

        basis = ("walk-forward · out-of-sample (honest)" if sc.out_of_sample
                 else "IN-SAMPLE — optimistic, < 150 trades")
        meta = ttk.Frame(self.body)
        meta.pack(fill="x", pady=(4, 8))
        ttk.Label(meta, font=("Consolas", 9), foreground=MUTED,
                  text=f"{sc.n_trades} trades   {sc.date_from} → {sc.date_to}   ·   "
                       f"{basis}   ·   threshold {sc.threshold:g}").pack(anchor="w")
        if not sc.out_of_sample:
            ttk.Label(meta, foreground=RED, font=("Segoe UI", 9, "bold"),
                      text="⚠ Optimistic — collect 150+ trades for the honest "
                           "walk-forward scorecard.").pack(anchor="w")

        # --- bucket table -------------------------------------------------
        ttk.Label(self.body, text="By score bucket",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(6, 2))
        cols = ("score", "n", "win", "exp", "total", "rr")
        tree = ttk.Treeview(self.body, columns=cols, show="headings", height=len(sc.buckets))
        for c, txt, w in (("score", "Score", 80), ("n", "Trades", 70),
                          ("win", "Win %", 70), ("exp", "Expectancy $", 110),
                          ("total", "Total $", 100), ("rr", "R:R", 60)):
            tree.heading(c, text=txt)
            tree.column(c, width=w, anchor="center")
        tree.tag_configure("pos", foreground=GREEN)
        tree.tag_configure("neg", foreground=RED)
        tree.tag_configure("allow", background="#eaf6ec")
        for b in sc.buckets:
            inband = b.lo >= sc.threshold        # bucket the gate lets through
            tags = ("pos" if b.expectancy >= 0 else "neg",) + (("allow",) if inband else ())
            rr = f"{b.rr:.2f}" if b.rr is not None else "—"
            tree.insert("", "end", tags=tags, values=(
                f"{b.lo:g}-{b.hi:g}", b.n, f"{b.win_rate:.0f}%",
                _money(b.expectancy), f"{b.total_pnl:+,.0f}", rr))
        tree.pack(fill="x")
        ttk.Label(self.body, font=("Consolas", 8), foreground=MUTED,
                  text="Green rows = scores at/above the threshold (the gate "
                       "lets these through).").pack(anchor="w", pady=(2, 8))

        # --- gate decision summary ---------------------------------------
        ttk.Label(self.body, text="Gate decision at the live threshold",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(6, 2))
        grid = ttk.Frame(self.body)
        grid.pack(fill="x")
        hdr = ("", "Trades", "Win %", "Expectancy $", "Total $")
        for j, h in enumerate(hdr):
            ttk.Label(grid, text=h, font=("Segoe UI", 9, "bold"),
                      width=18 if j == 0 else 12,
                      anchor="w" if j == 0 else "e").grid(row=0, column=j, padx=4, sticky="w")
        for i, (g, color) in enumerate(((sc.all, MUTED), (sc.allow, GREEN), (sc.skip, RED)), 1):
            ttk.Label(grid, text=g.label, foreground=color,
                      font=("Segoe UI", 9, "bold")).grid(row=i, column=0, padx=4, sticky="w")
            for j, v in enumerate((str(g.n), f"{g.win_rate:.0f}%",
                                   _money(g.expectancy), f"{g.total_pnl:+,.0f}"), 1):
                ttk.Label(grid, text=v, font=("Consolas", 9),
                          anchor="e").grid(row=i, column=j, padx=4, sticky="e")

        # --- the headline: does the filter make money? -------------------
        edge = sc.edge_per_trade
        box = ttk.Frame(self.body, padding=10)
        box.pack(fill="x", pady=(12, 0))
        verdict_color = GREEN if edge > 0 else RED
        ttk.Label(box, foreground=verdict_color, font=("Segoe UI", 12, "bold"),
                  text=f"Edge added per taken trade:  {edge:+.2f} $").pack(anchor="w")
        ttk.Label(box, foreground=MUTED, font=("Segoe UI", 9), wraplength=620,
                  text=f"ALLOW expectancy {sc.allow.expectancy:+.2f} $ vs trading "
                       f"everything {sc.all.expectancy:+.2f} $. The gate skipped "
                       f"{sc.skip.n} trades worth {sc.skip.total_pnl:+,.0f} $ in total"
                       f"{' (a net loss it dodged)' if sc.skip.total_pnl < 0 else ''}."
                  ).pack(anchor="w", pady=(2, 0))


class ControlPanel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TOAI Control Panel")
        self.geometry("740x640")
        self.minsize(580, 420)

        self.stop_event = threading.Event()
        self.reload_event = threading.Event()
        self.switch_queue = queue.Queue()
        self.watch_thread = None
        self.badges = {}        # inst -> ttk.Label
        self.radio_vars = {}    # inst -> tk.StringVar
        self._sig = None

        self._build()
        self.start_watch()
        self.after(300, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- layout ----------
    def _build(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="TOAI control panel",
                  font=("Segoe UI", 15, "bold")).pack(side="left")

        ttk.Button(top, text="Set", width=4, command=self._set_threshold).pack(side="right")
        self.thr_var = tk.StringVar(value=f"{config.get_threshold():g}")
        ttk.Entry(top, textvariable=self.thr_var, width=5).pack(side="right", padx=(0, 4))
        ttk.Label(top, text="min score").pack(side="right", padx=(8, 4))
        self.watch_btn = ttk.Button(top, text="Stop watch", width=11, command=self._toggle_watch)
        self.watch_btn.pack(side="right", padx=10)
        self.watch_lbl = ttk.Label(top, text="● running", foreground=GREEN)
        self.watch_lbl.pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.canvas = tk.Canvas(body, highlightthickness=0)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw", width=700)
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        self._rebuild()

    def _signature(self):
        sig = []
        for inst in config.list_instruments():
            vs = variants.list_variants(_inst_dir(inst))
            sig.append((inst, tuple((s, v.get("active")) for s, v in vs)))
        return tuple(sig)

    def _rebuild(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.badges.clear()
        self.radio_vars.clear()
        insts = config.list_instruments()
        if not insts:
            ttk.Label(self.inner, wraplength=660,
                      text="No instruments yet — open a chart with the TOAI exporter "
                           "and a data folder appears under C:\\LIOR_ML.").pack(anchor="w", pady=24)
        for inst in insts:
            self._card(inst)
        self._sig = self._signature()

    def _card(self, inst):
        d = _inst_dir(inst)
        card = ttk.LabelFrame(self.inner, text=f" {inst} ", padding=8)
        card.pack(fill="x", pady=6)

        head = ttk.Frame(card)
        head.pack(fill="x")
        badge = ttk.Label(head, text="—", font=("Consolas", 12, "bold"), foreground=MUTED)
        badge.pack(side="right")
        self.badges[inst] = badge
        ttk.Button(head, text="📊 Scorecard", width=12,
                   command=lambda i=inst: self._scorecard(i)).pack(side="right", padx=(0, 10))

        vs = variants.list_variants(d)
        if not vs:
            ttk.Label(card, foreground=MUTED, wraplength=620,
                      text="No variants yet — drop a backtest export into "
                           "C:\\LIOR_ML and it trains automatically.").pack(anchor="w", pady=(6, 0))
            return

        active, _ = variants.active_variant(d)
        rv = tk.StringVar(value=active or "")
        self.radio_vars[inst] = rv
        for s, info in vs:
            row = ttk.Frame(card)
            row.pack(fill="x", pady=3)
            ttk.Radiobutton(row, value=s, variable=rv,
                            command=lambda i=inst, sl=s: self._activate(i, sl)).pack(side="left")
            txt = ttk.Frame(row)
            txt.pack(side="left", fill="x", expand=True)
            tag = "   ← active" if info.get("active") else ""
            ttk.Label(txt, text=info["name"][:55] + tag,
                      font=("Segoe UI", 10, "bold")).pack(anchor="w")
            ttk.Label(txt, foreground=MUTED, font=("Consolas", 8),
                      text=f"PMV {info.get('pmv')}  ·  WF {info.get('wf_mean')}  ·  "
                           f"saved {info.get('saved')}").pack(anchor="w")
            ttk.Button(row, text="✕", width=3,
                       command=lambda i=inst, sl=s, n=info["name"]: self._delete(i, sl, n)).pack(side="right")

    # ---------- actions ----------
    def _activate(self, inst, s):
        # Hand the switch to the watch thread (it owns the global config and
        # will rescore + reload the model). UI stays responsive.
        self.switch_queue.put((inst, s))
        self.after(1500, self._rebuild)   # reflect the new [active] tag

    def _delete(self, inst, s, name):
        if not messagebox.askyesno("Delete variant", f"Delete this saved variant?\n\n{name}"):
            return
        variants.delete_variant(s, _inst_dir(inst))
        self._rebuild()

    def _set_threshold(self):
        try:
            config.set_threshold(float(self.thr_var.get()))
        except ValueError:
            messagebox.showwarning("TOAI", "Threshold must be a number 0-100.")

    def _scorecard(self, inst):
        ScorecardWindow(self, inst)

    def _toggle_watch(self):
        if self.watch_thread and self.watch_thread.is_alive():
            self.stop_event.set()
            self.watch_btn.config(text="Start watch")
            self.watch_lbl.config(text="● stopped", foreground=RED)
        else:
            self.start_watch()

    def start_watch(self):
        self.stop_event = threading.Event()
        self.watch_thread = threading.Thread(
            target=lambda: watch(stop_event=self.stop_event,
                                  reload_event=self.reload_event,
                                  switch_queue=self.switch_queue),
            daemon=True)
        self.watch_thread.start()
        self.watch_btn.config(text="Stop watch")
        self.watch_lbl.config(text="● running", foreground=GREEN)

    # ---------- periodic refresh ----------
    def _tick(self):
        for inst, badge in self.badges.items():
            score, verdict, color = _status(inst)
            text = f"{score:.0f}%  {verdict}" if score is not None else verdict
            badge.config(text=text, foreground=color)
        try:
            if self._signature() != self._sig:
                self._rebuild()
        except Exception:
            pass
        self.after(1500, self._tick)

    def _on_close(self):
        self.stop_event.set()
        self.destroy()


def main():
    ControlPanel().mainloop()


if __name__ == "__main__":
    main()
