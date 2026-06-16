# TOAI v4 — TOAIExporterGaugeTick (gauge + שער מהיר, מועמד סופי)

משלב את שתי הגרסאות הניסיוניות:
- **gauge HUD** (מ-v3): ציון גדול צבעוני, פס 0–100 עם סימון הסף, מיני-היסטוריה, הבהוב בחציית סף.
- **OnEachTick** (מ-v2): השער והתצוגה מתעדכנים תוך ~2 שניות מסגירת בר, במקום פיגור של ~בר שלם.

אופטימיזציה: ‏threshold.txt ו-entry_window.txt נקראים **פעם בבר** (לא כל טיק);
‏score.txt נבדק לפי חותמת-זמן ונקרא רק כשהשתנה. כך אין עומס I/O פר-טיק.

## בטיחות (זהה לשאר הניסיונות)
- מחלקה נפרדת `TOAIExporterGaugeTick`. **`TOAIExporter` (v1) לא נגעה.**
- קימפול שנכשל → ‏NinjaTrader שומר את ה-DLL האחרון הטוב; מוחקים את הקובץ
  ומקמפלים מחדש כדי לחזור. ‏v1 מגובה: `4c808f3` + `C:\LIOR_ML_archive\code_v1_working_20260616`.

## הפעלה (כשאתה Flat)
1. ‏NinjaScript Editor → ‏New Indicator → הדבק את `TOAIExporterGaugeTick.cs` → ‏F5.
2. **שגיאת קימפול?** שלח לי את הטקסט, אתקן; בינתיים מחק את הקובץ ו-F5.
3. בגרף: הסר את ה-exporter הקודם, הוסף `TOAIExporterGaugeTick`.
4. ב-BloodHound: ‏solver → `TOAIExporterGaugeTick.MLPass`.
5. בדוק ב-Sim.

## מה לבדוק כשזה רץ
- ה-HUD: ציון, פס, סף, מיני-היסטוריה, הבהוב כשחוצים 70.
- שה-gauge מתעדכן **תוך כמה שניות** מסגירת בר (לא בר שלם).
- שאין שגיאות קבצים (התיקונים החסינים כבר בפנים).

## אם משהו לא טוב — חוזרים ל-v1
הסר את `TOAIExporterGaugeTick`, החזר `TOAIExporter`, ‏solver → `TOAIExporter.MLPass`.
