# TOAI — Trade Optimizer AI (Claude Code Instructions)

## 🎯 מה הפרויקט הזה
מערכת Python מקומית שמחקה את TradeOptima.AI — מסנן עסקאות חכם ל-NinjaTrader/BlackBird
באמצעות Machine Learning (Gradient Boosting) שמחשב PMV Score (0-100) לכל עסקה.

## 🔧 התקנה ראשונה (הרץ רק פעם אחת)
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## ▶️ הפעלה
```bash
python main.py
```

## 📂 מבנה הפרויקט
```
main.py              ← נקודת כניסה — תפריט אינטראקטיבי
requirements.txt     ← תלויות Python
toai/
  config.py          ← נתיבים, רשימת features, threshold
  train.py           ← אימון המודל + חישוב PMV (AUC-ROC)
  score.py           ← scoring בזמן אמת (ProbOfTrue 0-100)
  simulate.py        ← יצירת נתוני דמה לבדיקת ה-pipeline
ninjascript/
  TOAIExporter.cs    ← skeleton ל-NinjaScript: ייצוא features + קריאת score
```

## 🔁 זרימת העבודה
1. NinjaScript Exporter כותב `training_data.csv` (כל trade + indicator values בכניסה)
2. `python main.py` → אופציה 2 → אימון Gradient Boosting → PMV score
3. PMV > 0.5 = המודל מוסיף ערך
4. אופציה 4 (Watch mode) → קורא `current_features.csv` → כותב `score.txt`
5. NinjaScript קורא את `score.txt` → ProbOfTrue ≥ threshold → מאשר עסקה

## 📁 נתיבי נתונים
- **Windows (מכונת המסחר):** `C:\LIOR_ML\` (ברירת מחדל)
- **אחר / פיתוח:** `./data/` בתיקיית הפרויקט
- ניתן לעקוף עם משתנה סביבה `TOAI_DATA_DIR`

## 🧪 בדיקה מהירה (בלי NinjaTrader)
```bash
python main.py
# אופציה 1 → יוצר 500 עסקאות דמה
# אופציה 2 → מאמן ומציג PMV
# אופציה 3 → scoring לבר האחרון
```

## ⚠️ כללים
- Threshold התחלתי: 55 (ראה `toai/config.py`)
- Retraining: אחת לחודש או אחרי 50 עסקאות חדשות
- ML נכנס לשימוש אמיתי רק אחרי 200+ עסקאות אמיתיות ב-CSV
- אסור לקמט (commit) נתוני מסחר או קבצי model — הם ב-.gitignore
