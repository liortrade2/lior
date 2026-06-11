# מדריך: בניית LIOR_MES_Entry ב-BloodHound

לפי ה-build map — שלב 1: Signal generation בלבד. בלי BlackBird, בלי ML עדיין.

## מה בונים
קובץ BloodHound אחד בשם **LIOR_MES_Entry** עם שני outputs:
- **Long** = Trend ∧ Regime ∧ Location
- **Short** = ההפך המדויק

## תנאי הסיגנל (מה-build map)

| תנאי | Long | Short |
|---|---|---|
| A — Trend 1 | EMA(9) > EMA(20) | EMA(9) < EMA(20) |
| A — Trend 2 | EMA(20) > EMA(50) | EMA(20) < EMA(50) |
| B — Regime | TTM Squeeze Histogram > 0 בבר הנוכחי **וגם** בבר הקודם | Histogram < 0 בשני הברים |
| C — Location | Close > Current Day VWAP | Close < Current Day VWAP |

העדפה: Lizard Gapless EMA ו-Lizard Current Day VWAP (יש לך את הספרייה).

## צעדים ב-Logic Editor

1. צ'ארט MES **5min** → הוסף BloodHound → לחץ על שורת ה-BloodHound בפאנל → **Logic Editor**

2. **צור 4 Solvers ל-Long:**
   - `A1_EmaFast`: Solver מסוג **Indicator Comparison** → Input A: Gapless EMA period 9, Input B: Gapless EMA period 20, תנאי: **A Greater Than B**
   - `A2_EmaSlow`: אותו דבר עם EMA 20 מול EMA 50
   - `B_Squeeze`: **Indicator Threshold** → Indicator: TTM Squeeze (Histogram plot), תנאי: Greater Than 0.
     לדרישת "שני ברים רצופים": שכפל את ה-Solver ובעותק הגדר **Bars Ago = 1**, או השתמש ב-Confirmed/Consecutive bars אם קיים בגרסה שלך
   - `C_Vwap`: **Indicator Comparison** → Input A: Close (Price), Input B: Current Day VWAP, תנאי: A Greater Than B

3. **חבר Logic Gate מסוג AND** עם כל ה-Solvers → גרור אל ה-**Long output**

4. **צור את צד ה-Short:** שכפל כל Solver והפוך את התנאי (Less Than) → AND → **Short output**

5. **שמור template:** File → Save As → `LIOR_MES_Entry`
   (BloodHound שומר ל-`Documents\NinjaTrader 8\templates\BloodHound`)

## בדיקת שפיות (לפני Replay!)

הסתכל על הצ'ארט אחרי החיבור ובדוק:
- [ ] סיגנלים מופיעים **1-3 פעמים ביום** (לא 20, לא 0)
- [ ] Long מופיע רק כשה-EMAs מסודרים למעלה והמחיר מעל VWAP
- [ ] סיגנלים בסביבת breakout, לא באמצע צריחה צידית

## שלב 3 — Replay Testing (אחרי שהסיגנלים נראים הגיוניים)

נתונים: MES Replay מאי 2026 | TF: 5min | יעד: 50+ trades

| מדד | Target | פסילה |
|---|---|---|
| Win Rate | > 45% | < 35% |
| Avg Win / Avg Loss | > 1.2 | < 1.0 |
| Trades per day | 2-5 | > 10 או < 1 |
| Max consecutive losses | < 5 | > 7 |

**כלל זהב:** לא ממשיכים לשלב הבא לפני 50+ trades על Replay.
