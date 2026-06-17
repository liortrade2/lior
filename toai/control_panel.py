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

    def refresh(self):
        """Recompute and redraw (used by the Refresh button and when the panel
        re-raises an already-open window)."""
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

        # --- expectancy-by-bucket chart ----------------------------------
        ttk.Label(self.body, text="Expectancy by score bucket  ($ per trade)",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(6, 2))
        self._bucket_chart(self.body, sc).pack(fill="x")
        ttk.Label(self.body, font=("Consolas", 8), foreground=MUTED,
                  text="Green band = scores ≥ threshold (the gate lets these "
                       "through). Bars are $ expectancy; zero line in the "
                       "middle.").pack(anchor="w", pady=(2, 8))

        # --- gate decision summary ---------------------------------------
        ttk.Label(self.body, text="Gate decision at the live threshold",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(6, 2))
        grid = ttk.Frame(self.body)
        grid.pack(fill="x")
        hdr = ("", "Trades", "Win %", "Expectancy $", "Total $", "PF")
        for j, h in enumerate(hdr):
            ttk.Label(grid, text=h, font=("Segoe UI", 9, "bold"),
                      width=18 if j == 0 else 11,
                      anchor="w" if j == 0 else "e").grid(row=0, column=j, padx=4, sticky="w")
        for i, (g, color) in enumerate(((sc.all, MUTED), (sc.allow, GREEN), (sc.skip, RED)), 1):
            ttk.Label(grid, text=g.label, foreground=color,
                      font=("Segoe UI", 9, "bold")).grid(row=i, column=0, padx=4, sticky="w")
            pf = f"{g.profit_factor:.2f}" if g.profit_factor is not None else "—"
            for j, v in enumerate((str(g.n), f"{g.win_rate:.0f}%",
                                   _money(g.expectancy), f"{g.total_pnl:+,.0f}", pf), 1):
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
                  text=f"ALLOW expectancy {sc.allow.expectancy:+.2f} $ "
                       f"(PF {sc.allow.profit_factor:.2f}) vs trading everything "
                       f"{sc.all.expectancy:+.2f} $ (PF {sc.all.profit_factor:.2f}). "
                       f"The gate takes {sc.selectivity:.0f}% of trades and skipped "
                       f"{sc.skip.n} worth {sc.skip.total_pnl:+,.0f} $"
                       f"{' (a net loss it dodged)' if sc.skip.total_pnl < 0 else ''}."
                  ).pack(anchor="w", pady=(2, 0))

    # ---------- chart ----------
    def _bucket_chart(self, parent, sc):
        """A diverging horizontal bar chart of $ expectancy per score bucket:
        bars grow right (green) for positive expectancy, left (red) for
        negative, from a central zero line. The ALLOW band (scores at/above the
        threshold) is shaded so the gate's cut is visible at a glance."""
        buckets = sc.buckets
        row_h, top_pad = 30, 10
        W = 640
        H = top_pad * 2 + row_h * len(buckets)
        label_w, val_w = 56, 168
        x0, x1 = label_w, W - val_w
        mid = (x0 + x1) / 2
        span = (x1 - x0) / 2 - 6
        maxabs = max((abs(b.expectancy) for b in buckets), default=1.0) or 1.0

        c = tk.Canvas(parent, width=W, height=H, highlightthickness=0,
                      bg=self.cget("bg"))
        # ALLOW band behind everything.
        for i, b in enumerate(buckets):
            if b.lo >= sc.threshold:
                y = top_pad + i * row_h
                c.create_rectangle(0, y, W, y + row_h, fill="#eaf6ec", width=0)
        # Zero line.
        c.create_line(mid, top_pad - 2, mid, H - top_pad + 2, fill="#b0b0b0")
        for i, b in enumerate(buckets):
            yc = top_pad + i * row_h + row_h / 2
            bar = (b.expectancy / maxabs) * span
            color = GREEN if b.expectancy >= 0 else RED
            c.create_rectangle(mid, yc - 8, mid + bar, yc + 8, fill=color, width=0)
            c.create_text(4, yc, anchor="w", font=("Consolas", 9),
                          text=f"{b.lo:g}-{b.hi:g}")
            c.create_text(x1 + 6, yc, anchor="w", font=("Consolas", 8),
                          fill="#333333",
                          text=f"{b.expectancy:+.2f}$  {b.win_rate:.0f}%  n={b.n}")
        return c


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
        self.scorecards = {}    # inst -> ScorecardWindow (one per instrument)
        self._edge_labels = {}  # inst -> ttk.Label (the at-a-glance edge line)
        self._edge_text = {}    # inst -> (mtime, text, color)  — last computed
        self._edge_inflight = set()
        self._edge_result = {}  # inst -> (mtime, text, color)  — worker -> _tick
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
        # Grab the wheel only while the pointer is over the panel body, so a
        # scorecard popup (or any other window) keeps its own scrolling.
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all(
            "<MouseWheel>", self._on_wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))
        self._rebuild()

    def _on_wheel(self, e):
        self.canvas.yview_scroll(int(-e.delta / 120), "units")

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

        # At-a-glance "does the filter make money?" footer — computed in the
        # background (cached by training_data mtime) and filled in by _tick.
        edge = ttk.Label(card, foreground=MUTED, font=("Consolas", 8),
                         text="filter edge: computing…")
        edge.pack(anchor="w", pady=(4, 0))
        self._edge_labels[inst] = edge
        self._refresh_edge_label(inst)

    # ---------- scorecard edge (background) ----------
    def _training_mtime(self, inst):
        try:
            return (_inst_dir(inst) / "training_data.csv").stat().st_mtime
        except OSError:
            return None

    def _refresh_edge_label(self, inst):
        lbl = self._edge_labels.get(inst)
        if lbl is None:
            return
        mtime = self._training_mtime(inst)
        cached = self._edge_text.get(inst)
        if cached and cached[0] == mtime:                 # same data -> instant
            lbl.config(text=cached[1], foreground=cached[2])
            return
        lbl.config(text="filter edge: computing…", foreground=MUTED)
        if inst not in self._edge_inflight:
            self._edge_inflight.add(inst)
            threading.Thread(target=self._compute_edge, args=(inst, mtime),
                             daemon=True).start()

    def _compute_edge(self, inst, mtime):
        # Worker thread: compute (uses the mtime-keyed cache in scorecard) and
        # stash a display string; _tick paints it on the UI thread.
        try:
            sc = scorecard.scorecard_for_instrument(inst)
            if sc is None:
                text, color = "filter edge: not enough trades yet", MUTED
            else:
                mark = "✓" if sc.edge_per_trade > 0 else "✗"
                pf = (f" PF{sc.allow.profit_factor:.2f}"
                      if sc.allow.profit_factor is not None else "")
                tag = "" if sc.out_of_sample else "  (in-sample)"
                text = (f"{mark} filter edge {sc.edge_per_trade:+.2f}$/trade  ·  "
                        f"ALLOW {sc.allow.win_rate:.0f}%{pf}  ·  "
                        f"takes {sc.selectivity:.0f}%{tag}")
                color = GREEN if sc.edge_per_trade > 0 else RED
        except Exception:
            text, color = "filter edge: n/a", MUTED
        self._edge_result[inst] = (mtime, text, color)

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
        # One scorecard window per instrument: if it's already open, raise and
        # refresh it instead of stacking duplicates.
        win = self.scorecards.get(inst)
        if win is not None and win.winfo_exists():
            win.deiconify()
            win.lift()
            win.focus_force()
            win.refresh()
            return
        self.scorecards[inst] = ScorecardWindow(self, inst)

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
        # Paint any background edge results that have landed.
        for inst in list(self._edge_result.keys()):
            mtime, text, color = self._edge_result.pop(inst)
            self._edge_text[inst] = (mtime, text, color)
            self._edge_inflight.discard(inst)
            lbl = self._edge_labels.get(inst)
            if lbl is not None and lbl.winfo_exists():
                lbl.config(text=text, foreground=color)
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
