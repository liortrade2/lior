# TOAI — Restore Points (נקודות שחזור)

כל נקודה היא commit שנמצא ב-GitHub. שחזור מלא של הקוד לנקודה:

```
git checkout <hash> -- .
git commit -m "Restore to <hash>"
```

(הנתונים ב-C:\LIOR_ML לא נשמרים ב-git — לגבות אותם בנפרד עם TOAI_Backup.bat)

| תאריך | Commit | מצב |
|---|---|---|
| 2026-06-12 | `61ec668` | **מערכת עובדת מלאה על ES 15-min**: תוויות TradeOptima-style על ברי-סיגנל, threshold.txt כמקור יחיד (70), ציונים רטרואקטיביים + Playback, אימון על 221 עסקאות Double CCI (PMV 0.5982, WF 0.5396). לפני המעבר ל-1-min. |
| 2026-06-11 | `bc0dabb` | **features יחסיים (חסרי-סקייל)**: אחרי כישלון ניסוי ה-1-min וחזרה ל-15-min. המודל מאומן על נגזרות יחסיות (toai/features.py) במקום רמות מחיר — חסין לעליית השוק ול-rollover. דה-דופ בייצוא + דחיסת bar_data. דורש קימפול מחדש של TOAIExporter.cs. |
| 2026-06-16 | `4c808f3` | **גרסה יציבה חיה (v1)**: רב-מכשירי (סל מיקרו MES/MNQ/M2K/MYM/MCL/MGC/MBT), חלון RTH לכל מכשיר, שעון ET ישיר (בלי המרת DST), גשר חי חסין-race. MES מאומן (BBTMP, PMV 0.656). **נקודת החזרה אם ניסוי ה-Tick משתבש.** גיבוי פיזי: `C:\LIOR_ML_archive\code_v1_working_20260616`. הניסוי (TOAIExporterTick, OnEachTick) ב-`ninjascript_v2_onTick/` — מחלקה נפרדת, לא נוגעת ב-v1. |
