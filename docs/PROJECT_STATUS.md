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

## 3. מודל נוכחי — MES (1-דקה, BBTMP)

| וריאנט | PMV | Walk-forward | מצב |
|---|---|---|---|
| **1- (פעיל)** | 0.6734 | **0.6539** (0.629/0.664/0.676/0.646) | ACTIVE, ~4905 עסקאות |
| 2- (גיבוי) | 0.6681 | 0.6655 | שמור |
שניהם מצוינים. סף 70 → ~78% win. ‏threshold.txt=70 (shared). חלון RTH 9:30-16:00.
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
    של תוחלת לפי דלי (ירוק/אדום מקו-אפס, פס ALLOW מודגש), טבלת ALLOW/SKIP, וכותרת edge. רץ בת'רד-עובד
    (caching לפי mtime — פתיחה חוזרת/שינוי סף = מיידי). כל כרטיס-כלי מציג שורת **"filter edge"** חיה
    (מחושבת ברקע) — רואים אם הפילטר עושה כסף בלי לפתוח כלום.
  - **CLI**: `main.py` אופציה 9 (טקסט).
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

### 🔧 מודל (הבא בתור — התחל מ-#3)
3. **סף אופטימלי אוטומטי לכל וריאנט/כלי** (ממקסם תוחלת מטבלת ה-WF), במקום 70 גלובלי.
   ‏הבסיס כבר קיים: `scorecard.walk_forward_scores()` מחזיר (Score, PnL) לכל עסקה —
   סריקת ספים על זה נותנת את הסף שממקסם תוחלת.
4. **השוואת וריאנטים** — טבלאות WF זו-לצד-זו בפאנל.
5. **מבנה 3-תת-הוראות (A/B/C)** — לבדוק אם אימון ברמת-סיגנל (במקום תת-הוראה) נקי יותר.
6. **News-aware** — XT News Pro על הגרף; feature "דקות מאירוע" או חסימה סביב חדשות גדולות.

### ⚙️ תשתית
7. גיבוי/שחזור מודלים+וריאנטים (אחרי אסון ה-bar_data — קריטי).
8. תזכורת אימון-מחדש (חודשי).
9. התראה: Watch מת / ציון חוצה סף / מודל מתיישן.

---

## 6. ⚠️ פעולות פתוחות בצד ליאור (מכונת המסחר)
1. **לקמפל מחדש את `TOAIExporterGaugeTick`** — תיקון ה-ping-pong האחרון (custom-period
   לעולם לא writer). בלי זה ה-bar_data בסיכון.
2. **להפעיל מחדש את ה-Control Panel** — לטעון את מודל וריאנט 1.
3. לטעון מחדש את הגרף.

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
קרא את הקובץ הזה → ‎#1+#2 (Scorecard+Expectancy) **בוצעו** →
**התחל ב-#3: סף אופטימלי אוטומטי לכל וריאנט/כלי** (השתמש ב-`scorecard.walk_forward_scores()`
שכבר מחזיר Score+PnL לכל עסקה — סרוק ספים, מקסם תוחלת, כתוב סף-מומלץ-לכלי).
‏עדכון: גם לראות את ה-Scorecard חי (פתח את הפאנל, כפתור 📊 על MES).
זרימה: כל קוד ב-git, לקמט+לדחוף אחרי כל שינוי משמעותי, לעדכן את הקובץ הזה בסוף.
