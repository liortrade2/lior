# TOAI — Project Status (handoff לשיחה חדשה)

> עדכון אחרון: **2026-06-12 בוקר**. קרא את הקובץ הזה בתחילת כל session חדש.

## מה המערכת עושה (עובד ✅)

פילטר עסקאות ML ל-NinjaTrader: BloodHound מייצר סיגנלים (Double CCI Scalping),
TOAI מחשב Probability-of-Win לכל בר, BloodHound בודק את `TOAIExporter.MLPass`
(0/1) כ-solver וחוסם סיגנלים מתחת לסף. BlackBird מנהל את העסקה.

## ארכיטקטורה — קבצים ב-C:\LIOR_ML (הנתונים, לא ב-git)

**רב-מכשירי (2026-06-11):** כל מכשיר בתת-תיקייה משלו — `C:\LIOR_ML\ES\`,
`C:\LIOR_ML\NQ\`… — וכל הקבצים בטבלה (חוץ מ-threshold.txt וה-exports)
חיים בתוכה. ‏TOAIExporter/TOAISignalLabel גוזרים את התיקייה מהמכשיר של
הגרף; ה-Watch האחד מנטר את כל התיקיות במקביל ומדפיס `[ES] ProbOfTrue…`;
‏export של Strategy Analyzer נשמר ל-root ומנותב אוטומטית לפי עמודת
Instrument. ‏threshold.txt נשאר ב-root — סף אחד לכל הגרפים. מגבלה:
‏timeframe אחד פעיל לכל מכשיר (שני גרפים של אותו מכשיר ב-TF שונה יתנגשו).

| קובץ | מי כותב | מי קורא |
|---|---|---|
| bar_data.csv | TOAIExporter (כל בר + 11 features גולמיים) | merge / score_history |
| bar_data_tf.txt | TOAIExporter | TOAIExporter (זיהוי החלפת TF → ארכוב אוטומטי) |
| `<שם כלשהו>.csv` | המשתמש (export מ-Strategy Analyzer) | ה-Watch מזהה חדש → **אימון אוטומטי** |
| training_data.csv | merge (trades + bars, עמודות גולמיות) | train |
| model.pkl | train (GB + GridSearch + walk-forward) | score / score_history |
| bar_scores.csv | score_history (ציון לכל בר היסטורי) | האינדיקטורים — היסטוריה + Playback |
| current_features.csv | TOAIExporter (בר חי) | Watch |
| score.txt | Watch (ציון חי 0-100) | TOAIExporter |
| **threshold.txt** | **הפאנל (Set Threshold) — המקור היחיד לסף!** | הכל: Watch, שני האינדיקטורים, העותק של BloodHound |

## מצב נוכחי — חזרה ל-15-min + features יחסיים

### מה קרה ב-2026-06-11 (בסדר כרונולוגי)
1. **ניסוי 1-min הסתיים בשלילה** — 1,200 עסקאות, walk-forward ‏0.488 < 0.5,
   טבלת ספים שטוחה מתחת ל-baseline, והאסטרטגיה עצמה מפסידה על 1-min ‏(-32K).
2. **חזרה ל-15-min** — bar_data נבנה מחדש (Minute-15), export חדש מה-Strategy
   Analyzer (ינו 2025–ינו 2026, ‏122 עסקאות, win rate ‏50%), אימון אוטומטי.
3. **אומתה סוגיית ES JUN26 על שנה אחורה** — תקין: ‏Merge Policy =
   MergeBackAdjusted ממזג חוזים קודמים אוטומטית. הוכח אמפירית (עסקאות בכל
   13 החודשים, מחיר רציף).
4. **נמצא ותוקן עיוות רמת-מחיר במודל**: ‏EMA9/20/50 נכנסו כמחירים אבסולוטיים;
   המודל העניש כל בר עכשווי כי ES ב-7,300 בעוד האימון ראה 6,200–6,600
   (ועם back-adjustment כל ההיסטוריה זזה בכל rollover). בבר לדוגמה
   (2026-06-11 11:30, ציון 24) זה היה שווה ~30 נקודות ציון.

### התיקון — features יחסיים (toai/features.py)
המודל מאומן עכשיו על נגזרות חסרות-סקייל בלבד; חוזה ה-CSV מול NinjaScript לא השתנה:
`ATR_Pct, EMA9_vs_EMA20, EMA20_vs_EMA50, RSI14, ADX14, SwingHigh_ATR,
SwingLow_ATR, Volume_Ratio, BB_Width_ATR, ZScore`
- אימות: הזזת השוק +800 נק' משנה את הציון ב-0.0 בדיוק (לפני: ~30 נק').
- בנוסף: ‏TOAIExporter.cs מסנן עכשיו ברים שכבר יוצאו (HashSet) —
  סוף לכפילויות בכל טעינת צ'ארט; ‏score_history דוחס את bar_data.csv הקיים
  (בוצע: 645K שורות → 17.7K, ‏103MB → 3.3MB).

### מודל נוכחי (model.pkl) — בקטסט שנתיים, ינו 2024–ינו 2026
- **239 עסקאות 15-min** (כולן נמצאו ב-bar_data), win rate ‏47.7%.
- **Walk-forward PMV: ‏0.5219 > 0.5 ✔** (folds: ‏0.620, 0.475, 0.526, 0.468)
  — ה-edge מחזיק על נתוני עתיד, אבל חלש ולא יציב (רק fold אחד חזק).
- טבלת הספים ההגונה (WF): סף 70 → ‏58.1% win על 43/192 עסקאות
  (baseline ‏53.1%) — הסף הנוכחי 70 הוא השורה הטובה בטבלה. שים לב:
  ‏43 עסקאות ≈ ‏2 בחודש בלבד; סף 55 שומר 60 עסקאות עם 55.0%.
- ‏PMV על random-split: ‏0.4133 — נמוך, אבל לפי העקרונות random-split
  מנופח/רועש ומתעלמים ממנו; ‏walk-forward הוא המדד.
- אומת בנתונים: ה-Exporter המקומפל החדש עובד — ‏24,259 שורות bar_data,
  ‏0 כפילויות אחרי טעינות חוזרות.

### חלון כניסה + feature זמן (2026-06-12)
- ‏`TimeOfDay_Min` נוסף ל-features — מחושב ב**שעון הסשן (US Eastern אמיתי)**,
  לא בשעון הצ'ארט: זמני הצ'ארט קופצים שעה בכל מעבר DST אמריקאי (אומת על
  שנתיים של כניסות — 09:00 כל החורף, 08:00 כל הקיץ, היפוך בדיוק בתאריכי
  ה-DST). ההמרה: stamp ⇐ fixed UTC-5 ⇐ America/New_York.
- **תוקן 2026-06-12: אין יותר המרת timezone.** ‏export של 2,679 עסקאות
  MES הוכיח ש-NinjaTrader כבר מייצא Eastern עם DST (כניסות RTH ב-09:42–16:00
  גם בחורף וגם בקיץ — אין קפיצה). המרת UTC-5⇒Eastern הקודמת (שהתבססה על
  "קפיצה" בדגימת Double CCI קטנה ורועשת) רק הוסיפה שעה שגויה בקיץ. עכשיו
  ‏`TimeOfDay_Min`, ה-window וה-banner משתמשים בשעון ה-stamp הגולמי ישירות.
- ‏`entry_window.txt` בדקות שעון-צ'ארט; ‏`SessionMinutes` מחזיר זמן גולמי.
- ‏override ידני: `entry_window_manual.txt` (למשל `9:30-16:00`). **הוגדר
  ל-ES ול-MES = ‏9:30-16:00** — gate על כל סשן ה-RTH, לא רק שעות הכניסה.
- **תוויות (2026-06-12): כל הסיגנלים מקבלים ציון.** בתוך החלון —
  ירוק/אדום לפי הסף + פס רקע; מחוץ לחלון — **תווית אפורה** (מידע, לא
  תחזית סחירה; בלי פס; ‏gate חי חסום + באנר אפור). ‏bar_scores מכסה את
  כל הברים.
- **פער פתוח מול ה-Scheduler**: הבקטסט הישן נכנס 09:00–11:15 ET ויצא עד
  15:00, וה-Scheduler מציג 9:30–16:00 ET — ל-template ‏(PT_x) כנראה
  מגבלות זמן פנימיות. ה-export החדש (06-12) כבר נכנס 10:00–13:15 ET —
  ייתכן שליאור שינה הגדרות. ליישר ולהריץ בקטסט ארוך.

### ⭐ אסטרטגיה: BBTMP Bollinger Volatility Spike — מצב 2026-06-16
ליאור על **BBTMP Bollinger 2.5 Volatility Spike** (לוגיקה 1-CCI EMA MACD_RTH),
‏MES SEP26 **1-דקה** (עבר מ-2-דקה ל-1-דקה; הכל עקבי — bar_data, מודל, גרף).
- **MES**: ‏4,908 עסקאות אימון (ינו 2025–ינו 2026). ‏**PMV ‏0.6681,
  ‏Walk-forward ‏0.641/0.677/0.671/0.673** — כל ה-folds גבוהים ועקביים.
  **המודל הכי טוב בפרויקט.** סף 70, חלון RTH (override 9:30-16:00).
- **גרסה חיה = v4** (`ninjascript_v4_gauge_tick/`): ‏TOAIExporterGaugeTick
  (גשר+שער+קו, ‏OnEachTick, ‏ShowTextHud=false) + ‏TOAIGaugeHUD (gauge גרפי
  SharpDX על פאנל המחיר) + ‏TOAISignalLabelGaugeTick ×2 (Long+Short Confidence
  → תוויות על שני הכיוונים). ‏v1 (`ninjascript/`) = fallback בלבד.
- **BloodHound solver**: ‏`TOAIExporterGaugeTick.MLPass >= 1` ל-**שני**
  הכיוונים (לא `>0`/`<0` — זה חוסם את כל השורטים!).

### באגים שתוקנו (2026-06-16)
- **single-writer**: הגרף ועותק ה-solver של BloodHound כתבו שניהם bar_data →
  כפילות (38MB, 50% dups). מנגנון owner סטטי לכל מכשיר → רק מופע אחד כותב.
  גם מבטל את ה-race על current_features. (תוקן ב-v4; ‏v1 עם אותה בעיה
  לטנטית-לא-מזיקה — deduped בקריאה.)
- **bar_scores מתיישן** (מתחדש רק בהפעלת Watch): מינורי, נפתר בטעינת צ'ארט /
  restart ל-Watch. בר-סיגנל חי משתמש ב-score.txt עד אז.

## צעדים פתוחים (בצד ליאור — על מכונת המסחר)

1. **לקמפל את שני קבצי ה-NinjaScript יחד** (TOAIExporter + TOAISignalLabel,
   גרסת התוויות האפורות + SessionMinutes) — פורמט entry_window.txt השתנה
   לדקות-סשן; ערבוב גרסאות יפרש אותו לא נכון.
2. **בקטסט ארוך עם ההגדרות הנוכחיות** (ינו 2024→היום, ES) + ‏export —
   מחליף את מודל ה-43 החלש.
3. ‏MES ו-NQ: התיקיות כבר קיימות (גרפים נפתחו) — בקטסט + export לכל אחד.
4. בדיקת קצה-לקצה ב-Playback על תקופה שלא הייתה באימון, לוודא שה-gate
   חוסם בפועל לפי הסף.
5. ‏shorts: אם האסטרטגיה סוחרת שורט — עותק שני של TOAISignalLabel עם
   Short Confidence; ולוודא שחוק ה-Threshold Rules ב-BloodHound קורא את
   ‏plot ‏**MLPass** (0/1) ולא את ProbOfTrue (0–100, ‏>=0.5 יעבור הכל!).
6. אחרי שהכל יציב: לנקות קבצי legacy מהשורש (bar_data/model/scores הישנים
   ב-`C:\LIOR_ML` עצמו — הכל חי היום בתתי-התיקיות).

## עקרונות שנקבעו (לא לשבור!)

- היסטוריה: MLPass=1 תמיד (לא מוחקים סיגנלים של BloodHound); התוויות מראות
  מה *היה* נחסם. ב-Playback וחי — ה-gate אמיתי
- ולידציה: walk-forward בלבד לבחירת סף (random-split מנופח, להתעלם)
- ה-ML מאומן רק על features יחסיים/חסרי-סקייל (toai/features.py) — לעולם לא
  על רמות מחיר אבסולוטיות (non-stationary + back-adjustment shifts)
- TOAISignalLabel דורש TOAIExporter מקומפל (פונקציות סטטיות משותפות)
- אחרי כל שינוי ב-ninjascript/: להדביק ב-NinjaScript Editor + F5 (ידני)
- עדכון קוד במכונת המסחר: TOAI_Update.bat (העותק היחיד: C:\lior)

## תצורה חיה (C:\LIOR_ML)
- threshold.txt = **70** (shared לכל המכשירים)
- **סל מסחר = 7 מיקרו-חוזים** (2026-06-12): ‏MES, MNQ, M2K, MYM, MCL, MGC, MBT.
  כל אחד תיקייה משלו. ‏ES ו-NQ הישנים + קבצי root ישנים הועברו ל-
  `C:\LIOR_ML_archive\20260612` (הפיך).
- **חלון מסחר לכל מכשיר:**
  - מדדי מניות (MES/MNQ/M2K/MYM): `entry_window_manual.txt` = `9:30-16:00` (RTH).
  - ‏MCL (נפט ‏9:00–14:30), MGC (זהב ‏8:20–13:30), MBT (ביטקוין ~24/7):
    **אין override** — החלון נגזר אוטומטית מהבקטסט. להגדיר Scheduler מתאים
    לכל אחד (לא RTH מניות!).
- **מצב מודלים:** רק **MES** מאומן (BBTMP, ‏PMV 0.656, WF חזק). ששת
  האחרים = תיקייה + override מוכנים, **אין model.pkl** — כל אחד דורש
  גרף + בקטסט + export משלו כדי להתאמן.
- שעון: ה-timestamps של NinjaTrader הם Eastern עם DST תקין — שום המרה.

## היסטוריה / נקודות שחזור
- `61ec668` = מערכת 15-min עובדת מלאה, 221 עסקאות, PMV 0.5982, WF 0.5396
  (ראה RESTORE_POINTS.md) — לפני ניסוי ה-1-min.
- 2026-06-11: ניסוי 1-min בוצע ונכשל ב-walk-forward (0.488) → חזרה ל-15-min.
- 2026-06-11 לילה: features יחסיים + דה-דופ ייצוא + דחיסת bar_data.
