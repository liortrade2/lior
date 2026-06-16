# TOAI v4 — הגרסה הנבדקת (חבילה מלאה ועצמאית)

**כל מה שצריך לגרסה הנבדקת נמצא בתיקייה הזו בלבד.** אין תלות בקבצים מגרסאות
אחרות — שני האינדיקטורים כאן עצמאיים לחלוטין.

| קובץ | אינדיקטור | תפקיד |
|---|---|---|
| `TOAIExporterGaugeTick.cs` | `TOAIExporterGaugeTick` | גשר + שער (MLPass) + קו ProbOfTrue, ‏OnEachTick (~2ש'). יש בו HUD טקסטואלי כ-fallback (מתג `ShowTextHud`). |
| `TOAIGaugeHUD.cs` | `TOAIGaugeHUD` | **gauge גרפי** (SharpDX) על פאנל המחיר — overlay נפרד |
| `TOAISignalLabelGaugeTick.cs` | `TOAISignalLabelGaugeTick` | תוויות ה-% על ברי-סיגנל (ירוק/אדום/אפור) |

**ה-gauge הגרפי (TOAIGaugeHUD)** הוא overlay על פאנל המחיר (שם OnRender לא
נחתך) — זה הפתרון להצגת גרפיקה אמיתית, לא תווי-טקסט. הוא רק מציג; הגשר והשער
נשארים ב-TOAIExporterGaugeTick.

## מה כולל
- **gauge HUD**: ציון גדול צבעוני, פס 0–100 עם סימון הסף, מיני-היסטוריה, הבהוב בחציית סף.
- **OnEachTick**: השער והתצוגה מתעדכנים תוך ~2ש' מסגירת בר.
- כל התיקונים החסינים (FileShare + retry על כתיבה/append).
- ‏threshold/window נקראים פעם בבר; ‏score.txt רק כשמשתנה.

## הפעלה (כשאתה Flat)
1. ‏NinjaScript Editor → ‏New Indicator → הדבק את **שלושת** הקבצים (כל אחד
   בנפרד) → ‏F5.
2. **שגיאת קימפול?** שלח לי את הטקסט, אתקן; בינתיים מחק את הקובץ ו-F5.
3. בגרף:
   - הסר את ה-exporter/label/HUD הישנים.
   - הוסף `TOAIExporterGaugeTick` (פאנל תחתון). ב-properties שלו:
     **`ShowTextHud` = false** (כדי שלא יוצג באנר טקסט כפול ל-gauge הגרפי).
   - הוסף `TOAIGaugeHUD` (פאנל מחיר — ה-gauge הגרפי).
   - הוסף `TOAISignalLabelGaugeTick` (פאנל מחיר) → ‏Input series =
     ‏BloodHound Ultimate → ‏Long Confidence.
4. ב-BloodHound (Threshold Rules): ‏solver → `TOAIExporterGaugeTick.MLPass`.
5. בדוק ב-Sim.

> אם ה-gauge הגרפי לא מופיע — הסר את `TOAIGaugeHUD`, החזר את
> `ShowTextHud = true` ב-exporter, ותקבל את ה-HUD הטקסטואלי האמין.

## חזרה ל-v1 (רשת ביטחון)
הגרסה היציבה היא תיקיית `ninjascript/` (commit `4c808f3`, גיבוי ב-
`C:\LIOR_ML_archive\code_v1_working_20260616`). לחזור: הסר את שני
האינדיקטורים של v4 מהגרף, החזר את `TOAIExporter` + `TOAISignalLabel`,
‏solver → `TOAIExporter.MLPass`.

> רק שתי גרסאות קיימות: **`ninjascript/` = יציב (v1)**, **`ninjascript_v4_gauge_tick/` = נבדק (v4)**. גרסות הביניים (v2/v3) נמחקו כדי לא לפזר.
