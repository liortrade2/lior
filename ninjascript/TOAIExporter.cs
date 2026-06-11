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

        // Historical rows are buffered and written once when the chart goes
        // realtime — one big write instead of thousands of appends, and no
        // file-lock collisions with Python reading bar_data.csv.
        private System.Text.StringBuilder histBuffer;
        private string ioError;

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
                histBuffer = new System.Text.StringBuilder();
            }
            else if (State == State.DataLoaded)
            {
                try
                {
                    System.IO.Directory.CreateDirectory(DataDir);
                    if (ExportBarData && !System.IO.File.Exists(BarDataFile))
                        System.IO.File.WriteAllText(BarDataFile, "DateTime," + Header + Environment.NewLine);
                }
                catch (Exception ex) { ioError = ex.Message; }
            }
            else if (State == State.Realtime || State == State.Terminated)
            {
                FlushHistoryBuffer();
            }
        }

        private void FlushHistoryBuffer()
        {
            if (histBuffer == null || histBuffer.Length == 0) return;
            try
            {
                System.IO.File.AppendAllText(BarDataFile, histBuffer.ToString());
                histBuffer.Clear();
            }
            catch (Exception ex) { ioError = ex.Message; }
        }

        protected override void OnBarUpdate()
        {
            if (CurrentBar < 20) return;

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

            string stamped = Time[0].ToString("yyyy-MM-dd HH:mm:ss") + "," + line + Environment.NewLine;

            // Historical bars have no live score — the Python watch loop only
            // runs in real time, so score.txt holds a single stale value that
            // would otherwise be applied to the whole history and erase every
            // past BloodHound signal. Pass-through (MLPass = 1) keeps the
            // historical signals intact; the ML gate only acts on live bars.
            if (State == State.Historical)
            {
                if (ExportBarData)
                    histBuffer.Append(stamped);
                Values[1][0] = 1;
                return;
            }

            // Live bars are appended one by one (the buffer was already flushed).
            try
            {
                if (ExportBarData)
                    System.IO.File.AppendAllText(BarDataFile, stamped);

                // Real-time bridge: only meaningful when Python watch mode is running.
                System.IO.File.WriteAllText(FeaturesFile, Header + Environment.NewLine + line + Environment.NewLine);
            }
            catch (Exception ex) { ioError = ex.Message; }

            // Read back the score written by: python main.py -> option 4 (watch mode)
            MlFilterPassed = false;
            double probOfTrue = double.NaN;
            string debugMsg = "";
            try
            {
                if (System.IO.File.Exists(ScoreFile))
                {
                    string scoreContent = System.IO.File.ReadAllText(ScoreFile).Trim();
                    double parsed;
                    if (double.TryParse(scoreContent,
                            System.Globalization.NumberStyles.Float,
                            System.Globalization.CultureInfo.InvariantCulture, out parsed))
                    {
                        probOfTrue = parsed;
                        MlFilterPassed = probOfTrue >= MinProbabilityThreshold;
                        debugMsg = "SCORE_OK";
                    }
                    else
                    {
                        debugMsg = "PARSE_FAIL:" + scoreContent;
                    }
                }
                else
                {
                    debugMsg = "NO_FILE";
                }
            }
            catch (Exception ex) { ioError = ex.Message; debugMsg = "EXCEPTION"; }

            if (ioError != null)
            {
                Draw.TextFixed(this, "TOAIError", "TOAI file error: " + ioError,
                    TextPosition.BottomLeft, Brushes.Yellow, new SimpleFont("Arial", 12),
                    Brushes.Transparent, Brushes.Transparent, 0);
                ioError = null;
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
                    TextPosition.TopLeft, color, new SimpleFont("Arial", 16) { Bold = true },
                    Brushes.Transparent, Brushes.Transparent, 0);

                // Per-bar marker on the price chart, like TradeOptima's
                // "LONG SKIPPED" tags: green score above the bar when the
                // gate is open, red "SKIP" when blocked. One tag per bar so
                // the history of decisions stays visible.
                string barText = MlFilterPassed
                    ? string.Format("{0:F0}%", probOfTrue)
                    : string.Format("SKIP {0:F0}%", probOfTrue);
                Draw.Text(this, "TOAIBar" + CurrentBar, barText,
                    0, High[0] + 4 * TickSize, color);
            }
            else
            {
                // Debug: show why no score
                string displayMsg = debugMsg == "NO_FILE" ? "no score.txt (Watch not running?)" :
                                   debugMsg.StartsWith("PARSE_FAIL") ? "parse error: " + debugMsg.Substring(11) :
                                   debugMsg == "EXCEPTION" ? "read exception" : "unknown";
                Draw.TextFixed(this, "TOAIScore",
                    "TOAI: " + displayMsg + " — python main.py option 4",
                    TextPosition.TopLeft, Brushes.Gray, new SimpleFont("Arial", 12),
                    Brushes.Transparent, Brushes.Transparent, 0);
            }
        }
    }
}
