# TOAI 2.0 — Modern Quant Stack Roadmap

*A staged plan to evolve TOAI into a state-of-the-art meta-labeling system — built
on what the pros actually use, sequenced so each step compounds the last.*

---

## 0. Where we are (honest baseline)

- **What TOAI already is:** a **meta-labeling** system (López de Prado, 2017) — an
  ML model that filters a primary strategy's signals (Bollinger + RSI mean
  reversion) and decides *whether to act*. This is the right architecture; it's
  what multi-manager hedge funds use.
- **Current edge:** walk-forward AUC ≈ **0.51** (≈ random). Calibration + TRUST
  badge are in (`train.py`).
- **Data:** ~263 long-only trades; **OHLC present on only ~1%** of history, so the
  5 candle-shape mean-reversion features in `features.py` are **OFF**.
- **Live learning:** `build_and_train(include_live=True)` now folds Sim101 +
  funded fills into training (`merge.live_training_rows`).

### The guiding principle
> Top quant edge comes from **labeling quality + honest validation + good
> features** — NOT from a bigger model. A fancy model on 263 trades overfits
> spectacularly and gives false confidence. **Foundation first.**

---

## The two prerequisites only the user can do
1. **OHLC re-export** in NinjaTrader → retrain. Lights up the existing candle-shape
   features (the "turn" of a reversion). *Biggest single unlock.*
2. **Collect 1000+ trades.** Every technique below scales with data.

Everything in Layer 1 should land *together with* the OHLC re-export.

---

## Layer 1 — Foundation (labeling, validation, features) ⭐ do first

### 1.1 Triple-barrier labeling  *(López de Prado)*
- **What:** label each trade by **which barrier it hits first** — `+1` target,
  `-1` stop, `0` time-out — instead of by final P&L sign.
- **Why:** captures **risk + timing**, not just direction; the model learns from
  *how the trade actually played out*, not noisy price drift.
- **TOAI fit:** we already compute exactly this from **MAE/MFE** in
  `simulate_sltp` / `sltp_grid` (the Simulator). Reuse it to relabel
  `training_data.csv`: a `Label ∈ {-1,0,+1}` column drives training.
- **Effort:** medium. Files: `merge.py` (add label), `train.py` (train on label).
- **Dependency:** MAE/MFE (have it). Independent of OHLC.

### 1.2 OHLC candle-shape features  *(already coded, just OFF)*
- Re-export → `BodyDir_ATR`, `ClosePos`, `LowerWick_ATR`, `UpperWick_ATR`,
  `DipDepth_ATR` auto-activate at ≥80% coverage (`features.py`).
- Gives the model "eyes" for the reversal bar (dip exhausts → turns up).

### 1.3 Purged + Combinatorial-Purged CV  *(López de Prado)*
- **What:** cross-validation that **purges** overlapping samples and embargoes
  data near the test fold, so the model can't peek at adjacent-in-time info.
  Combinatorial-purged CV (CPCV) yields a *distribution* of out-of-sample
  Sharpe, not one fragile number.
- **Why:** standard k-fold leaks badly in time series → inflated, fake edge.
  This is the single biggest reason backtests don't survive live.
- **TOAI fit:** replace/augment the current walk-forward in `train.py`.
- **Effort:** medium. **High truth-value** — tells you if any edge is real.

### 1.4 LightGBM + SHAP  *(model + explainability)*
- **What:** gradient-boosted trees (best-in-class for tabular) + **SHAP** values
  that attribute each score to its features ("this 70 = +ZScore −ADX +LowerWick").
- **Why:** strong on small/medium tabular data, robust, and *interpretable* —
  you see *why* the model gates each trade. Trust through transparency.
- **TOAI fit:** swap/ensemble the current estimator in `train.py`; add a SHAP
  panel to the 🎯 ML edge tab and per-trade in 🕯 Trade explorer.
- **Effort:** medium.

---

## Layer 2 — Context ("see like a human" + regime) 👁️

### 2.1 Vision-LLM second opinion  *(Claude vision — FinAgent-style)*
- **What:** render a candlestick image of the recent bars → send to **Claude
  vision** → structured read: `regime ∈ {range, trend, falling-knife}`,
  `reversion_quality 0-100`, one-line rationale.
- **Why:** FinAgent showed adding Kline-chart vision to a GPT-4V trading agent
  *materially improved* performance vs. numbers-only. Directly attacks the
  falling-knife problem (don't fade a strong trend).
- **TOAI fit:** you already have Claude wired (`ai_coach.py`, `ANTHROPIC_API_KEY`)
  and candlestick rendering (Trade explorer). Start as an **advisor** in the AI
  Coach; later wire as a **soft veto/weight** on the gate (require ML-allow AND
  not-falling-knife).
- **Caveat:** general VLMs aren't trained on financial charts — use as a *regime
  sanity check*, never the primary signal.
- **Effort:** medium. Highest "wow", very feasible.

### 2.2 Regime detection  *(HMM / clustering)*
- **What:** an unsupervised model (Hidden Markov Model or k-means on
  volatility/trend features) labels the current market **regime**; the gate adapts
  (mean reversion only fires in range/choppy regimes).
- **Why:** "oversold stays oversold in a downtrend." Mean reversion *needs* a
  ranging regime. You already export `ADX14` (trend strength) and EMA spreads.
- **TOAI fit:** add a `Regime` feature + an optional regime gate in `score.py`.
- **Effort:** medium.

---

## Layer 3 — Confidence (how much to trust each call) 🎯

### 3.1 Conformal prediction
- **What:** wraps the model to output a **statistically guaranteed** confidence
  set per prediction — "≥X% coverage" with a valid error rate, not just a number.
- **Why:** turns "score 70" into "70 with a *trustworthy* band" → size up only
  when the model is genuinely sure. Cutting-edge, works on modest data.
- **TOAI fit:** wrap the calibrated estimator; surface the band on the gauge.
- **Effort:** medium.

### 3.2 Ensemble + (existing) calibration
- Combine LightGBM + the current calibrated model; keep Platt/sigmoid calibration
  (have it) so probabilities mean what they say (Brier/ECE already reported).

---

## Deliberately NOT in scope (traps for this data size)
- **Deep learning / Transformers / RL for sizing** — data-hungry; overfit on 263
  trades. Revisit at 10k+ trades.
- **CNN on chart images** — the "92% accuracy" papers measure *pattern
  classification*, not P&L edge; heavy to train. Vision-LLM gives ~80% of the
  value for ~5% of the effort.

---

## Build sequence (impact-ordered)

| Phase | Build | Unlocks | Needs |
|-------|-------|---------|-------|
| **0 — user** | OHLC re-export + keep collecting trades | candle-shape features, data | NinjaTrader |
| **1** | Triple-barrier labeling | risk/timing-aware learning | MAE/MFE ✓ |
| **2** | LightGBM + SHAP | stronger model + "why" per score | — |
| **3** | Purged/Combinatorial CV | honest out-of-sample truth | — |
| **4** | Vision-LLM second opinion | human-eye regime read | Claude ✓ |
| **5** | Regime detection + gate | avoid falling-knife fades | ADX ✓ |
| **6** | Conformal prediction | trustworthy confidence + sizing | calibrated model ✓ |

Phases 1–3 are the **foundation** and should ship close to the OHLC re-export.
Phases 4–6 layer context and confidence on top.

---

## Success metrics (how we know it's working — not vanity)
- **Walk-forward / CPCV AUC** climbs decisively above 0.55 (today ≈ 0.51).
- **Edge per trade** (ALLOW vs all) goes positive out-of-sample — the green line
  clears the grey on the "Strategy vs TOAI" chart.
- **Calibration** (ECE/Brier) stays low — scores mean what they say.
- **TRUST** badge moves off `none`.

> If CPCV says there's no edge, *no model upstream will fix it* — that's the
> signal to change the strategy or the features, not to add more AI.

---

*Architecture in one line:* **ML score (quant) × Vision-LLM (context) × conformal
confidence (trust)** — three independent layers, each a soft gate, exactly how
modern multi-strategy desks stack signals.
