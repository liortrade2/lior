# TOAI — Project Status & Handoff

> **קרא אותי ראשון בכל chat חדש.** עדכון אחרון: **2026-06-16 לילה**.
> כתוב כ-handoff מלא — הצ'אט הקודם הגיע לגבול אורך.

---

## 1. מה המערכת עושה (עובד ✅)

פילטר עסקאות ML ל-NinjaTrader. ‏BloodHound מייצר סיגנלים (אסטרטגיית
**BBTMP Bollinger 2.5 Volatility Spike**, לוגיקה 1-CCI EMA MACD_RTH),
‏TOAI מחשב Probability-of-Win לכל בר, ‏BloodHound בודק את ה-plot **MLPass**
‏(0/1) כ-solver וחוסם סיגנלים מתחת לסף. ‏BlackBird מנהל את העסקה.
מסחר ב-**Sim101** (לא חי-אמיתי עדיין).

## 2. הגרסה החיה = **v4** (`ninjascript_v4_gauge_tick/`)

חבילה עצמאית, 3 אינדיקטורים על הגרף:
| קובץ | תפקיד |
|---|---|
| `TOAIExporterGaugeTick.cs` | גשר + שער (MLPass) + קו ProbOfTrue (sub-panel). ‏OnEachTick (~2ש' lag). מתג `ShowTextHud` (fallback טקסטואלי, כרגע false). |
| `TOAIGaugeHUD.cs` | **gauge גרפי** (SharpDX) על פאנל המחיר — overlay נפרד. |
| `TOAISignalLabelGaugeTick.cs` | תוויות % על ברי-סיגנל. **×2 על הגרף**: ‏Input=Long Confidence + עותק עם Short Confidence (שני הכיוונים). |

`ninjascript/` = ‏v1 (TOAIExporter/TOAISignalLabel) — **fallback בלבד**, נקודת שחזור.

**BloodHound solver:** ‏`TOAIExporterGaugeTick.MLPass >= 1` ל-**שני** הכיוונים
(לא `>0`/`<0` — חוסם שורטים!).

## 3. מודל נוכחי — MES עובר ל-**15-דקות** (2026-06-17)

‏**BBTMP (1-דקה) נמחק** לבקשת ליאור — וריאנטים 1-/2-/expectancy, ה-model.pkl, training_data,
bar_scores כולם נמחקו. ה-`MES` עכשיו **לוח נקי** (variants.json ריק), עם `bar_data.csv` של **15-דקות**
(‏`bar_data_tf.txt=Minute-15`). ארכיוני ה-1-דקה נשמרו כגיבוי. (ה-BBTMP היה: 1- WF 0.654 / 2- WF 0.666 —
אם רוצים להחזיר, יש ארכיוני bar_data_Minute-1 + ה-export "1-".)

**הצעד הבא (חוסם):** הגרף 15-דקות טען רק ~6 ימים (11-17/6); 5 ה-exports (`1A-15min…`, כולם MES SEP26,
‏72-519 עסקאות) הם מ-**2025-01 עד 2026-01**. **צריך לטעון היסטוריית 15-דקות מלאה (חזרה ל-2025-01)**
על הגרף, ואז ה-watch יאמן את 5 האסטרטגיות אוטומטית → 5 וריאנטים → להשוות ב-⚖ ולבחור.
**הגנה חדשה**: merge כבר לא דורס training_data לריק כש-0 התאמות (תיקון שורש הקריסה), ו-build_and_train
מזהה+מדפיס את ה-TF. כלל: רק גרף MES אחד (15-דקות) רץ — לא במקביל ל-1-דקה (ping-pong).
מכשירים אחרים (MNQ/M2K/MYM/MCL/MGC/MBT): תיקיות קיימות, **לא אומנו**.

## 4. כלים שנבנו (Python)
- **Control Panel** (`toai/control_panel.py`, `TOAI_Control.bat`) — **מחליף את TOAI_Watch**.
  מריץ את ה-watch ברקע + כרטיס לכל כלי: badge חי (ALLOW/SKIP/CLOSED) + רדיו לבחירת וריאנט + מחיקה +
  כפתור **📊 Scorecard**.
- **Live Scorecard** (`toai/scorecard.py`) — ✅ roadmap #1+#2. לכל כלי: win-rate **+ תוחלת ($/עסקה) + R:R
  + Profit Factor + Selectivity**, וסיכום **ALLOW מול SKIP** בסף החי = ה-edge בכסף שהפילטר מוסיף.
  **out-of-sample** (walk-forward, לא in-sample) — מאותו מקור-אמת של train.walk_forward, רק שנושא PnL.
  מקור: `training_data.csv` → מתעדכן לבד בכל אימון. **תוצאה MES**: ALLOW 78% win / +4.25$ / PF 2.48 מול
  SKIP 58% / -0.61$ / PF 0.89; edge ‎+2.33$ לעסקה, לוקח 52% מהעסקאות. ✔ הפילטר עובד בכסף (out-of-sample).
  - **בפאנל**: כפתור 📊 פותח popup (חלון אחד לכל כלי — לחיצה חוזרת מקדימה+מרעננת) עם **גרף עמודות מתפצל**
    של תוחלת לפי דלי (ירוק/אדום מקו-אפס, פס ALLOW מודגש), **עקומת הון** (ALLOW מול 'לסחור הכול'),
    **סליידר-סף אינטראקטיבי** (גורר → ALLOW/SKIP/edge/גרפים מתעדכנים מיידית בזכות ה-caching) עם המלצות
    **סף אופטימלי** (max $/עסקה ו-max total $) וכפתור "Apply to live", טבלת ALLOW/SKIP (PF), וכותרת edge.
    כל כרטיס-כלי מציג שורת **"filter edge"** חיה (ברקע) — רואים אם הפילטר עושה כסף בלי לפתוח כלום.
  - **CLI**: `main.py` אופציה 9 (טקסט).
- **השוואת וריאנטים** (✅ roadmap #4) — כפתור "⚖ Compare variants" בכרטיס (כש-2+ וריאנטים): טבלה זו-לצד-זו
  של PMV, WF (ממוצע + גרף-עמודות לכל fold), win@סף, ו-**$ edge out-of-sample** (★ על הטוב ביותר) + כפתור
  Activate. ‏$ edge דורש snapshot של training_data לכל וריאנט — `variants.save_variant` שומר אותו מעכשיו
  (וריאנט בלי snapshot מציג "—" עד אימון מחדש; הפעיל משתמש ב-training_data.csv הנוכחי).
- **סף אופטימלי** (✅ roadmap #3, כבסיס) — `scorecard.recommend_threshold()` + `threshold_sweep()` סורקים
  את כל הספים על ה-out-of-fold ובוחרים מקסימום-תוחלת / מקסימום-total. כרגע **מייעץ** (הסף החי גלובלי-משותף
  לכל הגרפים בארכיטקטורה הנוכחית). "Apply to live" כותב לסף הגלובלי.
- **יומן עסקאות TOAI-native** (`toai/journal.py`) — הצד ה**מומש** של הלולאה הסגורה. במקום יומן חיצוני
  (Edgewonk/TradeZella/TradesViz — כולם כלים אנושיים שדוחפים לענן, וסגירת-לולאה תלויה ב-API בתשלום),
  בנינו יומן משלנו: ה-watch קורא `<כלי>/executions.csv` (fills חיים) ורושם כל עסקה מול הציון שקיבלה
  → `<כלי>/journal.csv` (append-only, dedup, שורד אימונים). תצוגת ה-Scorecard ממוחזרת: כפתור **Show:
  Realized fills ↔ Walk-forward** בחלון ה-📊 מציג **חזוי (backtest) מול מומש (fills אמיתיים)** באותו גרף —
  המבחן האמיתי אם ה-edge מתממש בכסף. גם `main.py` אופציה 10. **חסר בצד ליאור**: מי כותב את `executions.csv`
  (ראה §6) — NinjaScript executions-logger או ייצוא Trade Performance ידני.
- **ניהול וריאנטים** (`toai/variants.py`, main.py אופציה 8) — כל אימון נשמר כווריאנט; החלפה בלי אימון מחדש.
- **אימון אוטומטי של כל ה-exports** — ה-watch סורק את כל הקבצים בשורש ומאמן כל חדש (לכל הכלים יחד).

---

## 5. ⭐ ROADMAP מאושר (להמשך — לפי עדיפות)

ליאור **אישר את כל אלה**. בנה לפי הסדר:

### 🎯 הבא בתור (התחל כאן)
1. ✅ **Live Scorecard** — **בוצע** (`toai/scorecard.py` + כפתור בפאנל + main.py אופ' 9). ראה §4.
2. ✅ **Expectancy** — **בוצע** דרך ה-Scorecard (תוחלת $/עסקה + R:R לפי דלי, ו-ALLOW/SKIP).
   הערה: טבלת הספים ב-`train.py` (פלט אימון) עדיין win-rate בלבד — ה-Scorecard מחליף אותה
   לתצוגת-הכסף. אופציונלי בעתיד: לשתול עמודת תוחלת גם שם (דורש להעביר PnL ל-walk_forward).

### 🧠 מוח (Tier 1) — מודל-תוחלת ✅ הוכח ובנוי
- **`toai/expectancy.py`** — אימון על **כסף במקום win/loss**: `sample_weight ∝ |PnL|` (winsorize 97.5%).
  המודל לומד להתחמק מההפסדים הגדולים ולהעדיף את הרווחים השמנים, לא רק את התכופים.
  - **הוכחה (out-of-sample, אותן 4905 עסקאות MES, סף 70)**: win-rate model +4.25$/עסקה (edge +2.33) מול
    **expectancy model +6.19$/עסקה (edge +4.27, PF 2.89)**. מנצח בכל סף. יותר סלקטיבי (פחות עסקאות, איכותיות יותר).
  - **מופעל כווריאנט**: `train_expectancy()` שומר וריאנט **לא-פעיל** `<base> [expectancy]` (slug `..._EXP`) עם
    snapshot משלו — ה-model.pkl החי **לא נגעו בו**. משווים ב-**⚖ Compare** (כל וריאנט מנוקד עם/בלי משקלול
    לפי `weight_by_pnl` ב-registry), ומפעילים בלחיצה אם מנצח. גם `main.py` אופציה 11.
  - **הערה**: ה-AUC של מודל-התוחלת *נמוך* יותר (0.625 מול 0.654) — זה תקין: הוא מקריב דיוק-דירוג כדי לדייק
    בעסקאות הגדולות. **ה-$ edge הוא ההשוואה האמיתית**, לא ה-AUC.

### 🔧 מודל
3. ✅ **סף אופטימלי** — **בוצע כבסיס** (recommend_threshold + סליידר + Apply). מייעץ בלבד כי הסף גלובלי.
   ‏**להשלים בעתיד**: סף-לכל-כלי אמיתי דורש שינוי ב-NinjaScript (לקרוא threshold לכל instrument).
4. ✅ **השוואת וריאנטים** — **בוצע** (כפתור ⚖ Compare, טבלה זו-לצד-זו עם $ edge). ראה §4.
5. **מבנה 3-תת-הוראות (A/B/C)** — לבדוק אם אימון ברמת-סיגנל (במקום תת-הוראה) נקי יותר. ← **הבא בתור**
6. **News-aware** — XT News Pro על הגרף; feature "דקות מאירוע" או חסימה סביב חדשות גדולות.

### ⚙️ תשתית
7. גיבוי/שחזור מודלים+וריאנטים (אחרי אסון ה-bar_data — קריטי).
8. תזכורת אימון-מחדש (חודשי).
9. התראה: Watch מת / ציון חוצה סף / מודל מתיישן.

---

## 6. ⚠️ פעולות פתוחות בצד ליאור (מכונת המסחר)
1. **לקמפל מחדש את `TOAIExporterGaugeTick`** — תיקון ה-ping-pong האחרון (custom-period
   לעולם לא writer). בלי זה ה-bar_data בסיכון.
   ‏⚠️ **קרה שוב ב-17/6 ~11:00**: ה-bar_data החי הצטמצם ל-~5000 ברים (כמה ימים), ו-exports חדשים
   ("1A-15min…") בשורש אימנו מול ה-bar_data המוקטן → 0 התאמות → `MES/training_data.csv` נמחק (header בלבד).
   **שוחזר** מ-`MES/bar_data_Minute-1_20260617-090455.csv` (111k ברים, היסטוריה מלאה) + ה-export "1-".
   **למנוע**: (א) לקמפל את התיקון ולטעון את גרף ה-1-דקה עם היסטוריה מלאה; (ב) **לא** לזרוק exports של
   אסטרטגיות/TF אחרים (15min) לשורש כל עוד אין להם bar_data משלהם — הם מאמנים מול ה-bar_data של MES.
2. **להפעיל מחדש את ה-Control Panel** — לטעון את מודל וריאנט 1.
3. לטעון מחדש את הגרף.
4. **(חדש) לקמפל את `TOAIExecutionLogger.cs`** — ה-AddOn שכותב את ה-fills החיים ל-
   `C:\LIOR_ML\<כלי>\executions.csv` אוטומטית (סוגר את הלולאה החיה). התקנה **פעם אחת**:
   NinjaScript Editor → New → AddOn (או הדבק את הקובץ ל-`Documents\NinjaTrader 8\bin\Custom\AddOns\`)
   → F5. רץ ברקע מההפעלה, ללא חלון. **חשוב**: ה-Control Panel חייב לרוץ בזמן המסחר כדי לקלוט את
   ה-executions.csv ל-journal.csv לפני שהסשן מתאפס. ה-watch כבר קולט אוטומטית. (חלופה ידנית: ייצוא
   Trade Performance לאותו שם.)

## 7. 🔥 לקחים/מלכודות (אל תחזור עליהן!)
- **bar_data ping-pong**: עותק BloodHound רץ על period לא-סטנדרטי (12345) ו"מארכב"=מוחק
  את ה-bar_data של הגרף בכל טעינה. **תוקן**: custom-period לעולם לא writer + single-writer.
  אם ה-bar_data מצטמצם פתאום ל-כמה ימים — זה זה. הארכיונים ב-`MES/bar_data_*.csv`.
- **Timeframe חייב להתאים**: המודל אומן על 1-דקה → הגרף חייב 1-דקה. החלפת TF מארכבת bar_data.
- **Exports → שורש `C:\LIOR_ML` תמיד** (לא תיקיית הכלי). הניתוב לפי עמודת Instrument.
- **שם export = שם וריאנט** (קבוע: `1-`, `2-`…). אותו שם = עדכון; שם חדש = וריאנט חדש.
- **לאמן רק כשהגרף טען מספיק היסטוריה** (אחרת 0 התאמות — צריך כיסוי תקופת הבקטסט).
- **single-writer**: שני מופעי exporter (גרף + BloodHound) — רק אחד כותב.
- **gate lag ~2ש'** (OnEachTick) — לא 0; סיגנל בדיוק בסגירת בר נשען על הציון הקודם.
- **DST**: ה-timestamps של NinjaTrader הם ET נכון — **בלי שום המרה** (אומת על 2679 עסקאות).
- **features יחסיים בלבד** (toai/features.py) — לעולם לא רמות מחיר אבסולוטיות.

## 8. נקודות שחזור
- ‏git: ענף `claude/magical-dirac-1yd0d4`. ‏HEAD נוכחי ≈ `ad2ced8`.
- ‏`4c808f3` = v1 יציב (לפני הגרפיקה). גיבוי פיזי: `C:\LIOR_ML_archive\code_v1_working_20260616`.
- כל מודל/וריאנט ב-`C:\LIOR_ML\<כלי>\models\` (לא ב-git).

## 9. עקרונות (לא לשבור)
- ולידציה: **walk-forward בלבד** (random-split מנופח).
- היסטוריה: ‏MLPass=1 תמיד (לא מוחקים סיגנלים); ‏gate אמיתי חי+Playback.
- אחרי שינוי ב-`ninjascript_v4_gauge_tick/`: להדביק ב-NinjaScript Editor + F5.
- עדכון קוד במכונת המסחר: ‏`TOAI_Update.bat` (git pull; העותק היחיד: C:\lior).
- אסור לקמט נתוני מסחר/model — ב-.gitignore.

---

## הצעד הראשון בצ'אט הבא
קרא את הקובץ הזה → roadmap **#1-#4 בוצעו** (Scorecard, Expectancy, סף אופטימלי, השוואת וריאנטים).
**הבא בתור: #5 — מבנה 3-תת-הוראות (A/B/C)**: לבדוק אם אימון ברמת-סיגנל (במקום תת-הוראה) נקי יותר.
‏שווה גם: לפתוח את הפאנל ולשחק עם הסליידר/ההשוואה על MES (📊 + ⚖), ואז להחליט אם להפוך את הסף
לפר-כלי אמיתי (דורש שינוי NinjaScript — ראה #3).
זרימה: כל קוד ב-git, לקמט+לדחוף אחרי כל שינוי משמעותי, לעדכן את הקובץ הזה בסוף.
