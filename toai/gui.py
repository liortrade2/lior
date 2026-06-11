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


class ToaiPanel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TOAI — Trade Optimizer AI")
        self.geometry("760x560")
        self.minsize(680, 500)

        self.training_file = tk.StringVar(value=str(config.TRAINING_FILE))
        self.strategy = tk.StringVar()
        self.pmv_text = tk.StringVar(value="PMV:  —")
        self.feature_vars = {f: tk.BooleanVar(value=True) for f in config.FEATURES}
        self._bundle = None  # set after training

        self._build_layout()
        self._refresh_templates()

    # ---------- layout ----------

    def _build_layout(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(2, weight=1)

        # Strategy template picker
        strat = ttk.LabelFrame(root, text="Strategy (BlackBird template)", padding=8)
        strat.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        strat.columnconfigure(0, weight=1)
        self.strategy_combo = ttk.Combobox(strat, textvariable=self.strategy, state="readonly")
        self.strategy_combo.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(strat, text="Refresh", command=self._refresh_templates).grid(row=0, column=1)
        self.templates_label = ttk.Label(strat, text=str(config.TEMPLATES_DIR), foreground="gray")
        self.templates_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # Training file picker
        filef = ttk.LabelFrame(root, text="Training file", padding=8)
        filef.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        filef.columnconfigure(0, weight=1)
        ttk.Entry(filef, textvariable=self.training_file).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(filef, text="Browse…", command=self._browse_training).grid(row=0, column=1)

        # Features checklist (left) + log (right)
        feats = ttk.LabelFrame(root, text="Features", padding=8)
        feats.grid(row=2, column=0, sticky="nsw", padx=(0, 8))
        for i, (name, var) in enumerate(self.feature_vars.items()):
            ttk.Checkbutton(feats, text=name, variable=var).grid(row=i, column=0, sticky="w")
        btns = ttk.Frame(feats)
        btns.grid(row=len(self.feature_vars), column=0, pady=(6, 0))
        ttk.Button(btns, text="All", width=5,
                   command=lambda: self._set_all(True)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="None", width=5,
                   command=lambda: self._set_all(False)).pack(side=tk.LEFT, padx=2)

        logf = ttk.LabelFrame(root, text="Log", padding=4)
        logf.grid(row=2, column=1, sticky="nsew")
        logf.columnconfigure(0, weight=1)
        logf.rowconfigure(0, weight=1)
        self.log = tk.Text(logf, height=10, state=tk.DISABLED, wrap="word")
        self.log.grid(row=0, column=0, sticky="nsew")

        # Bottom: action buttons + PMV display
        bottom = ttk.Frame(root)
        bottom.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
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
