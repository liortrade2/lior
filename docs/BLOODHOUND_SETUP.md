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

## איפה מגדירים את הסף? (יש 3 מקומות!)

| מקום | מה הוא שולט | איך משנים |
|---|---|---|
| **BloodHound** — Select Indicator → `TOAIExporter(true,55)` → `MinProbabilityThreshold` | **ה-gate האמיתי!** BloodHound מריץ עותק נפרד של האינדיקטור עם הפרמטרים האלה | בתוך ה-Logic Editor, לחיצה על שורת האינדיקטור |
| **NinjaTrader** — TOAIExporter על הצ'ארט → `MinProbabilityThreshold` | רק התצוגה (באנר + תוויות + פאנל) | בחלון ה-Indicators על הצ'ארט |
| **Python** — `toai/config.py` → `MIN_PROBABILITY_THRESHOLD` | התצוגה בחלון ה-Watch | עריכת הקובץ |

**מלכודת נפוצה:** שינוי הסף על הצ'ארט **לא** משפיע על BloodHound — לו יש
עותק נפרד עם הפרמטרים שמוגדרים ב-Select Indicator. תמיד לעדכן את שלושתם יחד.

## התנהגות על היסטוריה (חשוב להבין)

הציון של Python קיים **רק בזמן אמת**. לכן על ברים היסטוריים:

- `MLPass = 1` תמיד (pass-through) — הסיגנלים ההיסטוריים של BloodHound
  נשארים על הצ'ארט ולא נמחקים
- אין באנר ואין תוויות על ברים היסטוריים
- ה-gate של ה-ML פועל **רק על ברים חיים**

המשמעות: בדיקת הפילטר נעשית ב-Replay / שוק חי, כשה-Watch של Python רץ.

## חיווי על הגרף

- **באנר למעלה:** `Probability of Win: 62% | TRADE ALLOWED (min 55)` — ירוק כשעובר, אדום כשנחסם
- **תווית מעל כל בר חי (כמו TradeOptima):** ירוק `62%` = ה-gate פתוח, אדום `SKIP 29%` = חסום
- **פאנל תחתון:** קו כחול = ProbOfTrue, ריבועים ירוקים = MLPass (0/1), קו כתום = threshold
