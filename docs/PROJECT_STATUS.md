# TOAI — Project Status (handoff לשיחה חדשה)

> עדכון אחרון: 2026-06-12. קרא את הקובץ הזה בתחילת כל session חדש.

## מה המערכת עושה (עובד ✅)

פילטר עסקאות ML ל-NinjaTrader: BloodHound מייצר סיגנלים (Double CCI Scalping),
TOAI מחשב Probability-of-Win לכל בר, BloodHound בודק את `TOAIExporter.MLPass`
(0/1) כ-solver וחוסם סיגנלים מתחת לסף. BlackBird מנהל את העסקה.

## ארכיטקטורה — קבצים ב-C:\LIOR_ML (הנתונים, לא ב-git)

| קובץ | מי כותב | מי קורא |
|---|---|---|
| bar_data.csv | TOAIExporter (כל בר + 11 features) | merge / score_history |
| bar_data_tf.txt | TOAIExporter | TOAIExporter (זיהוי החלפת TF → ארכוב אוטומטי) |
| `<שם כלשהו>.csv` | המשתמש (export מ-Strategy Analyzer) | ה-Watch מזהה חדש → **אימון אוטומטי** |
| training_data.csv | merge (trades + bars) | train |
| model.pkl | train (GB + GridSearch + walk-forward) | score / score_history |
| bar_scores.csv | score_history (ציון לכל בר היסטורי) | האינדיקטורים — היסטוריה + Playback |
| current_features.csv | TOAIExporter (בר חי) | Watch |
| score.txt | Watch (ציון חי 0-100) | TOAIExporter |
| **threshold.txt** | **הפאנל (Set Threshold) — המקור היחיד לסף!** | הכל: Watch, שני האינדיקטורים, העותק של BloodHound |

## מצב נוכחי — ניסוי 1-Minute (באמצע!)

- המשתמש עבר מ-15-min ל-**1-min** כדי לקצר זמני בדיקה (מודע שהאסטרטגיה מפסידה שם)
- bar_data.csv נבנה מחדש על 1-min (180,192 ברים נוסקרו), הסף = **70**
- המודל הטעון עדיין מאומן על 15-min (221 עסקאות, PMV 0.5982, WF 0.5396)
- **ממתין:** המשתמש יריץ בקטסט 1-min ב-Strategy Analyzer וישמור export
  ל-C:\LIOR_ML → ה-Watch יאמן אוטומטית ("New trades export detected")

## תקלות פתוחות / דברים לבדוק

1. **Input series של TOAISignalLabel התאפס למחיר** אחרי קימפול — צריך להגדיר
   שוב: Indicators → TOAISignalLabel → Input series → BloodHound Ultimate →
   Plot = Long Confidence (האזהרה הצהובה על הצ'ארט מזהה את זה)
2. אחרי האימון על 1-min: לבדוק PMV/walk-forward ולבחור סף מהטבלה ההגונה (WF)
3. shorts: אם האסטרטגיה סוחרת שורט — עותק שני של TOAISignalLabel עם
   Short Confidence
4. בדיקת קצה-לקצה ב-Playback (שם ה-gate באמת חוסם, בניגוד להיסטוריה שהיא
   pass-through)

## עקרונות שנקבעו (לא לשבור!)

- היסטוריה: MLPass=1 תמיד (לא מוחקים סיגנלים של BloodHound); התוויות מראות
  מה *היה* נחסם. ב-Playback וחי — ה-gate אמיתי
- ולידציה: walk-forward בלבד לבחירת סף (random-split מנופח, להתעלם)
- TOAISignalLabel דורש TOAIExporter מקומפל (פונקציות סטטיות משותפות)
- אחרי כל שינוי ב-ninjascript/: להדביק ב-NinjaScript Editor + F5 (ידני)
- עדכון קוד במכונת המסחר: TOAI_Update.bat (העותק היחיד: C:\lior)

## נקודת שחזור

commit `61ec668` = מערכת 15-min עובדת מלאה (ראה RESTORE_POINTS.md)
