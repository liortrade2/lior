# חיבור TOAIExporter לאסטרטגיות הקיימות

## הארכיטקטורה (לפי המערכת של ליאור)

```
BloodHound template (קיים)          TOAIExporter (שלנו)
templates\BloodHound                 plot: MLPass = 0/1
   │  סיגנל כניסה                        │
   └──────────────┬─────────────────────┘
                  ▼
            AND Solver ב-BloodHound
                  │  סיגנל מסונן
                  ▼
        BlackBird template (קיים)
        templates\BlackBird — ניהול עסקה
```

**אין צורך לבנות אסטרטגיות חדשות** — מחברים את שכבת ה-ML לקיימות.

## ה-Plots של TOAIExporter

| Plot | ערכים | תפקיד |
|---|---|---|
| `ProbOfTrue` | 0-100 | הציון הגולמי מהמודל |
| `MLPass` | 0 או 1 | 1 = הציון ≥ threshold → מותר לסחור |

## חיבור ב-BloodHound (5 דקות)

1. פתח את ה-BloodHound template הקיים שלך → **Logic Editor**
2. הוסף Solver חדש: **Indicator Threshold** (או Indicator Comparison)
   - Indicator: **TOAIExporter** → plot: **MLPass**
   - Condition: **Greater Than** → Value: **0.5**
   - (כלומר: עובר רק כש-MLPass = 1)
3. חבר את ה-Solver החדש עם ה-AND Gate הראשי של הסיגנל הקיים
   - גם ב-Long וגם ב-Short
4. שמור את ה-template (אפשר בשם חדש: `<שם קיים>_ML`)

מעכשיו: סיגנל עובר ל-BlackBird **רק אם** גם הלוגיקה המקורית ירוקה **וגם** ה-ML מאשר.

## איך נקבע "ציון עובר"? (Threshold)

אחרי כל אימון, TOAI מדפיס **Threshold analysis** — טבלה אמיתית מנתוני הבדיקה:

```
Thresh | Trades kept | Win rate
   50  |    76 / 150 |  60.5%
   55  |    69 / 150 |  60.9%
   60  |    66 / 150 |  60.6%
   65  |    59 / 150 |  64.4%
   70  |    55 / 150 |  65.5%
Baseline (no filter): 53.8%
```

**כלל הבחירה:** הסף שבו ה-win rate המסונן גבוה משמעותית מה-baseline,
אבל עדיין נשארות מספיק עסקאות (2-5 ביום). מתחילים ב-55 ומכווננים.

## איפה מגדירים את הסף? (מקום אחד!)

**בפאנל TOAI** (python main.py → אופציה 5): שדה **"Min Probability of Win"**
→ כפתור **Set Threshold**. זה כותב את `C:\LIOR_ML\threshold.txt` —
וכל הרכיבים קוראים ממנו:

| רכיב | מתי קולט שינוי |
|---|---|
| חלון ה-Watch (Python) | מיידית (קורא בכל ציון) |
| TOAIExporter על הצ'ארט | בבר החי הבא, או ב-Reload |
| TOAISignalLabel | בבר החי הבא, או ב-Reload |
| **העותק הפנימי של BloodHound** | בבר החי הבא, או ב-Reload — אותו קובץ! |

ה-property `MinProbabilityThreshold` באינדיקטורים הוא **fallback בלבד** —
כשהקובץ קיים הוא גובר על הכל. אין יותר צורך לסנכרן שלושה מקומות ידנית.

## התנהגות על היסטוריה + Playback

ל-Python יש שני מקורות ציון:

| קובץ | מה יש בו | מתי משמש |
|---|---|---|
| `bar_scores.csv` | ציון לכל בר היסטורי (מחושב מראש מ-bar_data.csv) | היסטוריה + **Playback** |
| `score.txt` | ציון חי אחד (מה-Watch) | ברים חיים בשוק אמיתי |

`bar_scores.csv` נכתב אוטומטית: בכל אימון ("Refresh from Strategy Analyzer" /
TOAI_Train.bat), בכל הפעלה של TOAI_Watch.bat, או ידנית: `python main.py` → אופציה 7.
**אחרי שהקובץ מתעדכן — לטעון מחדש את הצ'ארט** (האינדיקטור קורא אותו בטעינה).

על ברים היסטוריים:

- קו ה-ProbOfTrue בפאנל התחתון מוצג רטרואקטיבית, והתוויות (TOAISignalLabel)
  מופיעות על כל בר-סיגנל היסטורי
- `MLPass = 1` תמיד (pass-through) — הסיגנלים ההיסטוריים של BloodHound נשארים
  על הצ'ארט; התווית `SKIP` מראה מה **היה** נחסם, בלי למחוק את הסיגנל
- ב-**Playback (Market Replay)** הברים המנוגנים הם ברי עבר שכבר נמצאים
  ב-bar_scores.csv — שם ה-gate כן פועל באמת (MLPass = 0/1 לפי הציון),
  אז Playback הוא הדרך לבדוק את הפילטר מקצה לקצה
- תנאי: bar_data.csv חייב לכסות את התקופה שמנגנים (לטעון את הצ'ארט עם מספיק
  ימים עם ExportBarData = true, ואז לעדכן את bar_scores)

## עדכון אוטומטי מ-Strategy Analyzer

כש-TOAI_Watch.bat רץ, הוא משגיח גם על תיקיית הנתונים: **שמירת export חדש
מ-Strategy Analyzer לתוך `C:\LIOR_ML` מאמנת את המודל אוטומטית** — בלי
ללחוץ על שום כפתור. אין צורך למחוק exports ישנים: החדש ביותר תמיד מנצח.
אחרי האימון ה-Watch טוען את המודל החדש מיד; לתוויות ההיסטוריות — Reload לצ'ארט.

## מעבר Timeframe (למשל 15-min → 1-min)

ה-features ב-bar_data.csv תלויים ב-timeframe (ATR20 על ברים של דקה ≠ ATR20
על ברים של 15 דקות). לכן כשמחליפים TF:

1. **לשנות שם** ל-bar_data.csv הישן (למשל `bar_data_15min.csv`) — לא למחוק
2. לפתוח צ'ארט על ה-TF החדש עם TOAIExporter (`ExportBarData = true`) ועם
   מספיק ימים לכסות את תקופת הבקטסט — bar_data.csv חדש ייבנה בטעינה
3. להריץ בקטסט על אותו TF ולשמור export ל-`C:\LIOR_ML` — האימון יקרה אוטומטית

## חיווי על הגרף

- **באנר למעלה (TOAIExporter):** `Probability of Win: 62% | TRADE ALLOWED (min 55)` — ירוק כשעובר, אדום כשנחסם
- **על בר עם סיגנל בלבד (TOAISignalLabel, כמו TradeOptima):** המספר בתוך הנר
  על תגית ירוקה (`72%` = עובר) או אדומה (`13%` = נחסם), ופס אנכי ירוק/אדום
  לכל גובה הצ'ארט (ניתן לכיבוי: `ShowSignalBand = false`)
- **פאנל תחתון (TOAIExporter):** קו כחול = ProbOfTrue, ריבועים ירוקים = MLPass (0/1), קו כתום = threshold

**חובה:** ה-Input series של TOAISignalLabel חייב להיות ה-plot של BloodHound
(לא מחיר!). אם הוא נשאר על מחיר — תופיע אזהרה צהובה בפינה הימנית-תחתונה
במקום תוויות על כל בר.

## TOAISignalLabel — תווית רק על בר עם סיגנל

התווית `62%` / `SKIP 29%` מופיעה **רק** על ברים שבהם BloodHound ירה סיגנל
(הפס הירוק), לא על כל בר. זה אינדיקטור נפרד כי TOAIExporter חייב לרוץ על
מחיר (בשביל ה-features), ואילו התווית צריכה לקרוא את ה-plot של BloodHound.

**התקנה (פעם אחת):**

1. NinjaScript Editor → Indicators → New → הדבק את `TOAISignalLabel.cs` → Compile
2. על הצ'ארט: הוסף את האינדיקטור **TOAISignalLabel**
3. בחלון ההגדרות שלו → **Input series** → בחר את ה-plot של BloodHound:
   `BloodHound Ultimate → Entry Signal US` (ה-plot שמצייר את הפס הירוק)
4. ודא ש-`MinProbabilityThreshold` זהה לזה של TOAIExporter (ברירת מחדל 55)

**איך זה עובד:** כשה-plot של BloodHound שונה מ-0 (יש סיגנל) — האינדיקטור
מחפש את ציון הבר ב-`bar_scores.csv` (היסטוריה + Playback), ואם הבר חי וטרם
בקובץ — קורא את `score.txt`. כשאין סיגנל — שום דבר לא מצויר.

**שים לב:** TOAISignalLabel דורש ש-TOAIExporter יהיה מקומפל (הוא משתמש
בפונקציה משותפת לקריאת bar_scores.csv) — לקמפל את שניהם יחד.
