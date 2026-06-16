# TOAI v4 — הגרסה הנבדקת (חבילה מלאה ועצמאית)

**כל מה שצריך לגרסה הנבדקת נמצא בתיקייה הזו בלבד.** אין תלות בקבצים מגרסאות
אחרות — שני האינדיקטורים כאן עצמאיים לחלוטין.

| קובץ | אינדיקטור | תפקיד |
|---|---|---|
| `TOAIExporterGaugeTick.cs` | `TOAIExporterGaugeTick` | גשר + שער (MLPass) + **gauge HUD**, ‏OnEachTick (~2ש') |
| `TOAISignalLabelGaugeTick.cs` | `TOAISignalLabelGaugeTick` | תוויות ה-% על ברי-סיגנל (ירוק/אדום/אפור) |

## מה כולל
- **gauge HUD**: ציון גדול צבעוני, פס 0–100 עם סימון הסף, מיני-היסטוריה, הבהוב בחציית סף.
- **OnEachTick**: השער והתצוגה מתעדכנים תוך ~2ש' מסגירת בר.
- כל התיקונים החסינים (FileShare + retry על כתיבה/append).
- ‏threshold/window נקראים פעם בבר; ‏score.txt רק כשמשתנה.

## הפעלה (כשאתה Flat)
1. ‏NinjaScript Editor → ‏New Indicator → הדבק את **שני** הקבצים (כל אחד
   בנפרד) → ‏F5.
2. **שגיאת קימפול?** שלח לי את הטקסט, אתקן; בינתיים מחק את הקובץ ו-F5.
3. בגרף:
   - הסר את ה-exporter ואת ה-label הישנים.
   - הוסף `TOAIExporterGaugeTick` (פאנל תחתון — שם ה-gauge).
   - הוסף `TOAISignalLabelGaugeTick` (פאנל מחיר) → ‏Input series =
     ‏BloodHound Ultimate → ‏Long Confidence.
4. ב-BloodHound (Threshold Rules): ‏solver → `TOAIExporterGaugeTick.MLPass`.
5. בדוק ב-Sim.

## חזרה ל-v1 (רשת ביטחון)
הגרסה היציבה היא תיקיית `ninjascript/` (commit `4c808f3`, גיבוי ב-
`C:\LIOR_ML_archive\code_v1_working_20260616`). לחזור: הסר את שני
האינדיקטורים של v4 מהגרף, החזר את `TOAIExporter` + `TOAISignalLabel`,
‏solver → `TOAIExporter.MLPass`.

> רק שתי גרסאות קיימות: **`ninjascript/` = יציב (v1)**, **`ninjascript_v4_gauge_tick/` = נבדק (v4)**. גרסות הביניים (v2/v3) נמחקו כדי לא לפזר.
