// TOAIExporter — NinjaScript indicator skeleton for the TOAI ML bridge.
//
// Per bar close it appends the feature row to C:\LIOR_ML\current_features.csv
// and reads C:\LIOR_ML\score.txt (written by the Python watch mode) to decide
// whether the ML filter allows the next signal.
//
// Import into NinjaTrader 8: New > NinjaScript Editor > Indicators, paste, compile.
// Column order MUST match toai/config.py FEATURES.

#region Using declarations
using System;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Indicators
{
    public class TOAIExporter : Indicator
    {
        private const string DataDir = @"C:\LIOR_ML";
        private const string FeaturesFile = DataDir + @"\current_features.csv";
        private const string ScoreFile = DataDir + @"\score.txt";
        private const string Header =
            "ATR20,EMA9,EMA20,EMA50,RSI14,ADX14,Distance_SwingHigh,Distance_SwingLow,Volume_Ratio,BBand_Width,ZScore";

        [NinjaScriptProperty]
        public double MinProbabilityThreshold { get; set; } = 55.0;

        public bool MlFilterPassed { get; private set; }

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "TOAIExporter";
                Calculate = Calculate.OnBarClose;
                IsOverlay = false;
            }
            else if (State == State.DataLoaded)
            {
                System.IO.Directory.CreateDirectory(DataDir);
            }
        }

        protected override void OnBarUpdate()
        {
            if (CurrentBar < 50) return;

            double swingHigh = Swing(5).SwingHigh[0];
            double swingLow = Swing(5).SwingLow[0];
            double volumeSma = SMA(Volume, 20)[0];
            double bbWidth = Bollinger(2, 20).Upper[0] - Bollinger(2, 20).Lower[0];
            double sma20 = SMA(20)[0];
            double stdDev20 = StdDev(20)[0];
            double zScore = stdDev20 > 0 ? (Close[0] - sma20) / stdDev20 : 0;

            string line = string.Format(
                "{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10}",
                ATR(20)[0],
                EMA(9)[0], EMA(20)[0], EMA(50)[0],
                RSI(14, 3)[0],
                ADX(14)[0],
                swingHigh > 0 ? swingHigh - Close[0] : 0,
                swingLow > 0 ? Close[0] - swingLow : 0,
                volumeSma > 0 ? Volume[0] / volumeSma : 1,
                bbWidth,
                zScore);

            System.IO.File.WriteAllText(FeaturesFile, Header + Environment.NewLine + line + Environment.NewLine);

            // Read back the score written by: python main.py -> option 4 (watch mode)
            MlFilterPassed = false;
            if (System.IO.File.Exists(ScoreFile))
            {
                double probOfTrue;
                if (double.TryParse(System.IO.File.ReadAllText(ScoreFile).Trim(), out probOfTrue))
                    MlFilterPassed = probOfTrue >= MinProbabilityThreshold;
            }
        }
    }
}
