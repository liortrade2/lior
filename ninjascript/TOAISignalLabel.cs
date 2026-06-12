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
        // Per-instrument folder (C:\LIOR_ML\ES, ...), resolved at DataLoaded
        // from the chart's instrument — matches TOAIExporter's layout.
        // threshold.txt stays at the ROOT — one threshold for all charts.
        private const string RootDir = @"C:\LIOR_ML";
        private const string ThresholdFile = RootDir + @"\threshold.txt";
        private string scoreFile, barScoresFile;

        // Precomputed per-bar scores — labels work retroactively on
        // historical bars and in Playback, not only live.
        private System.Collections.Generic.Dictionary<DateTime, double> scoreMap;

        [NinjaScriptProperty]
        public double MinProbabilityThreshold { get; set; } = 55.0;

        // TradeOptima-style vertical band over the signal bar:
        // green = ML allows, red = ML skips.
        [NinjaScriptProperty]
        public bool ShowSignalBand { get; set; } = true;

        // The input plot value at which BloodHound considers the signal
        // fired. Match BloodHound's Long/Short Threshold (default 0.8 for
        // the Confidence plots; a pure 0/1 signal plot works with this too).
        [NinjaScriptProperty]
        public double SignalFireLevel { get; set; } = 0.8;

        private Brush passBand, skipBand;

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
            else if (State == State.Configure)
            {
                passBand = new SolidColorBrush(Color.FromArgb(45, 50, 205, 50));
                passBand.Freeze();
                skipBand = new SolidColorBrush(Color.FromArgb(45, 255, 60, 30));
                skipBand.Freeze();
            }
            else if (State == State.DataLoaded)
            {
                // Bars = the chart's bars, regardless of the signal-plot input.
                string dataDir = RootDir + @"\" +
                    TOAIExporter.SanitizeName(Bars.Instrument.MasterInstrument.Name);
                scoreFile = dataDir + @"\score.txt";
                barScoresFile = dataDir + @"\bar_scores.csv";
                string error = null;
                scoreMap = TOAIExporter.LoadScoreMap(barScoresFile, ref error);
                // threshold.txt (set once in the TOAI panel) overrides the property.
                MinProbabilityThreshold = TOAIExporter.ReadThreshold(ThresholdFile, MinProbabilityThreshold);
            }
        }

        protected override void OnBarUpdate()
        {
            // Input is the BloodHound plot (e.g. Long Confidence, 0..1).
            // Below the fire level = no signal on this bar.
            double signal = Input[0];
            if (double.IsNaN(signal) || Math.Abs(signal) < SignalFireLevel)
                return;

            // A signal plot is 1 / -1. Price is in the thousands — if we see
            // that, the Input series was left on price: warn instead of
            // spraying a label on every single bar.
            if (Math.Abs(signal) > 1.5)
            {
                Draw.TextFixed(this, "TOAIBadInput",
                    "TOAISignalLabel: set Input series to the BloodHound signal plot (not price)!",
                    TextPosition.BottomRight, Brushes.Yellow, new SimpleFont("Arial", 13) { Bold = true },
                    Brushes.Transparent, Brushes.Transparent, 0);
                return;
            }

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
                    if (System.IO.File.Exists(scoreFile))
                    {
                        double parsed;
                        if (double.TryParse(System.IO.File.ReadAllText(scoreFile).Trim(),
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

            // TradeOptima look: vertical band over the signal bar, and the
            // score as a badge INSIDE the candle (white text on green/red).
            // Bars.GetHigh/GetLow = the real prices of the chart bar
            // (Input[0] here is the signal value, so High[0] would be wrong).
            if (ShowSignalBand)
                Draw.RegionHighlightX(this, "TOAIBand" + CurrentBar, 0, 0,
                    passed ? passBand : skipBand);

            double mid = (Bars.GetHigh(CurrentBar) + Bars.GetLow(CurrentBar)) / 2;
            string text = string.Format("{0:F0}%", probOfTrue);
            Draw.Text(this, "TOAISig" + CurrentBar, false, text,
                0, mid, 0, Brushes.White,
                new SimpleFont("Arial", 12) { Bold = true },
                System.Windows.TextAlignment.Center,
                Brushes.Transparent,
                passed ? Brushes.Green : Brushes.Red, 85);
        }
    }
}
