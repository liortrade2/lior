# TOAI גרסה ניסיונית — TOAIExporterGauge (באנר gauge ויזואלי)

מחליף את באנר הטקסט הפשוט ב-**HUD עם מד (gauge)** שמצויר ב-OnRender (SharpDX):
- ציון גדול צבעוני + מילה (ALLOWED / SKIPPED / GATE CLOSED)
- **פס 0–100** עם סימון הסף, ממולא עד הציון
- **מיני-היסטוריה** — הציונים האחרונים כפסים קטנים (מגמה במבט)
- **הבהוב** קצר כשהציון חוצה כלפי מעלה את הסף

הגשר והשער זהים ל-TOAIExporter היציב (OnBarClose, אותם קבצים, אותו MLPass
ל-BloodHound) — רק התצוגה משתנה.

## בטיחות
- מחלקה נפרדת `TOAIExporterGauge`. **`TOAIExporter` (v1) לא נגעה.**
- אם לא מתקמפל — מוחקים את הקובץ, מקמפלים מחדש, ו-v1 ממשיך. ‏NinjaTrader
  שומר את ה-DLL האחרון שקומפל בהצלחה, אז קימפול שנכשל לא שובר את הרץ.
- ‏v1 מגובה: ‏commit `4c808f3` + `C:\LIOR_ML_archive\code_v1_working_20260616`.

## הפעלה (כשאתה Flat)
1. ‏NinjaScript Editor → New Indicator → הדבק את `TOAIExporterGauge.cs` → ‏F5.
2. **אם יש שגיאות קימפול** — שלח לי את הטקסט שלהן ואתקן; בינתיים מחק את
   הקובץ ו-F5 כדי לחזור.
3. בגרף: הסר `TOAIExporter`, הוסף `TOAIExporterGauge` (הוא יושב בפאנל
   התחתון — ה-gauge מצויר שם).
4. ב-BloodHound: שנה את ה-solver ל-`TOAIExporterGauge.MLPass`.
5. בדוק ב-Sim.

## לחזרה ל-v1
הסר את `TOAIExporterGauge`, החזר את `TOAIExporter`, והחזר את ה-solver
ל-`TOAIExporter.MLPass`. (אפשר להשאיר את כל המחלקות מקומפלות במקביל — רק
לא להריץ שתי גרסאות exporter יחד על אותו מכשיר.)

## מה ניתן לכוונן בהמשך
מיקום/גודל ה-HUD, צבעים, אורך המיני-היסטוריה (כרגע 32 ברים), משך ההבהוב
(כרגע 8 ברים), והאם להציג גם על פאנל המחיר (דורש מעבר ל-overlay).
