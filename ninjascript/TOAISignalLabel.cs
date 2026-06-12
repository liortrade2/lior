// TOAISignalLabel — draws the ML score label ONLY on bars where the
// BloodHound entry signal fired (the green stripe), instead of on every bar.
//
// Works on historical bars and in Playback too: per-bar scores are read
// from C:\LIOR_ML\bar_scores.csv (written by Python: main.py -> option 7,
// or automatically when training / starting the watch). Live bars not yet
// in that file fall back to score.txt.
//
// Setup on the chart:
//   1. Add this indicator to the PRICE panel.
//   2. In its properties, set "Input series" to the BloodHound signal plot
//      (e.g. BloodHound Ultimate -> Entry Signal US). That plot is 0 when
//      there is no signal and non-zero (1 / -1) on a signal bar.
//   3. Leave TOAIExporter on the chart as usual — it keeps exporting the
//      features and the MLPass gate; this indicator only handles the label.
//
// Because the Input is the signal plot (not price), all price/feature math
// stays in TOAIExporter. Here we only read score.txt and use Bars.GetHigh()
// for the label position (Bars always refers to the underlying chart bars,
// regardless of the input series).
//
// Import into NinjaTrader 8: New > NinjaScript Editor > Indicators, paste, compile.

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
    public class TOAISignalLabel : Indicator
    {
        private const string ScoreFile = @"C:\LIOR_ML\score.txt";
        private const string BarScoresFile = @"C:\LIOR_ML\bar_scores.csv";
        private const string ThresholdFile = @"C:\LIOR_ML\threshold.txt";

        // Precomputed per-bar scores — labels work retroactively on
        // historical bars and in Playback, not only live.
        private System.Collections.Generic.Dictionary<DateTime, double> scoreMap;

        [NinjaScriptProperty]
        public double MinProbabilityThreshold { get; set; } = 55.0;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "TOAISignalLabel";
                Calculate = Calculate.OnBarClose;
                IsOverlay = true;               // draw on the price panel
                DrawOnPricePanel = true;
                DisplayInDataBox = false;
                PaintPriceMarkers = false;
            }
            else if (State == State.DataLoaded)
            {
                string error = null;
                scoreMap = TOAIExporter.LoadScoreMap(BarScoresFile, ref error);
                // threshold.txt (set once in the TOAI panel) overrides the property.
                MinProbabilityThreshold = TOAIExporter.ReadThreshold(ThresholdFile, MinProbabilityThreshold);
            }
        }

        protected override void OnBarUpdate()
        {
            // Input is the BloodHound signal plot: 0 = no signal on this bar.
            if (double.IsNaN(Input[0]) || Math.Abs(Input[0]) < 0.5)
                return;

            // Precomputed score first (history + Playback); for a true live
            // bar that is not in bar_scores.csv yet, fall back to score.txt.
            double probOfTrue = double.NaN;
            double mapped;
            if (scoreMap != null && scoreMap.TryGetValue(Time[0], out mapped))
            {
                probOfTrue = mapped;
            }
            else if (State != State.Historical)
            {
                try
                {
                    if (System.IO.File.Exists(ScoreFile))
                    {
                        double parsed;
                        if (double.TryParse(System.IO.File.ReadAllText(ScoreFile).Trim(),
                                System.Globalization.NumberStyles.Float,
                                System.Globalization.CultureInfo.InvariantCulture, out parsed))
                            probOfTrue = parsed;
                    }
                }
                catch { }
            }

            if (double.IsNaN(probOfTrue))
                return;

            if (State != State.Historical)
                MinProbabilityThreshold = TOAIExporter.ReadThreshold(ThresholdFile, MinProbabilityThreshold);
            bool passed = probOfTrue >= MinProbabilityThreshold;
            string text = passed
                ? string.Format("{0:F0}%", probOfTrue)
                : string.Format("SKIP {0:F0}%", probOfTrue);
            Brush color = passed ? Brushes.LimeGreen : Brushes.OrangeRed;

            // Bars.GetHigh = the real price high of the chart bar (Input[0]
            // here is the signal value, so High[0] would be wrong).
            double y = Bars.GetHigh(CurrentBar) + 4 * TickSize;
            Draw.Text(this, "TOAISig" + CurrentBar, text, 0, y, color);
        }
    }
}
