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

from . import config, variants
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
