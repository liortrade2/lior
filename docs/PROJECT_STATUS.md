# TOAI — Project Status & Handoff

> **קרא אותי ראשון בכל chat חדש.** עדכון אחרון: **2026-06-22** (ריבוי חשבונות + Bulenox evaluation tracker).
> כתוב כ-handoff מלא — הצ'אט הקודם הגיע לגבול אורך.

---

## 🆕 סשן 2026-06-22 (חלק ב') — ריבוי חשבונות + מעקב Prop-Evaluation

**הכל נדחף** ל-`claude/magical-dirac-1yd0d4` (HEAD ≈ `129f3e5`). שונו `toai/dashboard.py`
ו-`ninjascript_v4_gauge_tick/TOAIExecutionLogger.cs`. אומת לאורך הדרך עם בדיקות `_eval_html`/
`load_realized` ישירות (⚠️ **לא** עם AppTest מלא — כי `watch_toggle` ברירת מחדל ON ו-Home מפעיל
watch אמיתי; ריצה תתנגש ב-watch של המשתמש. השתמש בקריאות-פונקציה ישירות או compile-check).

### ריבוי חשבונות (גישת הפרו — DB אחד + שדה Account, לא תיקיות)
- **AddOn** כותב **פר-חשבון**: `<inst>/executions_<account>.csv` + `_<date>.csv` (שם מנוקה,
  `!`→`_`), וגם `<DataRoot>/accounts.txt` עם כל חשבונות הנינגה (מדלג Playback). ה-watch כבר
  עושה glob על `executions_*.csv`.
- **`load_realized`** מאחד את **כל** ארכיוני ה-`executions_*.csv` + הקובץ הנוכחי (dedup) — כך
  שכל ההיסטוריה נשמרת (executions.csv נדרס כל סשן). מסנן לפי `f_account`.
- **בורר חשבון** בראש הדף (גלוי תמיד), **שני dropdowns**: scope (📊 All / ▸ All Evaluation /
  Funded / Demo / 👤 Single account…) + dropdown שני לחשבון הספציפי. סיווג ב-`account_types.json`
  (ברירת מחדל לפי שם: Sim/Demo→Demo, אחרת Evaluation), נערך ב-Filters & goals → "Account types".

### פאנל Evaluation (Bulenox 25K — `_eval_html` + חישוב ב-Home)
מחליף את ה-Monthly goal. **בר טווח אחד:** Trailing DD שמאל · 0 מרכז · Profit target ימין, מילוי
ירוק/אדום מהמרכז לנטו, וסמן floor כהה. מתחת: Net/buffer/Balance/floor + התראת MAE.
**מדויק ל-Bulenox** (אומת מהלינק): trailing **real-time כולל unrealized** → peak לפי **MFE($)**;
**floor נעול ב-balance ההתחלתי** (`floor_net = min(peak_net − md, 0)`); **MAE** = הקרבה הכי גדולה
ל-floor תוך-עסקה ("⚠ touched floor"). ⚠️ MFE/MAE ב-executions הם **ב-$** (לא points). הגדרות:
`f_account_size/f_profit_target/f_max_dd` (25000/1500/1500) ב-Filters & goals. בסיס closed-trade;
trailing טהור עם נעילה-ב-start (אין נעילה-ב-breakeven נוספת).

### עוד ב-Home
- **watch toggle ברירת מחדל ON** + auto-start פעם אחת (guard `_watch_autostarted`).
- **auto-refresh כל 4ש'** כשה-watch ON (`@st.fragment(run_every=4)` → `st.rerun`).

### גיבוי / פורמט (המשתמש מתכנן פורמט)
- `TOAI_Backup_ToD.bat` — robocopy של `C:\LIOR_ML` + `C:\lior` ל-`D:\TOAI_Backup_<date>`.
- `C:\LIOR_ML\RESTORE_README.md` — מדריך שחזור מלא (בתוך הגיבוי).

### פתוח לצ'אט הבא
- **קבוצה עם כמה חשבונות** → ה-eval מאחד P&L (לא נכון ל-trailing על כמה חשבונות נפרדים); מדויק
  לחשבון בודד. שווה: eval פר-חשבון בתוך קבוצה, או להסתיר eval בקבוצות.
- **journal.csv עדיין בלי עמודת Account** → ML edge לא מסונן פר-חשבון (הלוח-שנה/eval כן, דרך
  executions). אם רוצים ML-edge-per-account — להוסיף Account ל-`_LEDGER_COLS`.
- כרטיס ML edge מציג מספר גם כש-selectivity=0% (`allow.n==0`) → כדאי "—".

---

## 🆕 סשן 2026-06-21/22 — ליטוש Home + כפתור app-mode בשולחן העבודה

**הכל נדחף** ל-`claude/magical-dirac-1yd0d4` (HEAD = `33ddd61`). שונו רק `toai/dashboard.py`
ו-`TOAI_Analytics_App.bat` (חדש). אומת לאורך הדרך עם `AppTest.from_file('toai/dashboard.py')`.

### מה נעשה — Home (toai/dashboard.py)
- **פריסה:** לוח-שנה ברוחב מלא בראש, ואז שורה תחתונה: משמאל **‹ June ›** nav + פקד **watch**;
  מימין בלוק היעד (Monthly goal / Month total). למטה: כרטיסי KPI (גובה 120px, שווי-גובה) ופאנל Evaluation.
- **לוח-שנה:** תאים אחידים `grid-auto-rows:84px` + `grid-template-rows:auto` (כותרת Mon..Sun נשארת נמוכה,
  התאים צמודים אליה). תאי-מסחר לחיצים → `?day=YYYY-MM-DD` פותח journal-יום (`_day_detail`).
- **פקד watch:** `st.toggle` (key=`watch_toggle`, default OFF) עם שורת-סטטוס `🟢/⚪`. מפעיל/עוצר את
  אותו subprocess כמו טאב Control (`from toai.score import watch`). **ברירת מחדל OFF — לא מפעיל לבד.**
- **ניווט חודשים:** חצים קטנים `on_click=_shift_month` (key `cal_prev`/`cal_next`) על `ss["f_calmonth"]`.
- **מיקום מדויק (pixel-tuned, שביר):** הבלוק השמאלי ממוקם ע"י עמודת-ריווח `st.columns([0.66, 3.4, 5])`,
  בלוק היעד ע"י `.cal-goal-below { margin-left:-120px }` + `.cal-goal { width:600px }`, והזזות-עדינות
  ב-`position:relative; top` על `.cal-monthlbl`/החצים/`.watch-status`/`.st-key-watch_toggle`.
  ⚠️ **המספרים האלה כוילו ידנית מול חלון 1071×589** — אם משנים גודל חלון או padding, צריך לכייל מחדש
  (יש שיטת "גריד-כיול" שאפשר להחזיר זמנית: `.stApp::before` עם repeating-linear-gradient כל 10/100px).

### כפתור הדסקטופ (`TOAI_Analytics_App.bat` + קיצור "TOAI Analytics" בשולחן העבודה)
- פותח את הדשבורד כ**חלון אפליקציה נקי** (Chrome/Edge `--app`, גודל 1071×589, פרופיל ייעודי
  `--user-data-dir`, `--disable-extensions` כדי שלא יופיעו תוספים כמו AdBlock360).
- השרת רץ ב**חלון ממוזער**; **סגירת חלון האפליקציה סוגרת את השרת** (`start /wait` על Chrome ואז
  `taskkill /f /t` על ה-PID שמאזין על 8765). הקיצור עצמו מקומי (לא ב-git).

### פתוח / לצ'אט הבא
- כרטיס **ML edge** עדיין מציג מספר גם כש-selectivity=0% (`allow.n==0`) → כדאי "—".
- נרות אמיתיים ב-Trade explorer ממתינים ל-recompile של `TOAIExporterGaugeTick` (OHLC).
- המיקומים ב-Home נעולים לחלון 1071×589 — אם רוצים responsive/גודל אחר, צריך לעבור מ-pixel-tuning
  ל-flex/grid יחסי.

---

## 🆕 סשן 2026-06-20 — נבנה דאשבורד אנליטיקה מקומי (📈 TOAI_Analytics)

**הכל נדחף** ל-`claude/magical-dirac-1yd0d4` (HEAD = `f84cf16`, 31 קומיטים בסשן).

### מה נבנה
**`toai/dashboard.py`** — דאשבורד **Streamlit** מקומי, **ML-aware**, "TradesViz/Edgewonk אצלנו".
קורא את אותם קבצים (`executions.csv`/`journal.csv`/`bar_data.csv`) — שום דבר לא יוצא מהמכונה.
מופעל ע"י **`TOAI_Analytics.bat`** או כפתור **📈 Analytics** ב-Control Panel (פורט קבוע **8765**).
דורש `pip install -r requirements.txt` (נוספו `streamlit`, `plotly`, `anthropic`).

**הטאבים (ניווט אנכי שמאלי, מצב-אפליקציה/PWA):**
- **🏠 Home** — מבט-אחד בסגנון Edgewonk (תֵמה בהירה): לוח-שנה-רווח HTML (אריחי-יום ירוק/אדום + עמודת Total),
  פאנל **Evaluation**, ושורת **KPI** (Net P&L sparkline · Win-rate gauge · Avg/trade split-bar · PF · **ML edge/trade**).
- **⚙️ Control** — מחליף את ה-Tkinter Control Panel: סטטוס-חי (score/gate/health, auto-refresh 2ש'), סף,
  בחירת/הפעלת/portfolio/מחיקת וריאנט, Train export, Backup, Clear-cache, Start/End-day, **Start/Stop watch** (subprocess).
- **🎯 ML edge** (תוחלת לפי דלי + ALLOW מול all) · **🔬 Breakdowns** · **📅 Calendar** · **🥅 Goals** ·
  **🧪 Simulator** (what-if stop/target לפי MAE/MFE) · **🕯 Trade explorer** (נרות/HA/Renko + replay) ·
  **🤖 AI Coach** (Claude `claude-opus-4-8`, off-path: debrief יומי/ביקורת-עסקה/צ'אט — דורש `ANTHROPIC_API_KEY`).

### דברים שכדאי לדעת לצ'אט הבא
- **אומת ב-Streamlit AppTest** (`from streamlit.testing.v1 import AppTest`) — דרך מצוינת לבדוק את הדאשבורד
  ללא דפדפן (תופס exceptions בכל הטאבים). הרץ עם `TOAI_DATA_DIR='C:\LIOR_ML'`.
- **פילטרים בתחתית הדף** — הערכים נקראים מ-`st.session_state` למעלה (keys: `f_inst/f_source/f_thr/f_unit/f_gday/...`),
  הוידג'טים מרונדרים בתחתית. ניווט = `st.radio(key="toainav")` + `if/elif view==…` (לא `st.tabs`).
- **CSS** — מוזרק כ-`THEME_CSS` (תמה בהירה, Manrope) + תבנית-Plotly אחת. הניווט-האנכי וה-full-bleed של
  שורת-ה-KPI (`.st-key-kpiwrap`/`.st-key-botbar`, `100vw`) מסתמכים על מבנה-DOM של Streamlit — שביר, לכוונן בזהירות.
- **OHLC נוסף ל-`TOAIExporterGaugeTick`** (לנרות) — צריך קימפול מחדש; עד אז גרף-העסקה נופל לקו EMA20.
- **Edgewonk** — תוקן (NinjaTrader importer, תאריכים אמיתיים) אבל **ליאור החליט שלא צריך** (יש דאשבורד). הכפתור הוסר מה-UI.

---

## 🆕 סשן 2026-06-20 (המשך) — עיצוב-מחדש של Home בסגנון Edgewonk

**הכל נדחף** ל-`claude/magical-dirac-1yd0d4` (HEAD = `3a99dd1`). שונה **רק `toai/dashboard.py`**.
השוואה ויזואלית מול Edgewonk (`edgewonk.app/home`) — Lior רצה שה-Home ייראה ויחשב כמוהו.

### מבנה Home החדש (מלמעלה למטה)
1. **לוח-השנה ברוחב מלא בראש הדף** — בכוונה, כדי שכשמצמצמים את החלון יישאר רק היומן.
   כותרת = ניווט `‹ June 2026 ›` בלבד (חיצים שמזיזים חודש חופשי דרך `ss["f_calmonth"]` כ-`pd.Period`).
   תאי-יום: תג-מספר עגול (`.cal-daynum`), רקע תכלת, **today** במסגרת שחורה (`pd.Timestamp.today()`),
   ימי חודש-סמוך מקווקווים (`.cal-cell.out`), עמודת **Total** שבועית בגוון.
   **ימי-מסחר הם לינקים** `?day=YYYY-MM-DD` → `_day_detail()` פותח journal-יום (סיכום + טבלת עסקאות),
   נקרא דרך `st.query_params["day"]`; "Back" מנקה אותו.
2. **בלוק יעד חודשי** מתחת ליומן (צמוד ימין, `.cal-goal-below`) — `_month_goal_html()`: יעד שהוגדר → סכום
   נוכחי → **כמה נשאר** + פס; "🎉 Goal reached" כשעוברים. גם **פס יעד יומי** בכל תא ו**שבועי** בעמודת Total
   (`_goalbar`, tooltips). היעדים מהשדות `f_gday/f_gweek/f_gmonth` (ב-$).
3. **כרטיסי KPI** (`.st-key-kpiwrap`) — בנראות Edgewonk: spark עם מילוי, מד win ירוק/אדום + גלולות W·BE·L,
   יחס payoff, סקאלת PF, טבעת ל-ML edge (selectivity).
4. **פאנל Evaluation** (`.evpanel.wide`) — פרוס ל-2 עמודות ברוחב מלא.

### דברים חשובים לצ'אט הבא
- **הנתונים שלנו נכונים** — תאמו 1:1 ל-`executions.csv` הגולמי (5 עסקאות, Net +3.90$). Edgewonk הראה
  רק 2 עסקאות כי יובא לשם ייצוא ישן/חלקי — **אל ת"תקן" את החישוב שלנו כדי להתאים ל-Edgewonk**.
- **עיגול בלוח** (`_cal_fmt`): $ ללא עשרוני, נקודות/טיקים ב-2 ספרות (אחרת `+0.78 pts` הוצג כ-`+1`).
- **באג ידוע (לא תוקן):** כרטיס ML edge מראה `+38.09$` גם כש-selectivity=0% (0 מ-4 מאושרות) — מספר מנוון על
  fills ממומשים. שווה להחזיר "—" כש-`allow.n==0`.
- בדיקה: `AppTest.from_file('toai/dashboard.py').run()` עם `TOAI_DATA_DIR='C:\LIOR_ML'` — לא מדמה קליקים על
  HTML, אז בדוק לינקים/`?day=` בשני חצאים (שהלינק נפלט + שה-param מרנדר את הפאנל).

---

## 1. מה המערכת עושה (עובד ✅)

פילטר עסקאות ML ל-NinjaTrader. ‏BloodHound מייצר סיגנלים, ‏TOAI מחשב
Probability-of-Win לכל בר, ‏BloodHound בודק את ה-plot **MLPass** (0/1) כ-solver
וחוסם סיגנלים מתחת לסף, ‏BlackBird מנהל את העסקה (כולל בלמים: kill-switch,
תקרת-הפסד) + XABCD News Pro לחדשות. מסחר ב-**Sim101**.
‏**הצינור אגנוסטי לאסטרטגיה ול-TF** (רב-TF, ראה §3).

**מצב אסטרטגיות MES — RESET נקי (2026-06-19):** ליאור **מחק את כל נתוני/וריאנטי
האסטרטגיות** ועושה ריצת-export חדשה. **כל המסקנות הקודמות לכל אסטרטגיה (מי "עם edge",
מי "חלש", מספרי AUC/WF) — מבוטלות, לא לצטט אותן.** הן נמדדו על נתונים שכבר נמחקו.
אחרי הריצה החדשה: לנקד כל אסטרטגיה מאפס עם `python -m toai.edge_scan` (ראה §הצעד הבא).
‏BBTMP הישן הוצא משימוש.

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

## 3. מודל נוכחי — MES עובר ל-**15-דקות** (2026-06-17)

‏**BBTMP (1-דקה) נמחק** לבקשת ליאור — וריאנטים 1-/2-/expectancy, ה-model.pkl, training_data,
bar_scores כולם נמחקו. ה-`MES` עכשיו **לוח נקי** (variants.json ריק), עם `bar_data.csv` של **15-דקות**
(‏`bar_data_tf.txt=Minute-15`). ארכיוני ה-1-דקה נשמרו כגיבוי. (ה-BBTMP היה: 1- WF 0.654 / 2- WF 0.666 —
אם רוצים להחזיר, יש ארכיוני bar_data_Minute-1 + ה-export "1-".)

**הצעד הבא (חוסם):** הגרף 15-דקות טען רק ~6 ימים (11-17/6); 5 ה-exports (`1A-15min…`, כולם MES SEP26,
‏72-519 עסקאות) הם מ-**2025-01 עד 2026-01**. **צריך לטעון היסטוריית 15-דקות מלאה (חזרה ל-2025-01)**
על הגרף, ואז ה-watch יאמן את 5 האסטרטגיות אוטומטית → 5 וריאנטים → להשוות ב-⚖ ולבחור.
**הגנה חדשה**: merge כבר לא דורס training_data לריק כש-0 התאמות (תיקון שורש הקריסה), ו-build_and_train
מזהה+מדפיס את ה-TF. כלל: רק גרף MES אחד (15-דקות) רץ — לא במקביל ל-1-דקה (ping-pong).
מכשירים אחרים (MNQ/M2K/MYM/MCL/MGC/MBT): תיקיות קיימות, **לא אומנו**.

**רב-TF (2026-06-17)**: MES תומך עכשיו בכמה timeframes יחד (1/3/5/15). המערכת **מזהה לבד** את ה-TF
של הגרף (`bar_data_tf.txt`) ומתאימה את המודל. כל וריאנט מתויג ב-TF שלו (מחולץ משם ה-export "…15min…",
או ה-TF החי). היסטוריית-אימון נפרדת לכל TF (`bar_data_train_<tf>min.csv`). ה-watch מסנכרן את `model.pkl`
לווריאנט הפעיל **של ה-TF החי** בכל tick — משנים TF בגרף / בוחרים אסטרטגיה בפאנל → הניקוד החי עוקב, בלי restart.
בפאנל: וריאנטים מקובצים לפי TF, ה-TF החי מסומן ● live, active נבחר נפרד לכל TF.
**זרימה**: עדכן TF בגרף → טען היסטוריה (פעם אחת ל-TF) → אמן את ה-export של אותו TF → בחר בפאנל.

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
    של תוחלת לפי דלי (ירוק/אדום מקו-אפס, פס ALLOW מודגש), **עקומת הון** (ALLOW מול 'לסחור הכול'),
    **סליידר-סף אינטראקטיבי** (גורר → ALLOW/SKIP/edge/גרפים מתעדכנים מיידית בזכות ה-caching) עם המלצות
    **סף אופטימלי** (max $/עסקה ו-max total $) וכפתור "Apply to live", טבלת ALLOW/SKIP (PF), וכותרת edge.
    כל כרטיס-כלי מציג שורת **"filter edge"** חיה (ברקע) — רואים אם הפילטר עושה כסף בלי לפתוח כלום.
  - **CLI**: `main.py` אופציה 9 (טקסט).
- **השוואת וריאנטים** (✅ roadmap #4) — כפתור "⚖ Compare variants" בכרטיס (כש-2+ וריאנטים): טבלה זו-לצד-זו
  של PMV, WF (ממוצע + גרף-עמודות לכל fold), win@סף, ו-**$ edge out-of-sample** (★ על הטוב ביותר) + כפתור
  Activate. ‏$ edge דורש snapshot של training_data לכל וריאנט — `variants.save_variant` שומר אותו מעכשיו
  (וריאנט בלי snapshot מציג "—" עד אימון מחדש; הפעיל משתמש ב-training_data.csv הנוכחי).
- **סף אופטימלי** (✅ roadmap #3, כבסיס) — `scorecard.recommend_threshold()` + `threshold_sweep()` סורקים
  את כל הספים על ה-out-of-fold ובוחרים מקסימום-תוחלת / מקסימום-total. כרגע **מייעץ** (הסף החי גלובלי-משותף
  לכל הגרפים בארכיטקטורה הנוכחית). "Apply to live" כותב לסף הגלובלי.
- **יומן עסקאות TOAI-native** (`toai/journal.py`) — הצד ה**מומש** של הלולאה הסגורה. במקום יומן חיצוני
  (Edgewonk/TradeZella/TradesViz — כולם כלים אנושיים שדוחפים לענן, וסגירת-לולאה תלויה ב-API בתשלום),
  בנינו יומן משלנו: ה-watch קורא `<כלי>/executions.csv` (fills חיים) ורושם כל עסקה מול הציון שקיבלה
  → `<כלי>/journal.csv` (append-only, dedup, שורד אימונים). תצוגת ה-Scorecard ממוחזרת: כפתור **Show:
  Realized fills ↔ Walk-forward** בחלון ה-📊 מציג **חזוי (backtest) מול מומש (fills אמיתיים)** באותו גרף —
  המבחן האמיתי אם ה-edge מתממש בכסף. גם `main.py` אופציה 10. **חסר בצד ליאור**: מי כותב את `executions.csv`
  (ראה §6) — NinjaScript executions-logger או ייצוא Trade Performance ידני.
- **ניהול וריאנטים** (`toai/variants.py`, main.py אופציה 8) — כל אימון נשמר כווריאנט; החלפה בלי אימון מחדש.
- **אימון אוטומטי של כל ה-exports** — ה-watch סורק את כל הקבצים בשורש ומאמן כל חדש (לכל הכלים יחד).
- **📈 Analytics dashboard** (`toai/dashboard.py`, `TOAI_Analytics.bat`, כפתור 📈 בפאנל) — דאשבורד
  אנליטיקה **מקומי ו-ML-aware** (Streamlit+Plotly), "TradesViz אצלנו". קורא את אותם
  `executions.csv`/`journal.csv`/`bar_data.csv` — שום דבר לא יוצא מהמכונה. 3 טאבים: **ML edge**
  (תוחלת לפי דלי-ציון + עקומת ALLOW מול trade-everything, סף אינטראקטיבי, ל-Realized **או**
  Walk-forward), **Breakdowns** (P&L לפי שעה/variant, MAE מול P&L צבוע ב-ML score, R-multiple),
  **Trade explorer** (טבלה + עסקה-על-גרף נרות עם entry/exit/SL/TP/MAE/MFE וה-ML score).
  **Phase A (2026-06-20, מתוך roadmap "TradesViz אצלנו" A→B→C):** נוספו בורר-יחידות ($/points/ticks),
  טאב **📅 Calendar** (heatmap חודשי + seasonality יום-בשבוע/חודש), טאב **🥅 Goals** (יעד יומי/שבועי/חודשי),
  **exit efficiency** (% מה-MFE שנתפס, צבוע ML), ובורר **סוגי-גרף** (Candlestick/Heikin-Ashi/Renko/Line)
  + אינדיקטורים (EMA9/20/50) על גרף-העסקה.
  **Phase B (2026-06-20):** טאב **🧪 Simulator** — what-if stop/target על העסקאות האמיתיות
  לפי MAE/MFE שכבר נשמרים (בלי צורך ב-bar history): סליידרים לסטופ/טרגט, מי-קודם tie-break,
  והשוואת net/win/PF + עקומת-הון מול בפועל. ועוד **replay slider** בגרף-העסקה (חשיפת ברים בהדרגה).
  **Phase C (2026-06-20):** טאב **🤖 AI Coach** — Claude off-path (`claude-opus-4-8`, adaptive
  thinking) שקורא את ה-fills האמיתיים **יחד עם ה-ML score וה-verdict** (`toai/ai_coach.py`):
  **Daily debrief**, **Review a trade**, ו-**chat על היומן**. זה ה-off-path Claude שתכננו (לא ב-hot-path).
  **דורש `ANTHROPIC_API_KEY`** בסביבה (בלעדיו הטאב מציג הנחיה, לא קורס). אומת: ה-SDK בנה+שלח את הבקשה
  (נעצר ב-auth עם מפתח-דמה — צורת-הבקשה תקינה). שלוש הפאזות A→B→C **הושלמו**.
  אומת חי עם Streamlit AppTest (כל 7 הטאבים + 4 סוגי-הגרף + הסימולטור + 2 המקורות, אין exceptions). **דורש**: `pip install -r requirements.txt` (נוסף `anthropic`)
  (נוספו streamlit+plotly). **נרות אמיתיים דורשים OHLC** — נוסף ל-`TOAIExporterGaugeTick` (לקמפל);
  עד אז fallback לקו EMA20.

---

## 5. ⭐ ROADMAP מאושר (להמשך — לפי עדיפות)

ליאור **אישר את כל אלה**. בנה לפי הסדר:

### 🎯 הבא בתור (התחל כאן)
1. ✅ **Live Scorecard** — **בוצע** (`toai/scorecard.py` + כפתור בפאנל + main.py אופ' 9). ראה §4.
2. ✅ **Expectancy** — **בוצע** דרך ה-Scorecard (תוחלת $/עסקה + R:R לפי דלי, ו-ALLOW/SKIP).
   הערה: טבלת הספים ב-`train.py` (פלט אימון) עדיין win-rate בלבד — ה-Scorecard מחליף אותה
   לתצוגת-הכסף. אופציונלי בעתיד: לשתול עמודת תוחלת גם שם (דורש להעביר PnL ל-walk_forward).

### 🧠 מוח (Tier 1) — מודל-תוחלת ✅ הוכח ובנוי
- **`toai/expectancy.py`** — אימון על **כסף במקום win/loss**: `sample_weight ∝ |PnL|` (winsorize 97.5%).
  המודל לומד להתחמק מההפסדים הגדולים ולהעדיף את הרווחים השמנים, לא רק את התכופים.
  - **הוכחה (out-of-sample, אותן 4905 עסקאות MES, סף 70)**: win-rate model +4.25$/עסקה (edge +2.33) מול
    **expectancy model +6.19$/עסקה (edge +4.27, PF 2.89)**. מנצח בכל סף. יותר סלקטיבי (פחות עסקאות, איכותיות יותר).
  - **מופעל כווריאנט**: `train_expectancy()` שומר וריאנט **לא-פעיל** `<base> [expectancy]` (slug `..._EXP`) עם
    snapshot משלו — ה-model.pkl החי **לא נגעו בו**. משווים ב-**⚖ Compare** (כל וריאנט מנוקד עם/בלי משקלול
    לפי `weight_by_pnl` ב-registry), ומפעילים בלחיצה אם מנצח. גם `main.py` אופציה 11.
  - **הערה**: ה-AUC של מודל-התוחלת *נמוך* יותר (0.625 מול 0.654) — זה תקין: הוא מקריב דיוק-דירוג כדי לדייק
    בעסקאות הגדולות. **ה-$ edge הוא ההשוואה האמיתית**, לא ה-AUC.

### 🔧 מודל
3. ✅ **סף אופטימלי** — **בוצע כבסיס** (recommend_threshold + סליידר + Apply). מייעץ בלבד כי הסף גלובלי.
   ‏**להשלים בעתיד**: סף-לכל-כלי אמיתי דורש שינוי ב-NinjaScript (לקרוא threshold לכל instrument).
4. ✅ **השוואת וריאנטים** — **בוצע** (כפתור ⚖ Compare, טבלה זו-לצד-זו עם $ edge). ראה §4.
5. **מבנה 3-תת-הוראות (A/B/C)** — לבדוק אם אימון ברמת-סיגנל (במקום תת-הוראה) נקי יותר. ← **הבא בתור**
6. **News-aware** — XT News Pro על הגרף; feature "דקות מאירוע" או חסימה סביב חדשות גדולות.

### ⚙️ תשתית
7. גיבוי/שחזור מודלים+וריאנטים (אחרי אסון ה-bar_data — קריטי).
8. תזכורת אימון-מחדש (חודשי).
9. התראה: Watch מת / ציון חוצה סף / מודל מתיישן.

---

## 6. ⚠️ פעולות פתוחות בצד ליאור (מכונת המסחר)
1. **לקמפל מחדש את `TOAIExporterGaugeTick`** — (א) תיקון ה-ping-pong (custom-period לעולם לא writer);
   (ב) **חדש**: נוסף input `ScoreFileName` (ברירת-מחדל score.txt, תאימות-לאחור) לתיק פר-אסטרטגיה. בלי
   הקומפילציה ה-bar_data בסיכון וה-ScoreFileName לא קיים.
   ‏⚠️ **ה-ping-pong חזר ב-17/6** ומחק את training_data (שוחזר). **תיקוני-קוד הכניסו הגנה**: merge כבר
   לא דורס training_data לריק, ו-`bar_data_train_<tf>min.csv` שומר היסטוריה (ראה §7). אבל שורש ה-ping-pong
   הוא ה-exporter — לקמפל. **כלל**: רק גרף MES אחד רץ (15-דקות), עם היסטוריה מלאה (600 יום) ל-bar_data_train.
2. **לוודא שה-Control Panel רץ בזמן המסחר** — טוען את המודל הפעיל (Two EMA+PSAR 15-דקות) וקולט executions.
3. (BBTMP/וריאנט-1 הוצאו משימוש — לא רלוונטי יותר.)
4. ✅ **`TOAIExecutionLogger.cs` — אומת חי (2026-06-18).** עסקת-בדיקה ב-Sim101 (MES Long, +10.03$)
   כתבה `C:\LIOR_ML\MES\executions.csv`, וה-watch קלט אותה ל-`journal.csv` תוך 6ש' (Score 42.5 → SKIP,
   Variant=Two EMA+PSAR, Source=live). **הלולאה החיה סגורה מקצה-לקצה**: fill → executions.csv (AddOn) →
   journal.csv (watch, מנוקד מול ה-gate). התקנה **פעם אחת**: NinjaScript Editor → New → AddOn → F5; רץ
   ברקע ללא חלון. **חשוב**: ה-Control Panel חייב לרוץ בזמן המסחר כדי לקלוט executions.csv ל-journal.csv
   לפני שהסשן מתאפס (ה-watch קולט אוטומטית). הצעד הבא: לצבור עסקאות חיות → 📊 Scorecard במצב "Realized
   fills" יראה אם ה-edge מתממש בכסף.

## 7. 🔥 לקחים/מלכודות (אל תחזור עליהן!)
- **bar_data ping-pong**: עותק BloodHound רץ על period לא-סטנדרטי (12345) ו"מארכב"=מוחק
  את ה-bar_data של הגרף בכל טעינה. **תוקן**: custom-period לעולם לא writer + single-writer.
  אם ה-bar_data מצטמצם פתאום ל-כמה ימים — זה זה. הארכיונים ב-`MES/bar_data_*.csv`.
- **Timeframe חייב להתאים**: המודל אומן על 1-דקה → הגרף חייב 1-דקה. החלפת TF מארכבת bar_data.
- **הפרדת אימון/חי (תוקן 2026-06-17)**: `bar_data.csv` = חי-מתגלגל (טען 5 ימים ליום-יום).
  `bar_data_train.csv` = איחוד מוקפא של כל הברים שנראו (אותו TF, dedup, רק גדל). **האימון קורא מהמוקפא**,
  אז **F5 של 5 ימים כבר לא דורס את היסטוריית האימון**. ה-watch מגדיל את קובץ-האימון כשברים מגיעים;
  build_and_train מאחד גם מהארכיונים. החלפת TF מאפסת את קובץ-האימון ל-TF החדש.
- **Exports → שורש `C:\LIOR_ML` תמיד** (לא תיקיית הכלי). הניתוב לפי עמודת Instrument.
- **שם export = שם וריאנט** (קבוע: `1-`, `2-`…). אותו שם = עדכון; שם חדש = וריאנט חדש.
- **לאמן רק כשהגרף טען מספיק היסטוריה** (אחרת 0 התאמות — צריך כיסוי תקופת הבקטסט).
- **single-writer**: שני מופעי exporter (גרף + BloodHound) — רק אחד כותב.
- **gate lag ~2ש'** (OnEachTick) — לא 0; סיגנל בדיוק בסגירת בר נשען על הציון הקודם.
- **DST**: ה-timestamps של NinjaTrader הם ET נכון — **בלי שום המרה** (אומת על 2679 עסקאות).
- **features יחסיים בלבד** (toai/features.py) — לעולם לא רמות מחיר אבסולוטיות.
- **Edgewonk: לייבא דרך ה-importer של NinjaTrader, לא Generic** (אומת חי 2026-06-19).
  ל-Edgewonk יש 2 importers: ה-**Generic** (תבנית עם Custom Stats) **מרסק תאריכים ל-1899-12-31**
  (קורא תאריך כמספר; נכשל על טקסט וגם על תא-datetime אמיתי). ה-**NinjaTrader importer** קורא נכון
  ומצפה ל-19 עמודות = `EDGEWONK_COLUMNS`. הייצוא-החי (`edgewonk._nt_live_rows`) כותב בדיוק את
  הפריסה הזו עם תאי datetime אמיתיים; ML score/Verdict ב-`Entry name`, Variant ב-`Strategy`
  (אין Custom Stats בפריסה הזו). בצד ליאור: Settings→Import→NinjaTrader + NinjaTrader בשפה אנגלית.

## 8. נקודות שחזור
- ‏git: ענף `claude/magical-dirac-1yd0d4`. ‏HEAD נוכחי ≈ `de916ff` (נדחף).
- **נבנה 2026-06-19 (הכול נדחף):**
  - **ייצוא Edgewonk חי** — לא הבקטסט אלא ה-fills האמיתיים (`executions.csv`), קובץ-יום
    מתוארך (`<inst>_live_<תאריך>.xlsx`), אוטומטי דרך ה-watch + כפתור force, פורמט ילידי
    עם **Custom Stats** (ML score/Verdict/Variant/Threshold) + Setup. SL/TP/MAE/MFE/Commission
    מ-executions.csv (דורש קימפול AddOn).
  - **מצב PLAYBACK מבודד** — שורש `C:\LIOR_ML_PLAYBACK`, מתג `PlaybackMode` ב-3 האינדיקטורים,
    ניתוב חשבון Playback101 ב-AddOn, `TOAI_Playback.bat` + `toai/playback.py` (סנכרון מודלים, ממזג).
  - **בורר TF לאימון פר-מכשיר** (כרטיס: Auto/1/2/3/5/15) → `<inst>/train_tf.txt`.
  - **התקשחות (7 תיקונים, `d5ad63f`):** סף פר-מכשיר (`<inst>/threshold.txt`+fallback), גיבוי
    אוטומטי אחרי אימון (`toai/backup.py` → D:\TOAI_Backups), executions עמידות
    (`executions_<date>.csv`+catch-up), חלון-פאנל לפי זמן-בר ET, playback-sync ממזג, dedup
    עם ExitTime (scalping), בדיקת-שפיות SL/TP. **`TOAIExporterGaugeTick`+`TOAIExecutionLogger`
    שונו — לקמפל.**
  - **בריאות מודל (`de916ff`)** — `toai/health.py`: התראת מודל מתיישן (>30 ימים) + drift
    (edge חי מול בקטסט) בכרטיס הפאנל + main.py אופ' 14.
  - **#9 (אותו מכשיר רב-TF חי במקביל) — נדחה** ביוזמת ליאור. כשיידרש: גישה A (קבצי
    `bar_data_<tf>min.csv`/`score_<tf>min.txt` באותה תיקייה, מנצל וריאנטים מתויגי-TF).
- **תיקוני 2026-06-18 (נדחפו):** (א) וריאנט expectancy יורש את ה-TF של הבסיס —
- **תיקוני 2026-06-18 (נדחפו):** (א) וריאנט expectancy יורש את ה-TF של הבסיס —
  אחרת לא יכל לעלות לאוויר אחרי Activate (`66eb713`). (ב) `TOAI_Panel.bat` מפעיל
  עכשיו את ה-Control Panel החדש, לא את gui.py הישן (`28e1517`). (ג) **ה-Scorecard
  וה-edge footer מנקדים את הווריאנט הפעיל** (snapshot שלו) ולא את ה-export האחרון
  שאומן — היה מציג edge של אסטרטגיה לא-פעילה (MES החי: ‎+57.94$/PF4.01, לא ‎-13.54$)
  (`7b2c73a`). (ד) כפתורי "Jump to optimal" בחלון ה-Scorecard (`779e2b2`).
  אומת חי: BloodHound solver = MLPass≥1 לשני הכיוונים; AddOn ה-executions קומפל.
- ‏`4c808f3` = v1 יציב (לפני הגרפיקה). גיבוי פיזי: `C:\LIOR_ML_archive\code_v1_working_20260616`.
- כל מודל/וריאנט ב-`C:\LIOR_ML\<כלי>\models\` (לא ב-git).

## 9. עקרונות (לא לשבור)
- ולידציה: **walk-forward בלבד** (random-split מנופח).
- היסטוריה: ‏MLPass=1 תמיד (לא מוחקים סיגנלים); ‏gate אמיתי חי+Playback.
- אחרי שינוי ב-`ninjascript_v4_gauge_tick/`: להדביק ב-NinjaScript Editor + F5.
- עדכון קוד במכונת המסחר: ‏`TOAI_Update.bat` (git pull; העותק היחיד: C:\lior).
- אסור לקמט נתוני מסחר/model — ב-.gitignore.

---

## הצעד הראשון בצ'אט הבא (עדכון 2026-06-19 — RESET נקי)

### 🔄 מצב: ריצה חדשה מאפס
ליאור **מחק את כל נתוני/וריאנטי האסטרטגיות הקיימים** ועושה ריצת-export חדשה ונקייה.
**אין מסקנות-אסטרטגיה שמועברות הלאה** — כל המספרים והוורדיקטים הקודמים (איזו אסטרטגיה
"עם edge", איזו "חלשה", כל AUC/WF) נמדדו על נתונים שנמחקו ו**אסור לצטט אותם**. המסגרת
תקינה — רק הנתונים והמסקנות אופסו.

> ⏵ **הריצה הנוכחית של 1a/MES היא ב-PLAYBACK** (Market Replay, שורש `C:\LIOR_ML_PLAYBACK`) —
> כל המספרים שנראו (1a PMV 0.59 / WF 0.56, scorecard, "edge") הם **replay, לא כסף חי**. הפאנל
> וה-Scorecard מסמנים עכשיו PLAYBACK בראש החלון, ומילת ה-drift היא "replay edge" (לא "live").

### 🧪 המבחן ל-edge אמיתי (לא השתנה — 3 תנאים יחד):
‏WF-AUC **>0.55** + win% עולה מונוטונית עם הציון + עקומת ALLOW מעל "לסחור הכול".
כלי מוכן לכך: **`python -m toai.edge_scan '<glob ל-*_training.csv>'`** — בדיקה read-only
שמריצה את 3 התנאים על כל dataset ומדרגת אותם (פלט ASCII, לא נוגע ב-model.pkl/וריאנטים).

### הצעד הבא — אחרי שהריצה החדשה מסתיימת ("לעשות הכל"):
1. לטעון היסטוריה מלאה לכל אסטרטגיה/TF שרוצים לבדוק → לאמן (כפתור **⚙ Train export** או ה-watch).
2. להריץ **`toai.edge_scan`** על כל ה-`*_training.csv` החדשים → לראות מי עובר 3/3.
3. לכל אסטרטגיה שעוברת: לבדוק ב-📊 Scorecard את ה-$ edge out-of-sample, ולהפעיל וריאנט.
4. תיק חי: לבחור 2-3 אסטרטגיות מאומתות (3/3) בקורלציה נמוכה.

### החלטות פתוחות (תלויות-נתונים — ימתינו לריצה החדשה):
- **תיק חי** — צריך 2-3 אסטרטגיות מאומתות (WF>0.55 + 3/3) בקורלציה נמוכה. מספר ה-edges כרגע **לא ידוע** (לפני הריצה).
- **Tier-2 sizing** — `sizing` (main אופ' 12) על מודל גדול; לחווט רק אם net/DD עולה.

### ⚠️ צד ליאור — לקמפל מחדש NinjaScript (שינויי 2026-06-19/20):
`TOAIExporterGaugeTick` (סף פר-מכשיר + PlaybackMode, **+ 2026-06-20: OHLC ל-bar_data**
לנרות בדאשבורד — מארכב bar_data ישן אוטומטית כי הכותרת השתנתה) ו-`TOAIExecutionLogger`
(executions_<date>.csv עמידים + SL/TP/MAE/MFE/Commission + ניתוב Playback101). הדבק + F5.
וכל פעם להפעיל מחדש `TOAI_Control.bat` אחרי שינוי Python. **חדש**: להריץ
`pip install -r requirements.txt` (streamlit+plotly לדאשבורד 📈 Analytics).

זרימה: כל קוד ב-git, לקמט+לדחוף אחרי כל שינוי, לעדכן את הקובץ הזה בסוף.
