# TOAI — Project Status (handoff לשיחה חדשה)

> עדכון אחרון: **2026-06-11 לילה**. קרא את הקובץ הזה בתחילת כל session חדש.

## מה המערכת עושה (עובד ✅)

פילטר עסקאות ML ל-NinjaTrader: BloodHound מייצר סיגנלים (Double CCI Scalping),
TOAI מחשב Probability-of-Win לכל בר, BloodHound בודק את `TOAIExporter.MLPass`
(0/1) כ-solver וחוסם סיגנלים מתחת לסף. BlackBird מנהל את העסקה.

## ארכיטקטורה — קבצים ב-C:\LIOR_ML (הנתונים, לא ב-git)

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

## צעדים פתוחים (בצד ליאור — על מכונת המסחר)

1. ~~לקמפל מחדש את TOAIExporter.cs~~ ✔ בוצע — אומת שאין כפילויות.
2. **להפעיל מחדש את ה-Watch** (TOAI_Watch.bat) — ‏score.txt לא מתעדכן
   (נעצר 22:37); המודל החדש (239 עסקאות) ייטען רק ב-Watch טרי.
3. **לטעון מחדש את הצ'ארט** — לקלוט את bar_scores.csv החדש לתוויות.
4. בדיקת קצה-לקצה ב-Playback על תקופה שלא הייתה באימון, לוודא שה-gate
   חוסם בפועל לפי הסף.
5. **Input series של TOAISignalLabel מתאפס למחיר** אחרי קימפול — להגדיר
   שוב: Indicators → TOAISignalLabel → Input series → BloodHound Ultimate →
   Plot = Long Confidence (האזהרה הצהובה על הצ'ארט מזהה את זה).
6. shorts: אם האסטרטגיה סוחרת שורט — עותק שני של TOAISignalLabel עם
   Short Confidence.
7. בדיקת קצה-לקצה ב-Playback (שם ה-gate באמת חוסם, בניגוד להיסטוריה שהיא
   pass-through).

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
- threshold.txt = **70** (טרם אומת walk-forward על המודל הנוכחי)
- bar_data_tf.txt = Minute-15

## היסטוריה / נקודות שחזור
- `61ec668` = מערכת 15-min עובדת מלאה, 221 עסקאות, PMV 0.5982, WF 0.5396
  (ראה RESTORE_POINTS.md) — לפני ניסוי ה-1-min.
- 2026-06-11: ניסוי 1-min בוצע ונכשל ב-walk-forward (0.488) → חזרה ל-15-min.
- 2026-06-11 לילה: features יחסיים + דה-דופ ייצוא + דחיסת bar_data.
