# TOAI — Project Status & Handoff

> **קרא אותי ראשון בכל chat חדש.** עדכון אחרון: **2026-06-19** (RESET נקי — ראה §הצעד הראשון).
> כתוב כ-handoff מלא — הצ'אט הקודם הגיע לגבול אורך.

---

## 1. מה המערכת עושה (עובד ✅)

פילטר עסקאות ML ל-NinjaTrader. ‏BloodHound מייצר סיגנלים, ‏TOAI מחשב
Probability-of-Win לכל בר, ‏BloodHound בודק את ה-plot **MLPass** (0/1) כ-solver
וחוסם סיגנלים מתחת לסף, ‏BlackBird מנהל את העסקה (כולל בלמים: kill-switch,
תקרת-הפסד) + XABCD News Pro לחדשות. מסחר ב-**Sim101**.
‏**הצינור אגנוסטי לאסטרטגיה ול-TF** (רב-TF, ראה §3).

**מצב אסטרטגיות MES — RESET נקי (2026-06-19):** ליאור **מחק את כל נתוני/וריאנטי
האסטרטגיות** ועושה ריצת-export חדשה. **כל המסקנות הקודמות לכל אסטרטגיה (מי "עם edge",
מי "חלש", מספרי AUC/WF) — מבוטלות, לא לצטט אותן.** הן נמדדו על נתונים שכבר נמחקו.
אחרי הריצה החדשה: לנקד כל אסטרטגיה מאפס עם `python -m toai.edge_scan` (ראה §הצעד הבא).
‏BBTMP הישן הוצא משימוש.

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

**רב-TF (2026-06-17)**: MES תומך עכשיו בכמה timeframes יחד (1/3/5/15). המערכת **מזהה לבד** את ה-TF
של הגרף (`bar_data_tf.txt`) ומתאימה את המודל. כל וריאנט מתויג ב-TF שלו (מחולץ משם ה-export "…15min…",
או ה-TF החי). היסטוריית-אימון נפרדת לכל TF (`bar_data_train_<tf>min.csv`). ה-watch מסנכרן את `model.pkl`
לווריאנט הפעיל **של ה-TF החי** בכל tick — משנים TF בגרף / בוחרים אסטרטגיה בפאנל → הניקוד החי עוקב, בלי restart.
בפאנל: וריאנטים מקובצים לפי TF, ה-TF החי מסומן ● live, active נבחר נפרד לכל TF.
**זרימה**: עדכן TF בגרף → טען היסטוריה (פעם אחת ל-TF) → אמן את ה-export של אותו TF → בחר בפאנל.

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
1. **לקמפל מחדש את `TOAIExporterGaugeTick`** — (א) תיקון ה-ping-pong (custom-period לעולם לא writer);
   (ב) **חדש**: נוסף input `ScoreFileName` (ברירת-מחדל score.txt, תאימות-לאחור) לתיק פר-אסטרטגיה. בלי
   הקומפילציה ה-bar_data בסיכון וה-ScoreFileName לא קיים.
   ‏⚠️ **ה-ping-pong חזר ב-17/6** ומחק את training_data (שוחזר). **תיקוני-קוד הכניסו הגנה**: merge כבר
   לא דורס training_data לריק, ו-`bar_data_train_<tf>min.csv` שומר היסטוריה (ראה §7). אבל שורש ה-ping-pong
   הוא ה-exporter — לקמפל. **כלל**: רק גרף MES אחד רץ (15-דקות), עם היסטוריה מלאה (600 יום) ל-bar_data_train.
2. **לוודא שה-Control Panel רץ בזמן המסחר** — טוען את המודל הפעיל (Two EMA+PSAR 15-דקות) וקולט executions.
3. (BBTMP/וריאנט-1 הוצאו משימוש — לא רלוונטי יותר.)
4. ✅ **`TOAIExecutionLogger.cs` — אומת חי (2026-06-18).** עסקת-בדיקה ב-Sim101 (MES Long, +10.03$)
   כתבה `C:\LIOR_ML\MES\executions.csv`, וה-watch קלט אותה ל-`journal.csv` תוך 6ש' (Score 42.5 → SKIP,
   Variant=Two EMA+PSAR, Source=live). **הלולאה החיה סגורה מקצה-לקצה**: fill → executions.csv (AddOn) →
   journal.csv (watch, מנוקד מול ה-gate). התקנה **פעם אחת**: NinjaScript Editor → New → AddOn → F5; רץ
   ברקע ללא חלון. **חשוב**: ה-Control Panel חייב לרוץ בזמן המסחר כדי לקלוט executions.csv ל-journal.csv
   לפני שהסשן מתאפס (ה-watch קולט אוטומטית). הצעד הבא: לצבור עסקאות חיות → 📊 Scorecard במצב "Realized
   fills" יראה אם ה-edge מתממש בכסף.

## 7. 🔥 לקחים/מלכודות (אל תחזור עליהן!)
- **bar_data ping-pong**: עותק BloodHound רץ על period לא-סטנדרטי (12345) ו"מארכב"=מוחק
  את ה-bar_data של הגרף בכל טעינה. **תוקן**: custom-period לעולם לא writer + single-writer.
  אם ה-bar_data מצטמצם פתאום ל-כמה ימים — זה זה. הארכיונים ב-`MES/bar_data_*.csv`.
- **Timeframe חייב להתאים**: המודל אומן על 1-דקה → הגרף חייב 1-דקה. החלפת TF מארכבת bar_data.
- **הפרדת אימון/חי (תוקן 2026-06-17)**: `bar_data.csv` = חי-מתגלגל (טען 5 ימים ליום-יום).
  `bar_data_train.csv` = איחוד מוקפא של כל הברים שנראו (אותו TF, dedup, רק גדל). **האימון קורא מהמוקפא**,
  אז **F5 של 5 ימים כבר לא דורס את היסטוריית האימון**. ה-watch מגדיל את קובץ-האימון כשברים מגיעים;
  build_and_train מאחד גם מהארכיונים. החלפת TF מאפסת את קובץ-האימון ל-TF החדש.
- **Exports → שורש `C:\LIOR_ML` תמיד** (לא תיקיית הכלי). הניתוב לפי עמודת Instrument.
- **שם export = שם וריאנט** (קבוע: `1-`, `2-`…). אותו שם = עדכון; שם חדש = וריאנט חדש.
- **לאמן רק כשהגרף טען מספיק היסטוריה** (אחרת 0 התאמות — צריך כיסוי תקופת הבקטסט).
- **single-writer**: שני מופעי exporter (גרף + BloodHound) — רק אחד כותב.
- **gate lag ~2ש'** (OnEachTick) — לא 0; סיגנל בדיוק בסגירת בר נשען על הציון הקודם.
- **DST**: ה-timestamps של NinjaTrader הם ET נכון — **בלי שום המרה** (אומת על 2679 עסקאות).
- **features יחסיים בלבד** (toai/features.py) — לעולם לא רמות מחיר אבסולוטיות.
- **Edgewonk: לייבא דרך ה-importer של NinjaTrader, לא Generic** (אומת חי 2026-06-19).
  ל-Edgewonk יש 2 importers: ה-**Generic** (תבנית עם Custom Stats) **מרסק תאריכים ל-1899-12-31**
  (קורא תאריך כמספר; נכשל על טקסט וגם על תא-datetime אמיתי). ה-**NinjaTrader importer** קורא נכון
  ומצפה ל-19 עמודות = `EDGEWONK_COLUMNS`. הייצוא-החי (`edgewonk._nt_live_rows`) כותב בדיוק את
  הפריסה הזו עם תאי datetime אמיתיים; ML score/Verdict ב-`Entry name`, Variant ב-`Strategy`
  (אין Custom Stats בפריסה הזו). בצד ליאור: Settings→Import→NinjaTrader + NinjaTrader בשפה אנגלית.

## 8. נקודות שחזור
- ‏git: ענף `claude/magical-dirac-1yd0d4`. ‏HEAD נוכחי ≈ `de916ff` (נדחף).
- **נבנה 2026-06-19 (הכול נדחף):**
  - **ייצוא Edgewonk חי** — לא הבקטסט אלא ה-fills האמיתיים (`executions.csv`), קובץ-יום
    מתוארך (`<inst>_live_<תאריך>.xlsx`), אוטומטי דרך ה-watch + כפתור force, פורמט ילידי
    עם **Custom Stats** (ML score/Verdict/Variant/Threshold) + Setup. SL/TP/MAE/MFE/Commission
    מ-executions.csv (דורש קימפול AddOn).
  - **מצב PLAYBACK מבודד** — שורש `C:\LIOR_ML_PLAYBACK`, מתג `PlaybackMode` ב-3 האינדיקטורים,
    ניתוב חשבון Playback101 ב-AddOn, `TOAI_Playback.bat` + `toai/playback.py` (סנכרון מודלים, ממזג).
  - **בורר TF לאימון פר-מכשיר** (כרטיס: Auto/1/2/3/5/15) → `<inst>/train_tf.txt`.
  - **התקשחות (7 תיקונים, `d5ad63f`):** סף פר-מכשיר (`<inst>/threshold.txt`+fallback), גיבוי
    אוטומטי אחרי אימון (`toai/backup.py` → D:\TOAI_Backups), executions עמידות
    (`executions_<date>.csv`+catch-up), חלון-פאנל לפי זמן-בר ET, playback-sync ממזג, dedup
    עם ExitTime (scalping), בדיקת-שפיות SL/TP. **`TOAIExporterGaugeTick`+`TOAIExecutionLogger`
    שונו — לקמפל.**
  - **בריאות מודל (`de916ff`)** — `toai/health.py`: התראת מודל מתיישן (>30 ימים) + drift
    (edge חי מול בקטסט) בכרטיס הפאנל + main.py אופ' 14.
  - **#9 (אותו מכשיר רב-TF חי במקביל) — נדחה** ביוזמת ליאור. כשיידרש: גישה A (קבצי
    `bar_data_<tf>min.csv`/`score_<tf>min.txt` באותה תיקייה, מנצל וריאנטים מתויגי-TF).
- **תיקוני 2026-06-18 (נדחפו):** (א) וריאנט expectancy יורש את ה-TF של הבסיס —
- **תיקוני 2026-06-18 (נדחפו):** (א) וריאנט expectancy יורש את ה-TF של הבסיס —
  אחרת לא יכל לעלות לאוויר אחרי Activate (`66eb713`). (ב) `TOAI_Panel.bat` מפעיל
  עכשיו את ה-Control Panel החדש, לא את gui.py הישן (`28e1517`). (ג) **ה-Scorecard
  וה-edge footer מנקדים את הווריאנט הפעיל** (snapshot שלו) ולא את ה-export האחרון
  שאומן — היה מציג edge של אסטרטגיה לא-פעילה (MES החי: ‎+57.94$/PF4.01, לא ‎-13.54$)
  (`7b2c73a`). (ד) כפתורי "Jump to optimal" בחלון ה-Scorecard (`779e2b2`).
  אומת חי: BloodHound solver = MLPass≥1 לשני הכיוונים; AddOn ה-executions קומפל.
- ‏`4c808f3` = v1 יציב (לפני הגרפיקה). גיבוי פיזי: `C:\LIOR_ML_archive\code_v1_working_20260616`.
- כל מודל/וריאנט ב-`C:\LIOR_ML\<כלי>\models\` (לא ב-git).

## 9. עקרונות (לא לשבור)
- ולידציה: **walk-forward בלבד** (random-split מנופח).
- היסטוריה: ‏MLPass=1 תמיד (לא מוחקים סיגנלים); ‏gate אמיתי חי+Playback.
- אחרי שינוי ב-`ninjascript_v4_gauge_tick/`: להדביק ב-NinjaScript Editor + F5.
- עדכון קוד במכונת המסחר: ‏`TOAI_Update.bat` (git pull; העותק היחיד: C:\lior).
- אסור לקמט נתוני מסחר/model — ב-.gitignore.

---

## הצעד הראשון בצ'אט הבא (עדכון 2026-06-19 — RESET נקי)

### 🔄 מצב: ריצה חדשה מאפס
ליאור **מחק את כל נתוני/וריאנטי האסטרטגיות הקיימים** ועושה ריצת-export חדשה ונקייה.
**אין מסקנות-אסטרטגיה שמועברות הלאה** — כל המספרים והוורדיקטים הקודמים (איזו אסטרטגיה
"עם edge", איזו "חלשה", כל AUC/WF) נמדדו על נתונים שנמחקו ו**אסור לצטט אותם**. המסגרת
תקינה — רק הנתונים והמסקנות אופסו.

> ⏵ **הריצה הנוכחית של 1a/MES היא ב-PLAYBACK** (Market Replay, שורש `C:\LIOR_ML_PLAYBACK`) —
> כל המספרים שנראו (1a PMV 0.59 / WF 0.56, scorecard, "edge") הם **replay, לא כסף חי**. הפאנל
> וה-Scorecard מסמנים עכשיו PLAYBACK בראש החלון, ומילת ה-drift היא "replay edge" (לא "live").

### 🧪 המבחן ל-edge אמיתי (לא השתנה — 3 תנאים יחד):
‏WF-AUC **>0.55** + win% עולה מונוטונית עם הציון + עקומת ALLOW מעל "לסחור הכול".
כלי מוכן לכך: **`python -m toai.edge_scan '<glob ל-*_training.csv>'`** — בדיקה read-only
שמריצה את 3 התנאים על כל dataset ומדרגת אותם (פלט ASCII, לא נוגע ב-model.pkl/וריאנטים).

### הצעד הבא — אחרי שהריצה החדשה מסתיימת ("לעשות הכל"):
1. לטעון היסטוריה מלאה לכל אסטרטגיה/TF שרוצים לבדוק → לאמן (כפתור **⚙ Train export** או ה-watch).
2. להריץ **`toai.edge_scan`** על כל ה-`*_training.csv` החדשים → לראות מי עובר 3/3.
3. לכל אסטרטגיה שעוברת: לבדוק ב-📊 Scorecard את ה-$ edge out-of-sample, ולהפעיל וריאנט.
4. תיק חי: לבחור 2-3 אסטרטגיות מאומתות (3/3) בקורלציה נמוכה.

### החלטות פתוחות (תלויות-נתונים — ימתינו לריצה החדשה):
- **תיק חי** — צריך 2-3 אסטרטגיות מאומתות (WF>0.55 + 3/3) בקורלציה נמוכה. מספר ה-edges כרגע **לא ידוע** (לפני הריצה).
- **Tier-2 sizing** — `sizing` (main אופ' 12) על מודל גדול; לחווט רק אם net/DD עולה.

### ⚠️ צד ליאור — לקמפל מחדש NinjaScript (שינויי 2026-06-19):
`TOAIExporterGaugeTick` (סף פר-מכשיר + PlaybackMode) ו-`TOAIExecutionLogger`
(executions_<date>.csv עמידים + SL/TP/MAE/MFE/Commission + ניתוב Playback101). הדבק + F5.
וכל פעם להפעיל מחדש `TOAI_Control.bat` אחרי שינוי Python.

זרימה: כל קוד ב-git, לקמט+לדחוף אחרי כל שינוי, לעדכן את הקובץ הזה בסוף.
