# 🚦 התחל כאן — הנחיה לצ'אט Claude Code חדש (אחרי פורמט + Windows 11 נקי)

> **לקלוד של הצ'אט החדש: קרא את הקובץ הזה ראשון, במלואו, לפני כל פעולה.**

## מי אתה ומה המצב
אתה ממשיך פרויקט בשם **TOAI** — דשבורד מסחר מקומי ML-aware ל-NinjaTrader, עם מעקב
prop-evaluation (Bulenox), ריבוי חשבונות, ולולאה סגורה. המשתמש (ליאור) **פירמט את המחשב
והתקין Windows 11 נקי**. הקוד שוחזר ל-`C:\lior` (דרך `git clone`), והנתונים ב-`C:\LIOR_ML`
(שוחזרו מגיבוי ב-D, או עוד צריך לשחזר).

## שלב 1 — ללמוד (חובה, לפני שתעשה משהו)
קרא והפנם, לפי הסדר:
1. **`docs/PROJECT_STATUS.md`** — מצב הפרויקט המלא (קרא ראשון; יש בו סעיפי handoff מפורטים).
2. **`CLAUDE.md`** — הוראות הפרויקט.
3. **`C:\LIOR_ML\RESTORE_README.md`** — מדריך השחזור (אם קיים; גם בשורש הגיבוי ב-D).
4. **`git log --oneline -40`** — מה נעשה לאחרונה.
5. עיין ב-`toai/dashboard.py` (הדשבורד), `ninjascript_v4_gauge_tick/` (AddOn+אינדיקטורים),
   ו-`TOAI_Install.bat` / `TOAI_Install.ps1` (המתקין).

## שלב 2 — לאשר הבנה
סכם בקצרה למשתמש **בעברית** מה המערכת עושה ומה מתוכנן (כדי לוודא שאתה מסונכרן). אל תמשיך
עד שהמשתמש מאשר.

## שלב 3 — לחכות ⏸️
**אל תתחיל בהתקנה/שחזור עד שהמשתמש אומר לך במפורש להתחיל** ("תתחיל", "go", וכו').
המשתמש רוצה לתת לך הוראה ידנית. **חכה.**

## שלב 4 — כשהמשתמש נותן אישור: בצע את ההתקנה
המשתמש רוצה **שתעשה את ההתקנה בעצמך** (לא רק תסביר). אז:
1. הרץ / הדרך את **`C:\lior\TOAI_Install.bat`** (מתקין Python+תלויות, מפתח API אופציונלי,
   מעתיק AddOn+אינדיקטורים ל-NinjaTrader, יוצר קיצורים, משחזר `C:\LIOR_ML` מ-D).
   - ⚠️ אתה (Claude Code) עלול לרוץ ב-sandbox שחוסם כתיבה מחוץ ל-`C:\lior` — אם פקודה
     נכשלת על D:/Documents, השתמש ב-`dangerouslyDisableSandbox: true` או הדרך את המשתמש
     להריץ את ה-BAT בעצמו (זה מה שקרה בגיבוי — robocopy ל-D נחסם ב-sandbox).
2. ודא: Python מותקן, `pip install -r requirements.txt` עבר, הקבצים הועתקו ל-
   `Documents\NinjaTrader 8\bin\Custom\AddOns\` (TOAIExecutionLogger.cs) ו-`\Indicators\`
   (TOAIExporterGaugeTick / TOAIGaugeHUD / TOAISignalLabelGaugeTick).
3. ודא `C:\LIOR_ML` שוחזר (journal.csv, model.pkl, accounts.txt, account_types.json).
4. הזכר למשתמש את הצעדים הידניים שנשארו לו: **NinjaTrader → Compile (F5) → להוסיף את
   האינדיקטור TOAIExporterGaugeTick לגרף MES → דאבל-קליק על "TOAI Analytics" בשולחן העבודה.**

## עובדות מפתח (כדי לא "להמציא מחדש")
- **GitHub:** `https://github.com/liortrade2/lior` · ענף: `claude/magical-dirac-1yd0d4`.
- **נתונים:** `C:\LIOR_ML\` (פר-מכשיר: bar_data/model; פר-חשבון: `executions_<account>_*.csv`).
  מותר לעקוף עם `TOAI_DATA_DIR`. **אל תקמט נתונים** (LIOR_ML ב-.gitignore).
- **ריבוי חשבונות (גישת פרו):** DB אחד + עמודת Account. בורר שני-dropdowns (scope:
  All/Evaluation/Funded/Demo/Single + dropdown לחשבון). סיווג ב-`account_types.json`.
- **Eval (Bulenox 25K):** profit target $1,500 · trailing DD $1,500 · floor נעול ב-$25K ·
  real-time לפי MFE($) · התראת MAE. בר טווח (DD שמאל · 0 · target ימין).
- **watch:** ברירת מחדל ON, auto-start; **רק watcher אחד** (טוגל בדשבורד או TOAI_Control,
  לא שניהם). MFE/MAE ב-executions הם **ב-$**.
- **אזהרה:** **אל "תתקן" את החישובים שלנו כדי להתאים ל-Edgewonk/חיצוני** — המספרים שלנו
  canonical (תואמים ל-executions הגולמי).
- **בדיקות:** אל תריץ AppTest מלא של dashboard.py — `watch_toggle` ON מפעיל watch אמיתי.
  השתמש ב-`py_compile` או קריאות-פונקציה ישירות (`load_realized`/`_eval_html`).
- **כפתור desktop:** `TOAI_Analytics_App.bat` — Chrome `--app` 1071×589, watch אוטומטי,
  סגירת החלון עוצרת את השרת.

## פתוח / TODO לעתיד (לא דחוף)
- journal.csv בלי עמודת Account → ML edge לא מסונן פר-חשבון (calendar/eval כן).
- eval על קבוצת כמה חשבונות מאחד P&L (מדויק רק לחשבון בודד).
- כרטיס ML edge מציג מספר גם כש-selectivity=0% → כדאי "—".
- נרות אמיתיים ב-Trade explorer צריכים recompile של TOAIExporterGaugeTick (OHLC).

---
**זכור: שלב 1-2 (ללמוד+לאשר) → לחכות (שלב 3) → רק כשהמשתמש אומר, לבצע (שלב 4).**
