// TOAIExporterTick — EXPERIMENTAL variant of TOAIExporter (the ~2-second fix).
//
// Problem it addresses: TOAIExporter runs Calculate.OnBarClose, so it reads
// score.txt for the gate/banner at the instant a bar closes — but the Python
// watch needs ~1-2s after the close to score that bar. Result: the chart shows
// the PREVIOUS bar's score for the whole next bar (a ~1-bar / 2-min lag).
//
// This variant runs Calculate.OnEachTick:
//   * features are still exported ONCE per closed bar (on the first tick of the
//     next bar, reading the just-closed bar at index [1]);
//   * score.txt / gate / banner are refreshed on EVERY tick, so within ~2s of a
//     bar close the chart and MLPass catch up to the latest score.
// The score read is throttled by file timestamp, so it only re-parses when the
// watch actually rewrites score.txt (no per-tick disk thrash).
//
// SAFE A/B DESIGN:
//   * This is a SEPARATE class (TOAIExporterTick). The proven TOAIExporter is
//     NOT modified — if this file fails to compile, delete it and recompile and
//     TOAIExporter keeps working.
//   * It writes to the SAME C:\LIOR_ML\<INSTR>\ files as TOAIExporter, so run
//     ONLY ONE exporter per instrument at a time (don't put both on one chart).
//   * To gate with this version, point BloodHound's solver at
//     TOAIExporterTick.MLPass instead of TOAIExporter.MLPass.
//   * TEST IN SIM FIRST.
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
    public class TOAIExporterTick : Indicator
    {
        private const string RootDir = @"C:\LIOR_ML";
        private const string ThresholdFile = RootDir + @"\threshold.txt";
        private string dataDir, featuresFile, barDataFile, scoreFile, barScoresFile,
            entryWindowFile;
        private const string Header =
            "ATR20,EMA9,EMA20,EMA50,RSI14,ADX14,Distance_SwingHigh,Distance_SwingLow,Volume_Ratio,BBand_Width,ZScore";

        [NinjaScriptProperty]
        public double MinProbabilityThreshold { get; set; } = 55.0;

        [NinjaScriptProperty]
        public bool ExportBarData { get; set; } = true;

        public bool MlFilterPassed { get; private set; }

        private System.Text.StringBuilder histBuffer;
        private string ioError;
        private System.Collections.Generic.HashSet<DateTime> exportedStamps;
        private System.Collections.Generic.Dictionary<DateTime, double> scoreMap;

        // Throttle: only re-read score.txt when the watch actually rewrote it.
        private DateTime lastScoreStamp = DateTime.MinValue;
        private double lastScore = double.NaN;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "TOAIExporterTick";
                Calculate = Calculate.OnEachTick;       // <-- the difference from TOAIExporter
                IsOverlay = false;

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
                // Reuse TOAIExporter's proven helpers + the same per-instrument layout.
                dataDir = RootDir + @"\" + TOAIExporter.SanitizeName(Instrument.MasterInstrument.Name);
                featuresFile = dataDir + @"\current_features.csv";
                barDataFile = dataDir + @"\bar_data.csv";
                scoreFile = dataDir + @"\score.txt";
                barScoresFile = dataDir + @"\bar_scores.csv";
                entryWindowFile = dataDir + @"\entry_window.txt";
                try
                {
                    System.IO.Directory.CreateDirectory(dataDir);
                    if (ExportBarData)
                    {
                        ArchiveBarDataOnTimeframeChange();
                        if (!System.IO.File.Exists(barDataFile))
                            System.IO.File.WriteAllText(barDataFile, "DateTime," + Header + Environment.NewLine);
                        exportedStamps = LoadExportedStamps(barDataFile, ref ioError);
                    }
                }
                catch (Exception ex) { ioError = ex.Message; }
                scoreMap = TOAIExporter.LoadScoreMap(barScoresFile, ref ioError);
                MinProbabilityThreshold = TOAIExporter.ReadThreshold(ThresholdFile, MinProbabilityThreshold);
                Lines[0].Value = MinProbabilityThreshold;
            }
            else if (State == State.Realtime || State == State.Terminated)
            {
                FlushHistoryBuffer();
            }
        }

        private void ArchiveBarDataOnTimeframeChange()
        {
            string tf = BarsPeriod.BarsPeriodType + "-" + BarsPeriod.Value;
            string metaPath = dataDir + @"\bar_data_tf.txt";
            string prev = System.IO.File.Exists(metaPath)
                ? System.IO.File.ReadAllText(metaPath).Trim() : null;
            if (prev != null && prev != tf && System.IO.File.Exists(barDataFile))
            {
                string archive = dataDir + @"\bar_data_" + prev + "_" +
                    DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".csv";
                System.IO.File.Move(barDataFile, archive);
                if (System.IO.File.Exists(barScoresFile))
                    System.IO.File.Delete(barScoresFile);
            }
            if (prev != tf)
                System.IO.File.WriteAllText(metaPath, tf);
        }

        // Own copies so TOAIExporter stays 100% untouched (these are private there).
        private static bool TryWriteShared(string path, string content)
        {
            for (int attempt = 0; attempt < 6; attempt++)
            {
                try
                {
                    using (var fs = new System.IO.FileStream(path, System.IO.FileMode.Create,
                               System.IO.FileAccess.Write, System.IO.FileShare.ReadWrite))
                    using (var sw = new System.IO.StreamWriter(fs))
                        sw.Write(content);
                    return true;
                }
                catch (System.IO.IOException) { System.Threading.Thread.Sleep(20); }
                catch { return false; }
            }
            return false;
        }

        private static bool TryAppendShared(string path, string content)
        {
            for (int attempt = 0; attempt < 6; attempt++)
            {
                try
                {
                    using (var fs = new System.IO.FileStream(path, System.IO.FileMode.Append,
                               System.IO.FileAccess.Write, System.IO.FileShare.ReadWrite))
                    using (var sw = new System.IO.StreamWriter(fs))
                        sw.Write(content);
                    return true;
                }
                catch (System.IO.IOException) { System.Threading.Thread.Sleep(20); }
                catch { return false; }
            }
            return false;
        }

        private static System.Collections.Generic.HashSet<DateTime>
            LoadExportedStamps(string path, ref string error)
        {
            var set = new System.Collections.Generic.HashSet<DateTime>();
            try
            {
                if (!System.IO.File.Exists(path))
                    return set;
                foreach (string row in System.IO.File.ReadLines(path))
                {
                    int comma = row.IndexOf(',');
                    if (comma <= 0) continue;
                    DateTime t;
                    if (DateTime.TryParseExact(row.Substring(0, comma),
                            "yyyy-MM-dd HH:mm:ss",
                            System.Globalization.CultureInfo.InvariantCulture,
                            System.Globalization.DateTimeStyles.None, out t))
                        set.Add(t);
                }
            }
            catch (Exception ex) { error = ex.Message; }
            return set;
        }

        private void FlushHistoryBuffer()
        {
            if (histBuffer == null || histBuffer.Length == 0) return;
            if (TryAppendShared(barDataFile, histBuffer.ToString()))
                histBuffer.Clear();
            else
                ioError = "bar_data.csv busy — history flushes on next chart reload";
        }

        // Build the feature CSV line from the bar `ago` bars back ([0]=forming,
        // [1]=just closed). Mirrors TOAIExporter's feature math exactly.
        private string BuildFeatureLine(int ago)
        {
            double close = Close[ago];
            double swingHigh = Swing(5).SwingHigh[ago];
            double swingLow = Swing(5).SwingLow[ago];
            double volumeSma = SMA(Volume, 20)[ago];
            double bbWidth = Bollinger(2, 20).Upper[ago] - Bollinger(2, 20).Lower[ago];
            double sma20 = SMA(20)[ago];
            double stdDev20 = StdDev(20)[ago];
            double zScore = stdDev20 > 0 ? (close - sma20) / stdDev20 : 0;
            return string.Format(
                "{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10}",
                ATR(20)[ago],
                EMA(9)[ago], EMA(20)[ago], EMA(50)[ago],
                RSI(14, 3)[ago],
                ADX(14)[ago],
                swingHigh > 0 ? swingHigh - close : 0,
                swingLow > 0 ? close - swingLow : 0,
                volumeSma > 0 ? Volume[ago] / volumeSma : 1,
                bbWidth,
                zScore);
        }

        protected override void OnBarUpdate()
        {
            if (CurrentBar < 20) return;

            // Historical bars behave like TOAIExporter (one update per bar,
            // [0] = the closed bar): buffer features and plot the precomputed score.
            if (State == State.Historical)
            {
                string hline = BuildFeatureLine(0);
                string hstamped = Time[0].ToString("yyyy-MM-dd HH:mm:ss") + "," + hline + Environment.NewLine;
                if (ExportBarData && exportedStamps != null && exportedStamps.Add(Time[0]))
                    histBuffer.Append(hstamped);
                double histScore;
                if (scoreMap != null && scoreMap.TryGetValue(Time[0], out histScore))
                    Values[0][0] = histScore;
                Values[1][0] = 1;
                return;
            }

            // --- Realtime, OnEachTick ---

            // (a) Export the just-CLOSED bar ([1]) once, on its first new tick.
            if (IsFirstTickOfBar)
            {
                string line = BuildFeatureLine(1);
                string stamped = Time[1].ToString("yyyy-MM-dd HH:mm:ss") + "," + line + Environment.NewLine;
                if (ExportBarData && (exportedStamps == null || !exportedStamps.Contains(Time[1])))
                {
                    if (TryAppendShared(barDataFile, stamped))
                    {
                        if (exportedStamps != null) exportedStamps.Add(Time[1]);
                    }
                    else
                        ioError = "bar_data.csv busy — retried, will refresh next bar";
                }
                if (!TryWriteShared(featuresFile, Header + Environment.NewLine + line + Environment.NewLine))
                    ioError = "current_features.csv busy — retried, will refresh next bar";
            }

            // (b) Every tick: refresh threshold, entry-window gate, score, banner.
            MinProbabilityThreshold = TOAIExporter.ReadThreshold(ThresholdFile, MinProbabilityThreshold);
            Lines[0].Value = MinProbabilityThreshold;

            double winLo, winHi;
            if (TOAIExporter.TryReadWindow(entryWindowFile, out winLo, out winHi))
            {
                double barMinute = TOAIExporter.SessionMinutes(Time[0]);
                if (barMinute < winLo || barMinute > winHi)
                {
                    MlFilterPassed = false;
                    Values[1][0] = 0;
                    int wlo = (int)winLo, whi = (int)winHi;
                    Draw.TextFixed(this, "TOAIScore",
                        string.Format("TOAI(Tick): outside entry window ({0:00}:{1:00}-{2:00}:{3:00}) — gate closed",
                            wlo / 60, wlo % 60, whi / 60, whi % 60),
                        TextPosition.TopLeft, Brushes.Gray, new SimpleFont("Arial", 14),
                        Brushes.Transparent, Brushes.Transparent, 0);
                    return;
                }
            }

            // Freshest score for the last CLOSED bar ([1] in realtime). Precomputed
            // bar_scores.csv first (history/Playback), else score.txt — re-parsed
            // only when its file timestamp changed.
            double probOfTrue = double.NaN;
            string debugMsg = "";
            double mapped;
            if (scoreMap != null && scoreMap.TryGetValue(Time[1], out mapped))
            {
                probOfTrue = mapped;
                debugMsg = "SCORE_OK";
            }
            else
            {
                try
                {
                    if (System.IO.File.Exists(scoreFile))
                    {
                        DateTime st = System.IO.File.GetLastWriteTimeUtc(scoreFile);
                        if (st != lastScoreStamp)
                        {
                            lastScoreStamp = st;
                            string sc = System.IO.File.ReadAllText(scoreFile).Trim();
                            double parsed;
                            lastScore = double.TryParse(sc,
                                System.Globalization.NumberStyles.Float,
                                System.Globalization.CultureInfo.InvariantCulture, out parsed)
                                ? parsed : double.NaN;
                            if (double.IsNaN(lastScore)) debugMsg = "PARSE_FAIL:" + sc;
                        }
                        probOfTrue = lastScore;
                        if (!double.IsNaN(probOfTrue)) debugMsg = "SCORE_OK";
                    }
                    else debugMsg = "NO_FILE";
                }
                catch (Exception ex) { ioError = ex.Message; debugMsg = "EXCEPTION"; }
            }

            MlFilterPassed = !double.IsNaN(probOfTrue) && probOfTrue >= MinProbabilityThreshold;

            if (ioError != null)
            {
                Draw.TextFixed(this, "TOAIErrorTick", "TOAI(Tick) file error: " + ioError,
                    TextPosition.BottomLeft, Brushes.Yellow, new SimpleFont("Arial", 12),
                    Brushes.Transparent, Brushes.Transparent, 0);
                ioError = null;
            }
            else
            {
                RemoveDrawObject("TOAIErrorTick");
            }

            Values[1][0] = MlFilterPassed ? 1 : 0;

            if (!double.IsNaN(probOfTrue))
            {
                Values[0][0] = probOfTrue;
                string verdict = MlFilterPassed ? "TRADE ALLOWED" : "TRADE SKIPPED";
                Brush color = MlFilterPassed ? Brushes.LimeGreen : Brushes.OrangeRed;
                Draw.TextFixed(this, "TOAIScore",
                    string.Format("Probability of Win: {0:F0}%  |  {1}  (min {2})  [Tick]",
                        probOfTrue, verdict, MinProbabilityThreshold),
                    TextPosition.TopLeft, color, new SimpleFont("Arial", 16) { Bold = true },
                    Brushes.Transparent, Brushes.Transparent, 0);
            }
            else
            {
                string displayMsg = debugMsg == "NO_FILE" ? "no score.txt (Watch not running?)" :
                                   debugMsg.StartsWith("PARSE_FAIL") ? "parse error: " + debugMsg.Substring(11) :
                                   debugMsg == "EXCEPTION" ? "read exception" : "unknown";
                Draw.TextFixed(this, "TOAIScore",
                    "TOAI(Tick): " + displayMsg + " — python main.py option 4",
                    TextPosition.TopLeft, Brushes.Gray, new SimpleFont("Arial", 12),
                    Brushes.Transparent, Brushes.Transparent, 0);
            }
        }
    }
}
