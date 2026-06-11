// TOAIExporter — NinjaScript indicator skeleton for the TOAI ML bridge.
//
// Per bar close it appends the feature row to C:\LIOR_ML\current_features.csv
// and reads C:\LIOR_ML\score.txt (written by the Python watch mode) to decide
// whether the ML filter allows the next signal.
//
// Display: the live ProbOfTrue score (0-100) is plotted in the indicator
// panel with the threshold line, plus an ALLOW/SKIP label on the chart.
//
// Import into NinjaTrader 8: New > NinjaScript Editor > Indicators, paste, compile.
// Column order MUST match toai/config.py FEATURES.

#region Using declarations
using System;
using System.Windows.Media;
using NinjaTrader.Cbi;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Chart;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.DrawingTools;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Indicators
{
    public class TOAIExporter : Indicator
    {
        private const string DataDir = @"C:\LIOR_ML";
        private const string FeaturesFile = DataDir + @"\current_features.csv";
        private const string BarDataFile = DataDir + @"\bar_data.csv";
        private const string ScoreFile = DataDir + @"\score.txt";
        private const string Header =
            "ATR20,EMA9,EMA20,EMA50,RSI14,ADX14,Distance_SwingHigh,Distance_SwingLow,Volume_Ratio,BBand_Width,ZScore";

        [NinjaScriptProperty]
        public double MinProbabilityThreshold { get; set; } = 55.0;

        // When true, every bar (including the full chart history) is appended
        // to bar_data.csv with its DateTime — the raw material that gets
        // joined with the Strategy Analyzer trades export to build the real
        // training_data.csv (python main.py -> merge option).
        [NinjaScriptProperty]
        public bool ExportBarData { get; set; } = true;

        public bool MlFilterPassed { get; private set; }

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "TOAIExporter";
                Calculate = Calculate.OnBarClose;
                IsOverlay = false;                      // own panel below the chart

                AddPlot(new Stroke(Brushes.DodgerBlue, 2), PlotStyle.Line, "ProbOfTrue");
                AddPlot(new Stroke(Brushes.LimeGreen, 3), PlotStyle.Square, "MLPass");
                AddLine(Brushes.OrangeRed, 55, "Threshold");
            }
            else if (State == State.Configure)
            {
                Lines[0].Value = MinProbabilityThreshold;
            }
            else if (State == State.DataLoaded)
            {
                System.IO.Directory.CreateDirectory(DataDir);
                if (ExportBarData && !System.IO.File.Exists(BarDataFile))
                    System.IO.File.WriteAllText(BarDataFile, "DateTime," + Header + Environment.NewLine);
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

            // Historical export: one row per bar, used to build the real
            // training file from a Strategy Analyzer backtest.
            if (ExportBarData)
                System.IO.File.AppendAllText(BarDataFile,
                    Time[0].ToString("yyyy-MM-dd HH:mm:ss") + "," + line + Environment.NewLine);

            // Real-time bridge: only meaningful when Python watch mode is running.
            System.IO.File.WriteAllText(FeaturesFile, Header + Environment.NewLine + line + Environment.NewLine);

            // Read back the score written by: python main.py -> option 4 (watch mode)
            MlFilterPassed = false;
            double probOfTrue = double.NaN;
            if (System.IO.File.Exists(ScoreFile))
            {
                double parsed;
                if (double.TryParse(ScoreFile.Length > 0 ? System.IO.File.ReadAllText(ScoreFile).Trim() : "",
                        System.Globalization.NumberStyles.Float,
                        System.Globalization.CultureInfo.InvariantCulture, out parsed))
                {
                    probOfTrue = parsed;
                    MlFilterPassed = probOfTrue >= MinProbabilityThreshold;
                }
            }

            // MLPass plot: 1 = score passed the threshold, 0 = blocked.
            // BloodHound reads this plot as a solver and ANDs it with the
            // entry signal, so blocked signals never reach BlackBird.
            Values[1][0] = MlFilterPassed ? 1 : 0;

            // Live display: plot in the panel + ALLOW/SKIP banner on the chart.
            if (!double.IsNaN(probOfTrue))
            {
                Values[0][0] = probOfTrue;

                string verdict = MlFilterPassed ? "TRADE ALLOWED" : "TRADE SKIPPED";
                Brush color = MlFilterPassed ? Brushes.LimeGreen : Brushes.OrangeRed;
                Draw.TextFixed(this, "TOAIScore",
                    string.Format("Probability of Win: {0:F0}%  |  {1}  (min {2})",
                        probOfTrue, verdict, MinProbabilityThreshold),
                    TextPosition.TopRight, color, new SimpleFont("Arial", 16) { Bold = true },
                    Brushes.Transparent, Brushes.Transparent, 0);
            }
            else
            {
                Draw.TextFixed(this, "TOAIScore",
                    "TOAI: no score.txt — run: python main.py -> option 4 (watch mode)",
                    TextPosition.TopRight, Brushes.Gray, new SimpleFont("Arial", 12),
                    Brushes.Transparent, Brushes.Transparent, 0);
            }
        }
    }
}
