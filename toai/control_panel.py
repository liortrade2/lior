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

from . import config, journal, scorecard, variants
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
        self._scored = None        # cached out-of-fold scores (for slider/equity)
        self._rec = None           # threshold recommendation
        self._path = scorecard.training_file_for(inst)
        self._preview = tk.IntVar(value=int(round(config.get_threshold())))
        self._slider_job = None
        self._realized = False     # False = predicted (walk-forward); True = journal
        self.title(f"Live Scorecard — {inst}")
        self.geometry("720x860")
        self.minsize(600, 520)

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text=f"Live Scorecard — {inst}",
                  font=("Segoe UI", 14, "bold")).pack(side="left")
        self.refresh_btn = ttk.Button(top, text="Refresh", command=self._load)
        self.refresh_btn.pack(side="right")
        self.mode_btn = ttk.Button(top, text="Show: Realized fills",
                                   command=self._toggle_mode)
        self.mode_btn.pack(side="right", padx=(0, 8))

        # Scrollable body — the card is taller than one screen now.
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(outer, highlightthickness=0, bg=self.cget("bg"))
        sb = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self.body = ttk.Frame(self._canvas, padding=(10, 0, 10, 10))
        self.body.bind("<Configure>", lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.create_window((0, 0), window=self.body, anchor="nw")
        self._canvas.configure(yscrollcommand=sb.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._canvas.bind("<Enter>", lambda e: self._canvas.bind_all(
            "<MouseWheel>", lambda ev: self._canvas.yview_scroll(
                int(-ev.delta / 120), "units")))
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))

        self.status = ttk.Label(self.body, foreground=MUTED,
                                text="Computing walk-forward scorecard…")
        self.status.pack(anchor="w", pady=20)
        self._load()

    def refresh(self):
        """Recompute and redraw (used by the Refresh button and when the panel
        re-raises an already-open window)."""
        self._load()

    def _toggle_mode(self):
        self._realized = not self._realized
        self.mode_btn.config(text="Show: Walk-forward" if self._realized
                             else "Show: Realized fills")
        self._load()

    def _load(self):
        for w in self.body.winfo_children():
            w.destroy()
        msg = ("Loading realized fills…" if self._realized
               else "Computing walk-forward scorecard…")
        self.status = ttk.Label(self.body, foreground=MUTED, text=msg)
        self.status.pack(anchor="w", pady=20)
        self.refresh_btn.config(state="disabled")
        self._result = None
        threading.Thread(target=self._compute, daemon=True).start()
        self.after(150, self._poll)        # poll for the result on the UI thread

    def _compute(self):
        # Worker thread: NEVER touch widgets here (Tkinter is single-threaded).
        # Stash the result; the main thread picks it up in _poll.
        try:
            if self._realized:
                self._result = (journal.live_scorecard_for(self.inst), None)
            else:
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
            msg = ("No live fills journalled yet — they appear here as the watch "
                   "logs executed trades from <instrument>\\executions.csv. Trade "
                   "in Sim/live and they accumulate." if self._realized else
                   "No scorecard yet — this instrument needs a trained model with "
                   "both winning and losing trades in training_data.csv. Train a "
                   "backtest export first.")
            ttk.Label(self.body, foreground=MUTED, wraplength=620,
                      text=msg).pack(anchor="w", pady=20)
            return

        # Cache the scored trades + threshold recommendation so the slider and
        # equity curve recompute instantly. Source depends on the mode: the
        # journal's realized fills, or the walk-forward out-of-fold scores.
        if self._realized:
            self._scored = journal.live_scored_for(self.inst)
        else:
            st = scorecard.score_trades(self._path)
            self._scored = st.scored if st else None
        self._rec = (scorecard.recommend_threshold(self._scored)
                     if self._scored is not None else None)

        if sc.realized:
            basis = "realized · actual fills (journal)"
        elif sc.out_of_sample:
            basis = "walk-forward · out-of-sample (honest)"
        else:
            basis = "IN-SAMPLE — optimistic, < 150 trades"
        meta = ttk.Frame(self.body)
        meta.pack(fill="x", pady=(4, 6))
        ttk.Label(meta, font=("Consolas", 9), foreground=MUTED,
                  text=f"{sc.n_trades} trades   {sc.date_from} → {sc.date_to}   ·   "
                       f"{basis}").pack(anchor="w")
        if not sc.out_of_sample and not sc.realized:
            ttk.Label(meta, foreground=RED, font=("Segoe UI", 9, "bold"),
                      text="⚠ Optimistic — collect 150+ trades for the honest "
                           "walk-forward scorecard.").pack(anchor="w")

        self._threshold_controls(self.body)

        self.content = ttk.Frame(self.body)
        self.content.pack(fill="both", expand=True)
        self._render_content(self._preview.get())

    # ---------- threshold explorer (roadmap #3 + interactive slider) ----------
    def _threshold_controls(self, parent):
        box = ttk.LabelFrame(parent, text=" Threshold explorer ", padding=8)
        box.pack(fill="x", pady=(2, 6))
        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Label(row, text="Preview gate:", font=("Segoe UI", 9, "bold")).pack(side="left")
        self._pv_label = ttk.Label(row, font=("Consolas", 12, "bold"),
                                   foreground=GREEN, width=3)
        self._pv_label.pack(side="left", padx=(6, 8))
        ttk.Scale(row, from_=50, to=95, orient="horizontal", variable=self._preview,
                  command=self._on_slider).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Apply to live", command=self._apply_live).pack(
            side="left", padx=(10, 0))

        if self._rec:
            be, bt = self._rec["by_expectancy"], self._rec["by_total"]
            hint = ttk.Frame(box)
            hint.pack(fill="x", pady=(6, 0))
            ttk.Label(hint, foreground=MUTED, font=("Consolas", 8),
                      text=f"optimal — max $/trade: {be['threshold']:.0f} "
                           f"(+{be['expectancy']:.2f}$, takes {be['selectivity']:.0f}%)"
                           f"   ·   max total $: {bt['threshold']:.0f} "
                           f"(+{bt['total']:,.0f}$)").pack(side="left")
            ttk.Button(hint, text=f"Use {bt['threshold']:.0f}", width=7,
                       command=lambda t=int(bt['threshold']): self._set_preview(t)
                       ).pack(side="right", padx=(4, 0))
            ttk.Button(hint, text=f"Use {be['threshold']:.0f}", width=7,
                       command=lambda t=int(be['threshold']): self._set_preview(t)
                       ).pack(side="right")
        self._pv_label.config(text=str(self._preview.get()))

    def _on_slider(self, _val):
        self._pv_label.config(text=str(self._preview.get()))
        if self._slider_job:
            self.after_cancel(self._slider_job)
        self._slider_job = self.after(
            120, lambda: self._render_content(self._preview.get()))

    def _set_preview(self, t):
        self._preview.set(int(t))
        self._pv_label.config(text=str(int(t)))
        self._render_content(int(t))

    def _apply_live(self):
        t = self._preview.get()
        if hasattr(self.master, "apply_threshold"):
            self.master.apply_threshold(t)

    def _render_content(self, t):
        if not self.winfo_exists() or self._scored is None:
            return
        for w in self.content.winfo_children():
            w.destroy()
        # Re-bucket at the preview threshold from the cached scored set — for
        # realized fills straight from the journal, otherwise the walk-forward
        # scores (cache hit, instant either way).
        if self._realized:
            sc = scorecard.scorecard_from_scored(self._scored, t, self.inst,
                                                 out_of_sample=False, realized=True)
        else:
            sc = scorecard.compute_scorecard(self._path, t, self.inst)
        if sc is None:
            return

        ttk.Label(self.content, text="Expectancy by score bucket  ($ per trade)",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(6, 2))
        self._bucket_chart(self.content, sc).pack(fill="x")
        ttk.Label(self.content, font=("Consolas", 8), foreground=MUTED,
                  text="Green band = scores ≥ preview gate (let through). Bars "
                       "are $ expectancy from a central zero line.").pack(
            anchor="w", pady=(2, 6))

        ttk.Label(self.content, text="Equity curve — ALLOW only vs trading everything",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8, 2))
        self._equity_chart(self.content, t).pack(fill="x")

        ttk.Label(self.content, text="Gate decision at the preview threshold",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10, 2))
        grid = ttk.Frame(self.content)
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

        edge = sc.edge_per_trade
        pf_a = f" (PF {sc.allow.profit_factor:.2f})" if sc.allow.profit_factor else ""
        pf_all = f" (PF {sc.all.profit_factor:.2f})" if sc.all.profit_factor else ""
        box = ttk.Frame(self.content, padding=10)
        box.pack(fill="x", pady=(12, 0))
        ttk.Label(box, foreground=(GREEN if edge > 0 else RED),
                  font=("Segoe UI", 12, "bold"),
                  text=f"Edge added per taken trade:  {edge:+.2f} $").pack(anchor="w")
        ttk.Label(box, foreground=MUTED, font=("Segoe UI", 9), wraplength=640,
                  text=f"ALLOW expectancy {sc.allow.expectancy:+.2f} ${pf_a} vs "
                       f"trading everything {sc.all.expectancy:+.2f} ${pf_all}. "
                       f"The gate takes {sc.selectivity:.0f}% of trades and skipped "
                       f"{sc.skip.n} worth {sc.skip.total_pnl:+,.0f} $"
                       f"{' (a net loss it dodged)' if sc.skip.total_pnl < 0 else ''}."
                  ).pack(anchor="w", pady=(2, 0))

    # ---------- equity curve ----------
    def _equity_chart(self, parent, t):
        """Cumulative PnL over the trades in time order: the gray line is every
        trade; the green line only steps at trades that pass the preview gate.
        The gap between them is the money the filter added."""
        all_cum, allow_cum = scorecard.equity_curves(self._scored, t)
        n = len(all_cum)
        W, H = 640, 175
        pad_l, pad_r, pad_t, pad_b = 50, 8, 10, 16
        c = tk.Canvas(parent, width=W, height=H, highlightthickness=0,
                      bg=self.cget("bg"))
        ymin = min(float(all_cum.min()), float(allow_cum.min()), 0.0)
        ymax = max(float(all_cum.max()), float(allow_cum.max()), 0.0)
        if ymax == ymin:
            ymax = ymin + 1.0

        def X(i):
            return pad_l + (i / (n - 1)) * (W - pad_l - pad_r) if n > 1 else pad_l

        def Y(v):
            return pad_t + (ymax - v) / (ymax - ymin) * (H - pad_t - pad_b)

        c.create_line(pad_l, Y(0), W - pad_r, Y(0), fill="#cfcfcf")
        c.create_text(2, Y(ymax), anchor="w", font=("Consolas", 7), fill=MUTED,
                      text=f"{ymax:+,.0f}")
        c.create_text(2, Y(ymin), anchor="w", font=("Consolas", 7), fill=MUTED,
                      text=f"{ymin:+,.0f}")
        step = max(1, n // 600)
        idx = list(range(0, n, step))
        if idx[-1] != n - 1:
            idx.append(n - 1)

        def poly(arr):
            pts = []
            for i in idx:
                pts += [X(i), Y(float(arr[i]))]
            return pts

        c.create_line(*poly(all_cum), fill="#9a9a9a", width=1)
        c.create_line(*poly(allow_cum), fill=GREEN, width=2)
        c.create_text(pad_l + 4, pad_t + 1, anchor="nw", font=("Consolas", 8),
                      fill="#777", text="— all trades")
        c.create_text(pad_l + 4, pad_t + 13, anchor="nw", font=("Consolas", 8),
                      fill=GREEN, text="— ALLOW only")
        c.create_text(W - pad_r, Y(float(all_cum[-1])) - 6, anchor="e",
                      font=("Consolas", 8), fill="#777", text=f"{all_cum[-1]:+,.0f}$")
        c.create_text(W - pad_r, Y(float(allow_cum[-1])) + 6, anchor="e",
                      font=("Consolas", 8), fill=GREEN, text=f"{allow_cum[-1]:+,.0f}$")
        return c

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


class VariantCompareWindow(tk.Toplevel):
    """Side-by-side comparison of an instrument's saved variants (roadmap #4):
    PMV, walk-forward AUC (mean + folds), win-rate at the live threshold, and —
    where the variant has its own training snapshot — the out-of-sample $ edge.
    One click activates a variant. Heavy bits run in a worker thread."""

    def __init__(self, master, inst):
        super().__init__(master)
        self.inst = inst
        self._result = None
        self.title(f"Compare variants — {inst}")
        self.geometry("860x420")
        self.minsize(640, 300)

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text=f"Variant comparison — {inst}",
                  font=("Segoe UI", 14, "bold")).pack(side="left")
        ttk.Button(top, text="Refresh", command=self._load).pack(side="right")

        self.body = ttk.Frame(self, padding=(10, 0, 10, 10))
        self.body.pack(fill="both", expand=True)
        self._load()

    def _load(self):
        for w in self.body.winfo_children():
            w.destroy()
        ttk.Label(self.body, foreground=MUTED,
                  text="Comparing variants…").pack(anchor="w", pady=20)
        self._result = None
        threading.Thread(target=self._compute, daemon=True).start()
        self.after(150, self._poll)

    def _compute(self):
        try:
            inst_dir = config.DATA_ROOT / self.inst
            threshold = config.get_threshold()
            rows = variants.comparison_data(inst_dir)
            for r in rows:
                tf = variants.variant_training_file(r["slug"], inst_dir)
                if tf is None and r["active"]:
                    live = inst_dir / "training_data.csv"
                    tf = live if live.exists() else None
                r["edge"] = r["allow_exp"] = r["allow_win"] = None
                r["oos"] = True
                if tf is not None:
                    sc = scorecard.compute_scorecard(tf, threshold, self.inst)
                    if sc is not None:
                        r["edge"] = sc.edge_per_trade
                        r["allow_exp"] = sc.allow.expectancy
                        r["allow_win"] = sc.allow.win_rate
                        r["oos"] = sc.out_of_sample
            self._result = (rows, threshold, None)
        except Exception as e:
            self._result = (None, None, str(e))

    def _poll(self):
        if not self.winfo_exists():
            return
        if self._result is None:
            self.after(150, self._poll)
            return
        rows, threshold, err = self._result
        self._render(rows, threshold, err)

    def _render(self, rows, threshold, err):
        if not self.winfo_exists():
            return
        for w in self.body.winfo_children():
            w.destroy()
        if err:
            ttk.Label(self.body, foreground=RED, wraplength=780,
                      text=f"Could not compare:\n{err}").pack(anchor="w", pady=20)
            return
        if not rows:
            ttk.Label(self.body, foreground=MUTED,
                      text="No saved variants to compare.").pack(anchor="w", pady=20)
            return

        # Bests to highlight.
        best_pmv = max((r["pmv"] or 0) for r in rows)
        best_wf = max((r["wf_mean"] or 0) for r in rows)
        edges = [r["edge"] for r in rows if r["edge"] is not None]
        best_edge = max(edges) if edges else None

        ttk.Label(self.body, foreground=MUTED, font=("Consolas", 8),
                  text=f"win@{threshold:g} and $ edge use the live threshold. "
                       "$ edge is out-of-sample; '—' = no training snapshot yet "
                       "(retrain that variant to capture it).").pack(
            anchor="w", pady=(2, 6))

        grid = ttk.Frame(self.body)
        grid.pack(fill="both", expand=True)
        heads = ("Variant", "PMV", "WF", "WF folds", f"win@{threshold:g}",
                 "edge $/trade", "")
        widths = (34, 7, 7, 0, 8, 12, 0)
        for j, (h, wd) in enumerate(zip(heads, widths)):
            ttk.Label(grid, text=h, font=("Segoe UI", 9, "bold"),
                      width=wd or None,
                      anchor="w" if j == 0 else "center").grid(
                row=0, column=j, padx=5, pady=(0, 4), sticky="w")

        for i, r in enumerate(rows, 1):
            dot = "● " if r["active"] else ""
            name = dot + (r["name"][:32])
            ttk.Label(grid, text=name, font=("Segoe UI", 9, "bold"),
                      foreground=(GREEN if r["active"] else None)).grid(
                row=i, column=0, padx=5, pady=3, sticky="w")

            pmv = r["pmv"]
            ttk.Label(grid, text=f"{pmv:.4f}" if pmv is not None else "—",
                      font=("Consolas", 9),
                      foreground=(GREEN if pmv == best_pmv else None)).grid(
                row=i, column=1, padx=5, sticky="n")
            wf = r["wf_mean"]
            ttk.Label(grid, text=f"{wf:.4f}" if wf is not None else "—",
                      font=("Consolas", 9),
                      foreground=(GREEN if wf == best_wf else None)).grid(
                row=i, column=2, padx=5, sticky="n")

            self._folds_chart(grid, r["wf"]).grid(row=i, column=3, padx=5)

            wr = self._win_at(r["wf_threshold_report"], threshold)
            ttk.Label(grid, text=f"{wr:.0f}%" if wr is not None else "—",
                      font=("Consolas", 9)).grid(row=i, column=4, padx=5, sticky="n")

            edge = r["edge"]
            if edge is None:
                etext, ecolor = "—", MUTED
            else:
                etext = f"{edge:+.2f}"
                ecolor = GREEN if edge > 0 else RED
            lbl = ttk.Label(grid, text=etext, font=("Consolas", 9, "bold"),
                            foreground=ecolor)
            lbl.grid(row=i, column=5, padx=5, sticky="n")
            if edge is not None and edge == best_edge:
                lbl.config(text=etext + "  ★")

            if r["active"]:
                ttk.Label(grid, text="active", foreground=GREEN,
                          font=("Segoe UI", 8)).grid(row=i, column=6, padx=5)
            else:
                ttk.Button(grid, text="Activate", width=9,
                           command=lambda s=r["slug"]: self._activate(s)).grid(
                    row=i, column=6, padx=5)

    def _activate(self, slug):
        if hasattr(self.master, "activate_variant"):
            self.master.activate_variant(self.inst, slug)
        self.after(1600, self._load)

    @staticmethod
    def _win_at(report, threshold):
        if not report:
            return None
        nearest = min(report, key=lambda r: abs(r.get("threshold", 0) - threshold))
        return nearest.get("win_rate")

    def _folds_chart(self, parent, folds):
        """Mini bar chart of the per-fold walk-forward AUCs, scaled 0.50–0.72
        (the meaningful band for these models)."""
        folds = folds or []
        W, H = 90, 34
        c = tk.Canvas(parent, width=W, height=H, highlightthickness=0,
                      bg=self.cget("bg"))
        if not folds:
            c.create_text(W / 2, H / 2, text="—", fill=MUTED, font=("Consolas", 8))
            return c
        lo, hi = 0.50, 0.72
        bw = W / len(folds)
        c.create_line(0, H - 1, W, H - 1, fill="#dddddd")
        for k, a in enumerate(folds):
            frac = max(0.0, min(1.0, (a - lo) / (hi - lo)))
            bh = frac * (H - 4)
            x = k * bw + 2
            c.create_rectangle(x, H - 1 - bh, x + bw - 4, H - 1,
                               fill=GREEN if a >= 0.5 else RED, width=0)
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
        self.compares = {}      # inst -> VariantCompareWindow
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

        if len(vs) >= 2:
            ttk.Button(card, text="⚖ Compare variants",
                       command=lambda i=inst: self._compare(i)).pack(
                anchor="w", pady=(4, 0))

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
        # Keyed on (data mtime, live threshold): the edge line depends on both,
        # so changing the threshold refreshes it without rescoring.
        key = (self._training_mtime(inst), config.get_threshold())
        cached = self._edge_text.get(inst)
        if cached and cached[0] == key:
            lbl.config(text=cached[1], foreground=cached[2])
            return
        lbl.config(text="filter edge: computing…", foreground=MUTED)
        if inst not in self._edge_inflight:
            self._edge_inflight.add(inst)
            threading.Thread(target=self._compute_edge, args=(inst, key),
                             daemon=True).start()

    def _compute_edge(self, inst, key):
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
        self._edge_result[inst] = (key, text, color)

    # ---------- actions ----------
    def _activate(self, inst, s):
        # Hand the switch to the watch thread (it owns the global config and
        # will rescore + reload the model). UI stays responsive.
        self.activate_variant(inst, s)   # reflects the new [active] tag

    def _delete(self, inst, s, name):
        if not messagebox.askyesno("Delete variant", f"Delete this saved variant?\n\n{name}"):
            return
        variants.delete_variant(s, _inst_dir(inst))
        self._rebuild()

    def _set_threshold(self):
        try:
            self.apply_threshold(float(self.thr_var.get()))
        except ValueError:
            messagebox.showwarning("TOAI", "Threshold must be a number 0-100.")

    def apply_threshold(self, value):
        """Write the live (global) threshold and refresh anything that depends
        on it — the entry box and the per-card edge footers. Used by the Set
        button and by a scorecard window's 'Apply to live'."""
        value = float(value)
        config.set_threshold(value)
        self.thr_var.set(f"{value:g}")
        for inst in list(self._edge_labels):
            self._refresh_edge_label(inst)
        return True

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

    def _compare(self, inst):
        win = self.compares.get(inst)
        if win is not None and win.winfo_exists():
            win.deiconify()
            win.lift()
            win.focus_force()
            return
        self.compares[inst] = VariantCompareWindow(self, inst)

    def activate_variant(self, inst, slug):
        """Route a variant switch through the watch thread (it owns the global
        instrument state). Used by the card radios and the compare window."""
        self.switch_queue.put((inst, slug))
        self.after(1500, self._rebuild)

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
            key, text, color = self._edge_result.pop(inst)
            self._edge_text[inst] = (key, text, color)
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
