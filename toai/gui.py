"""TOAI control panel — desktop GUI modeled on the TradeOptima.AI app.

Left side:  strategy template picker (BlackBird templates folder) and the
            feature checklist (like TOAI's "Select Strategy Features").
Bottom:     Calculate Decision Boundary / Calculate PMV buttons + PMV display.
Right side: log of everything that happened.

Run: python main.py -> option 5, or: python -m toai.gui
"""
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import config
from .features import MODEL_FEATURES


class ToaiPanel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TOAI — Trade Optimizer AI")
        self.geometry("760x560")
        self.minsize(680, 500)

        self.training_file = tk.StringVar(value=str(config.TRAINING_FILE))
        self.strategy = tk.StringVar()
        self.pmv_text = tk.StringVar(value="PMV:  —")
        self.threshold = tk.StringVar(value=f"{config.get_threshold():g}")
        self.feature_vars = {f: tk.BooleanVar(value=True) for f in MODEL_FEATURES}
        self._bundle = None  # set after training

        self._build_layout()
        self._refresh_templates()

    # ---------- layout ----------

    def _build_layout(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(3, weight=1)

        # Strategy template picker
        strat = ttk.LabelFrame(root, text="Strategy (BlackBird template)", padding=8)
        strat.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        strat.columnconfigure(0, weight=1)
        self.strategy_combo = ttk.Combobox(strat, textvariable=self.strategy, state="readonly")
        self.strategy_combo.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(strat, text="Refresh", command=self._refresh_templates).grid(row=0, column=1)
        self.templates_label = ttk.Label(strat, text=str(config.TEMPLATES_DIR), foreground="gray")
        self.templates_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # Backtest & data flow
        bktest = ttk.LabelFrame(root, text="Backtest data (from Strategy Analyzer)", padding=8)
        bktest.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        bktest.columnconfigure(0, weight=1)
        info = ttk.Label(bktest, text="1. Strategy Analyzer → Trades tab → right-click → Export → save with ANY name\n   (the strategy's name is best) into:  " + str(config.DATA_DIR) +
                         "\n2. Load chart with TOAIExporter (ExportBarData=true) to build bar_data.csv\n3. Click below — the newest export is found automatically, merged & trained",
                         wraplength=600, justify=tk.LEFT)
        info.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.refresh_btn = ttk.Button(bktest, text="Refresh from Strategy Analyzer", command=self._refresh_from_backtest)
        self.refresh_btn.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(bktest, text="Open folder", command=self._open_data_dir).grid(row=1, column=1)

        # Training file picker
        filef = ttk.LabelFrame(root, text="Training file (auto-generated)", padding=8)
        filef.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        filef.columnconfigure(0, weight=1)
        ttk.Entry(filef, textvariable=self.training_file, state=tk.DISABLED).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(filef, text="Browse…", command=self._browse_training).grid(row=0, column=1)

        # Features checklist (left) + log (right)
        feats = ttk.LabelFrame(root, text="Features", padding=8)
        feats.grid(row=3, column=0, sticky="nsw", padx=(0, 8))
        for i, (name, var) in enumerate(self.feature_vars.items()):
            ttk.Checkbutton(feats, text=name, variable=var).grid(row=i, column=0, sticky="w")
        btns = ttk.Frame(feats)
        btns.grid(row=len(self.feature_vars), column=0, pady=(6, 0))
        ttk.Button(btns, text="All", width=5,
                   command=lambda: self._set_all(True)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="None", width=5,
                   command=lambda: self._set_all(False)).pack(side=tk.LEFT, padx=2)

        logf = ttk.LabelFrame(root, text="Log", padding=4)
        logf.grid(row=3, column=1, sticky="nsew")
        logf.columnconfigure(0, weight=1)
        logf.rowconfigure(0, weight=1)
        self.log = tk.Text(logf, height=10, state=tk.DISABLED, wrap="word")
        self.log.grid(row=0, column=0, sticky="nsew")

        # Threshold — the ONE place it is set. Written to threshold.txt,
        # which the watch, TOAIExporter, TOAISignalLabel and BloodHound's
        # internal TOAIExporter copy all read.
        thresh = ttk.LabelFrame(root, text="Passing score (threshold) — updates ALL components", padding=8)
        thresh.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(thresh, text="Min Probability of Win:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Entry(thresh, textvariable=self.threshold, width=6).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(thresh, text="Set Threshold", command=self._set_threshold).pack(side=tk.LEFT, padx=(0, 10))
        self.threshold_label = ttk.Label(
            thresh, text=f"current: {config.get_threshold():g}  ({config.THRESHOLD_FILE})",
            foreground="gray")
        self.threshold_label.pack(side=tk.LEFT)

        # Bottom: action buttons + PMV display
        bottom = ttk.Frame(root)
        bottom.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.calc_btn = ttk.Button(bottom, text="Calculate Decision Boundary",
                                   command=self._calculate)
        self.calc_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.pmv_btn = ttk.Button(bottom, text="Calculate PMV", command=self._show_pmv)
        self.pmv_btn.pack(side=tk.LEFT, padx=(0, 12))
        self.pmv_label = ttk.Label(bottom, textvariable=self.pmv_text,
                                   font=("Segoe UI", 14, "bold"))
        self.pmv_label.pack(side=tk.LEFT)

    # ---------- helpers ----------

    def _log(self, msg: str):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _set_threshold(self):
        try:
            value = config.set_threshold(float(self.threshold.get()))
        except ValueError:
            messagebox.showwarning("TOAI", "Threshold must be a number between 0 and 100.")
            return
        self.threshold_label.configure(
            text=f"current: {value:g}  ({config.THRESHOLD_FILE})")
        self._log(f"Threshold set to {value:g} — written to {config.THRESHOLD_FILE.name}.")
        self._log("Applies everywhere: watch (immediately), chart indicators and")
        self._log("BloodHound's gate on the next bar / chart reload.")

    def _set_all(self, value: bool):
        for var in self.feature_vars.values():
            var.set(value)

    def _selected_features(self):
        return [f for f, var in self.feature_vars.items() if var.get()]

    def _refresh_templates(self):
        folder = config.TEMPLATES_DIR
        names = []
        if folder.exists():
            names = sorted(p.name for p in folder.iterdir() if p.is_file())
        self.strategy_combo["values"] = names
        if names and not self.strategy.get():
            self.strategy.set(names[0])
        if not names:
            self._log(f"No templates found in {folder}")

    def _browse_training(self):
        path = filedialog.askopenfilename(
            title="Select training CSV",
            initialdir=str(config.DATA_DIR),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if path:
            self.training_file.set(path)

    def _open_data_dir(self):
        import subprocess, sys
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(config.DATA_DIR)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(config.DATA_DIR)])
        else:
            subprocess.Popen(["xdg-open", str(config.DATA_DIR)])

    def _refresh_from_backtest(self):
        from .build_and_train import find_trades_export
        strategy = self.strategy.get() or None
        trades_file = find_trades_export(strategy)
        if trades_file is None:
            messagebox.showwarning(
                "TOAI",
                f"No trades export found in:\n\n{config.DATA_DIR}\n\n"
                f"Steps:\n"
                f"1. In NinjaTrader: Strategy Analyzer → run backtest\n"
                f"2. Trades tab → right-click → Export\n"
                f"3. Save with any name (the strategy's name is best)\n"
                f"   into the folder above\n\n"
                f"Then click Refresh again.")
            self._open_data_dir()
            return
        if not config.BAR_DATA_FILE.exists():
            messagebox.showwarning(
                "TOAI",
                f"bar_data.csv not found at:\n\n{config.BAR_DATA_FILE}\n\n"
                f"Load a chart with TOAIExporter indicator (ExportBarData=true)\n"
                f"covering the same period as your backtest, then click Refresh.")
            return
        self.refresh_btn.configure(state=tk.DISABLED)
        self._log(f"Using trades export: {trades_file.name}")
        self._log("Merging backtest with bar data and training…")
        threading.Thread(target=self._refresh_worker, args=(strategy,), daemon=True).start()

    def _refresh_worker(self, strategy):
        from .build_and_train import build_and_train
        try:
            ok = build_and_train(strategy)
            if ok:
                self.after(0, self._refresh_done)
            else:
                self.after(0, self._refresh_failed, "Merge or training failed — see output above")
        except Exception as e:
            self.after(0, self._refresh_failed, str(e))

    def _refresh_done(self):
        self.refresh_btn.configure(state=tk.NORMAL)
        try:
            import joblib
            from .train import format_threshold_report
            bundle = joblib.load(config.MODEL_FILE)
            pmv = bundle.get("pmv", float("nan"))
            self.pmv_text.set(f"PMV:  {pmv:.4f}")
            self._log(f"PMV (AUC-ROC) = {pmv:.4f}")
            wf = bundle.get("walk_forward") or []
            if wf:
                self._log(f"Walk-forward PMV = {sum(wf) / len(wf):.4f} "
                          f"(folds: {'  '.join(f'{a:.3f}' for a in wf)})")
            if bundle.get("wf_threshold_report"):
                self._log("")
                self._log(format_threshold_report(
                    bundle["wf_threshold_report"],
                    title="Threshold analysis (walk-forward — USE THIS to pick threshold):"))
            elif bundle.get("threshold_report"):
                self._log("")
                self._log(format_threshold_report(bundle["threshold_report"]))
        except Exception:
            pass
        self._log("")
        self._log("Done. Restart TOAI_Watch.bat to load the new model.")
        messagebox.showinfo("TOAI", "Model trained successfully.\n\n"
                           "Restart TOAI_Watch.bat so it loads the new model,\n"
                           "then check the scores on your live chart.")

    def _refresh_failed(self, err):
        self.refresh_btn.configure(state=tk.NORMAL)
        self._log(f"Error: {err}")
        messagebox.showerror("TOAI", f"Training failed:\n\n{err}")

    # ---------- actions ----------

    def _calculate(self):
        features = self._selected_features()
        if len(features) < 2:
            messagebox.showwarning("TOAI", "Select at least 2 features.")
            return
        if len(features) > 12:
            messagebox.showwarning("TOAI", "Select at most 12 features (curve-fitting risk).")
            return

        self.calc_btn.configure(state=tk.DISABLED)
        self.pmv_text.set("PMV:  calculating…")
        strategy = self.strategy.get() or "(no template selected)"
        self._log(f"Strategy: {strategy}")
        self._log(f"Training with {len(features)} features…")
        threading.Thread(target=self._train_worker, args=(features,), daemon=True).start()

    def _train_worker(self, features):
        from .train import load_training_data, train
        try:
            df = load_training_data(self.training_file.get(), features=features)
            model, scaler, pmv = train(df, features=features, verbose=False)
            self._bundle = {"pmv": pmv, "n_trades": len(df)}
            self.after(0, self._train_done, pmv, len(df))
        except Exception as e:
            self.after(0, self._train_failed, str(e))

    def _train_done(self, pmv, n_trades):
        self.calc_btn.configure(state=tk.NORMAL)
        self.pmv_text.set(f"PMV:  {pmv:.4f}")
        verdict = ("model adds value ✔" if pmv > 0.5
                   else "model does NOT add value — collect more trades")
        self._log(f"Done. {n_trades} trades | PMV (AUC-ROC) = {pmv:.4f} — {verdict}")
        try:
            import joblib
            from .train import format_threshold_report
            bundle = joblib.load(config.MODEL_FILE)
            if bundle.get("threshold_report"):
                self._log(format_threshold_report(bundle["threshold_report"]))
        except Exception:
            pass
        self._log(f"Model saved to {config.MODEL_FILE}")

    def _train_failed(self, err):
        self.calc_btn.configure(state=tk.NORMAL)
        self.pmv_text.set("PMV:  —")
        self._log(f"Error: {err}")
        messagebox.showerror("TOAI", err)

    def _show_pmv(self):
        if self._bundle:
            self.pmv_text.set(f"PMV:  {self._bundle['pmv']:.4f}")
            return
        # No training this session — read the saved model if there is one.
        try:
            import joblib
            bundle = joblib.load(config.MODEL_FILE)
            self.pmv_text.set(f"PMV:  {bundle.get('pmv', float('nan')):.4f}")
            self._log(f"Loaded PMV from saved model: {config.MODEL_FILE}")
        except FileNotFoundError:
            messagebox.showinfo("TOAI", "No trained model yet — run Calculate Decision Boundary first.")


def main():
    ToaiPanel().mainloop()


if __name__ == "__main__":
    main()
