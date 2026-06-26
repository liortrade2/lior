// TOAISignalLabelGaugeTick — the per-bar score badge for the v4 bundle.
//
// Identical behaviour to TOAISignalLabel (draws the ML score ONLY on bars
// where the BloodHound entry signal fired; green = allowed, red = skipped,
// gray = outside the entry window; works on history + Playback via
// bar_scores.csv, falls back to score.txt live). The ONLY difference: it is
// self-contained inside this v4 folder — it reuses the helper methods on
// TOAIExporterGaugeTick (same folder), so the whole v4 version lives in ONE
// place with no dependency on the v1 TOAIExporter class.
//
// Setup on the chart:
//   1. Add to the PRICE panel.
//   2. Set "Input series" to the BloodHound signal plot (BloodHound Ultimate
//      -> Long Confidence). 0 = no signal, non-zero on a signal bar.
//   3. Keep TOAIExporterGaugeTick on the chart (it does the gate + gauge).
//
// Import into NinjaTrader 8: New > NinjaScript Editor > Indicators, paste, F5.

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
    public class TOAISignalLabelGaugeTick : Indicator
    {
        private const string LiveRoot = @"C:\LIOR_ML";
        private const string PlaybackRoot = @"C:\LIOR_ML_PLAYBACK";
        private string RootDir = LiveRoot;
        private string ThresholdFile = LiveRoot + @"\threshold.txt";
        private string scoreFile, barScoresFile, modeFile;
        private double windowLo = -1, windowHi = -1;
        private string mode = "";                       // "Mean Reversion" / "Standard"
        private DateTime lastModeStamp = DateTime.MinValue;

        private System.Collections.Generic.Dictionary<DateTime, double> scoreMap;

        [NinjaScriptProperty]
        public double MinProbabilityThreshold { get; set; } = 55.0;

        [NinjaScriptProperty]
        public bool ShowSignalBand { get; set; } = true;

        [NinjaScriptProperty]
        public double SignalFireLevel { get; set; } = 0.8;

        // Read scores from C:\LIOR_ML_PLAYBACK on a Market-Replay chart.
        [NinjaScriptProperty]
        public bool PlaybackMode { get; set; } = false;

        private Brush passBand, skipBand;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "TOAISignalLabelGaugeTick";
                Calculate = Calculate.OnBarClose;
                IsOverlay = true;
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
                RootDir = PlaybackMode ? PlaybackRoot : LiveRoot;
                ThresholdFile = RootDir + @"\threshold.txt";
                string dataDir = RootDir + @"\" +
                    TOAIExporterGaugeTick.SanitizeName(Bars.Instrument.MasterInstrument.Name);
                scoreFile = dataDir + @"\score.txt";
                barScoresFile = dataDir + @"\bar_scores.csv";
                modeFile = dataDir + @"\mode.txt";
                TOAIExporterGaugeTick.TryReadWindow(dataDir + @"\entry_window.txt",
                    out windowLo, out windowHi);
                string error = null;
                scoreMap = TOAIExporterGaugeTick.LoadScoreMap(barScoresFile, ref error);
                MinProbabilityThreshold = TOAIExporterGaugeTick.ReadThreshold(ThresholdFile, MinProbabilityThreshold);
            }
        }

        protected override void OnBarUpdate()
        {
            // Mode badge (fixed, top-right) — which model is gating the signal:
            // Mean Reversion (candle-shape features ON) vs Standard. Read from
            // <inst>\mode.txt (written by Python); drawn every bar, not just on
            // signal bars, so it's always visible. Top-RIGHT avoids the gauge HUD.
            try
            {
                if (System.IO.File.Exists(modeFile))
                {
                    DateTime mt = System.IO.File.GetLastWriteTimeUtc(modeFile);
                    if (mt != lastModeStamp)
                    {
                        lastModeStamp = mt;
                        mode = System.IO.File.ReadAllText(modeFile).Trim();
                    }
                }
            }
            catch { }
            if (!string.IsNullOrEmpty(mode))
            {
                bool mr = mode.IndexOf("rever", StringComparison.OrdinalIgnoreCase) >= 0;
                Draw.TextFixed(this, "TOAIMode",
                    "MODE: " + (mr ? "MEAN REVERSION" : "STANDARD"),
                    TextPosition.TopRight,
                    mr ? Brushes.DeepSkyBlue : Brushes.Gray,
                    new SimpleFont("Arial", 11) { Bold = true },
                    Brushes.Transparent, Brushes.Transparent, 0);
            }

            double signal = Input[0];
            if (double.IsNaN(signal) || Math.Abs(signal) < SignalFireLevel)
                return;

            if (Math.Abs(signal) > 1.5)
            {
                Draw.TextFixed(this, "TOAIBadInput",
                    "TOAISignalLabelGaugeTick: set Input series to the BloodHound signal plot (not price)!",
                    TextPosition.BottomRight, Brushes.Yellow, new SimpleFont("Arial", 13) { Bold = true },
                    Brushes.Transparent, Brushes.Transparent, 0);
                return;
            }

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
                MinProbabilityThreshold = TOAIExporterGaugeTick.ReadThreshold(ThresholdFile, MinProbabilityThreshold);
            bool passed = probOfTrue >= MinProbabilityThreshold;

            bool inWindow = windowLo < 0 ||
                (TOAIExporterGaugeTick.SessionMinutes(Time[0]) >= windowLo &&
                 TOAIExporterGaugeTick.SessionMinutes(Time[0]) <= windowHi);

            if (ShowSignalBand && inWindow)
                Draw.RegionHighlightX(this, "TOAIBand" + CurrentBar, 0, 0,
                    passed ? passBand : skipBand);

            // Clean number INSIDE the bar — just the number: no "%", no outline
            // frame, no background box.
            double mid = (Bars.GetHigh(CurrentBar) + Bars.GetLow(CurrentBar)) / 2;
            string text = string.Format("{0:F0}", probOfTrue);
            Draw.Text(this, "TOAISig" + CurrentBar, false, text,
                0, mid, 0, Brushes.White,
                new SimpleFont("Arial", 12) { Bold = true },
                System.Windows.TextAlignment.Center,
                Brushes.Transparent,      // no outline frame
                Brushes.Transparent, 0);  // no background box
        }
    }
}
