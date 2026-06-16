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
        // Multi-chart layout: every instrument writes into its own folder
        // under the root (C:\LIOR_ML\ES, C:\LIOR_ML\NQ, ...) so several
        // charts run side by side without clobbering each other's files.
        // threshold.txt stays at the ROOT — one threshold for all charts.
        private const string RootDir = @"C:\LIOR_ML";
        private const string ThresholdFile = RootDir + @"\threshold.txt";
        private string dataDir, featuresFile, barDataFile, scoreFile, barScoresFile,
            entryWindowFile;
        private const string Header =
            "ATR20,EMA9,EMA20,EMA50,RSI14,ADX14,Distance_SwingHigh,Distance_SwingLow,Volume_Ratio,BBand_Width,ZScore";

        // Fallback only — when C:\LIOR_ML\threshold.txt exists (written by
        // the TOAI panel's "Set Threshold" button) it OVERRIDES this property
        // everywhere: on the chart AND inside BloodHound's copy of the
        // indicator. One file, one threshold.
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

        // Bars already present in bar_data.csv. Without this, every chart
        // reload re-appends the full history and the file grows with
        // duplicates (Python dedups on read, but the file balloons).
        private System.Collections.Generic.HashSet<DateTime> exportedStamps;

        // Precomputed per-bar scores (bar_scores.csv, written by Python's
        // score_history) — lets the chart show scores retroactively on
        // historical bars and during Playback / Market Replay.
        private System.Collections.Generic.Dictionary<DateTime, double> scoreMap;

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
                dataDir = RootDir + @"\" + SanitizeName(Instrument.MasterInstrument.Name);
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
                scoreMap = LoadScoreMap(barScoresFile, ref ioError);
                MinProbabilityThreshold = ReadThreshold(ThresholdFile, MinProbabilityThreshold);
                Lines[0].Value = MinProbabilityThreshold;
            }
            else if (State == State.Realtime || State == State.Terminated)
            {
                FlushHistoryBuffer();
            }
        }

        // Features depend on the bar size (ATR20 on 1-min bars != ATR20 on
        // 15-min bars), so bar data from different timeframes must never mix.
        // bar_data_tf.txt remembers which timeframe built the current
        // bar_data.csv; when the chart's timeframe differs, the old file is
        // archived (bar_data_<tf>_<stamp>.csv) and a fresh one starts. The
        // stale bar_scores.csv is removed — the watch regenerates it.
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

        // Minutes since midnight in the chart clock — NinjaTrader already
        // shows DST-aware US Eastern, so the raw bar time IS the session
        // time (verified on 2679 MES entries: RTH sits at 09:42-16:00 in
        // both winter and summer). No timezone conversion. Shared with
        // TOAISignalLabel.
        internal static double SessionMinutes(DateTime barTime)
        {
            return barTime.Hour * 60 + barTime.Minute;
        }

        // The strategy's entry window in chart-clock minutes ("570-960"),
        // written by Python at training time from the backtest's actual
        // entry times. Outside it the model has never seen a trade, so the
        // gate blocks live trades. Shared with TOAISignalLabel.
        internal static bool TryReadWindow(string path, out double lo, out double hi)
        {
            lo = hi = -1;
            try
            {
                if (!System.IO.File.Exists(path)) return false;
                string[] parts = System.IO.File.ReadAllText(path).Trim().Split('-');
                if (parts.Length != 2) return false;
                return double.TryParse(parts[0], System.Globalization.NumberStyles.Float,
                           System.Globalization.CultureInfo.InvariantCulture, out lo)
                    && double.TryParse(parts[1], System.Globalization.NumberStyles.Float,
                           System.Globalization.CultureInfo.InvariantCulture, out hi);
            }
            catch { lo = hi = -1; return false; }
        }

        // "ES JUN26" charts share the master name "ES"; anything that is
        // not a letter or digit becomes '_' so the name is always a valid
        // folder. Shared with TOAISignalLabel.
        internal static string SanitizeName(string name)
        {
            if (string.IsNullOrEmpty(name)) return "UNKNOWN";
            var sb = new System.Text.StringBuilder(name.Length);
            foreach (char c in name)
                sb.Append(char.IsLetterOrDigit(c) ? c : '_');
            return sb.ToString();
        }

        // Shared with TOAISignalLabel: the single-source-of-truth threshold.
        // Returns the fallback when the file is missing or unreadable.
        internal static double ReadThreshold(string path, double fallback)
        {
            try
            {
                if (System.IO.File.Exists(path))
                {
                    double t;
                    if (double.TryParse(System.IO.File.ReadAllText(path).Trim(),
                            System.Globalization.NumberStyles.Float,
                            System.Globalization.CultureInfo.InvariantCulture, out t)
                        && t >= 0 && t <= 100)
                        return t;
                }
            }
            catch { }
            return fallback;
        }

        // Shared with TOAISignalLabel: bar_scores.csv is "DateTime,Score"
        // rows ("yyyy-MM-dd HH:mm:ss", score 0-100), one per chart bar.
        internal static System.Collections.Generic.Dictionary<DateTime, double>
            LoadScoreMap(string path, ref string error)
        {
            var map = new System.Collections.Generic.Dictionary<DateTime, double>();
            try
            {
                if (!System.IO.File.Exists(path))
                    return map;
                foreach (string row in System.IO.File.ReadAllLines(path))
                {
                    string[] parts = row.Split(',');
                    if (parts.Length < 2) continue;
                    DateTime t;
                    double s;
                    if (DateTime.TryParseExact(parts[0], "yyyy-MM-dd HH:mm:ss",
                            System.Globalization.CultureInfo.InvariantCulture,
                            System.Globalization.DateTimeStyles.None, out t)
                        && double.TryParse(parts[1],
                            System.Globalization.NumberStyles.Float,
                            System.Globalization.CultureInfo.InvariantCulture, out s))
                        map[t] = s;
                }
            }
            catch (Exception ex) { error = ex.Message; }
            return map;
        }

        // Timestamps of bars already in bar_data.csv (first column of each
        // row) — used to skip re-exporting bars on chart reloads.
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

        // current_features.csv is rewritten every bar while the Python watch
        // may be reading it (and BloodHound runs a second copy of this
        // indicator that writes it too). A naive write throws "file in use"
        // on that race. Retry briefly with a shared handle so the collision
        // is invisible instead of flashing a (self-healing) error.
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

        private void FlushHistoryBuffer()
        {
            if (histBuffer == null || histBuffer.Length == 0) return;
            try
            {
                System.IO.File.AppendAllText(barDataFile, histBuffer.ToString());
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

            // Historical bars: the score comes from bar_scores.csv (written by
            // Python's score_history) so ProbOfTrue plots retroactively. The
            // gate stays pass-through (MLPass = 1) on history so BloodHound's
            // past signals are never erased — the labels (TOAISignalLabel)
            // show what WOULD have been skipped.
            if (State == State.Historical)
            {
                // HashSet.Add returns false when the bar is already in the
                // file — that's what keeps reloads from duplicating history.
                if (ExportBarData && exportedStamps != null && exportedStamps.Add(Time[0]))
                    histBuffer.Append(stamped);
                double histScore;
                if (scoreMap != null && scoreMap.TryGetValue(Time[0], out histScore))
                    Values[0][0] = histScore;
                Values[1][0] = 1;
                return;
            }

            // Live: re-read the shared threshold each bar so a change in the
            // TOAI panel applies without reloading the chart.
            MinProbabilityThreshold = ReadThreshold(ThresholdFile, MinProbabilityThreshold);
            Lines[0].Value = MinProbabilityThreshold;

            // Live bars are appended one by one (the buffer was already flushed).
            try
            {
                if (ExportBarData && (exportedStamps == null || exportedStamps.Add(Time[0])))
                    System.IO.File.AppendAllText(barDataFile, stamped);
            }
            catch (Exception ex) { ioError = ex.Message; }

            // Real-time bridge (only meaningful when the Python watch runs).
            // Shared+retry write so a watch read mid-write doesn't error out.
            if (!TryWriteShared(featuresFile, Header + Environment.NewLine + line + Environment.NewLine))
                ioError = "current_features.csv busy — retried, will refresh next bar";

            // Outside the strategy's entry window the model has never seen a
            // trade — the gate blocks (the strategy should not be entering
            // here anyway) and the banner says so. The window is in chart-
            // clock minutes (true Eastern), same clock as the bar time.
            // Re-read each bar so a retrain's new window applies live.
            double winLo, winHi;
            if (TryReadWindow(entryWindowFile, out winLo, out winHi))
            {
                double barMinute = SessionMinutes(Time[0]);
                if (barMinute < winLo || barMinute > winHi)
                {
                    MlFilterPassed = false;
                    Values[1][0] = 0;
                    int lo = (int)winLo, hi = (int)winHi;
                    Draw.TextFixed(this, "TOAIScore",
                        string.Format("TOAI: outside entry window ({0:00}:{1:00}-{2:00}:{3:00}) — no prediction, gate closed",
                            lo / 60, lo % 60, hi / 60, hi % 60),
                        TextPosition.TopLeft, Brushes.Gray, new SimpleFont("Arial", 14),
                        Brushes.Transparent, Brushes.Transparent, 0);
                    return;
                }
            }

            // Score resolution: precomputed bar_scores.csv first (covers
            // Playback / Market Replay, where the "live" bars are past bars
            // already scored by Python), then score.txt from the live watch.
            MlFilterPassed = false;
            double probOfTrue = double.NaN;
            string debugMsg = "";
            double mapped;
            if (scoreMap != null && scoreMap.TryGetValue(Time[0], out mapped))
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
                        string scoreContent = System.IO.File.ReadAllText(scoreFile).Trim();
                        double parsed;
                        if (double.TryParse(scoreContent,
                                System.Globalization.NumberStyles.Float,
                                System.Globalization.CultureInfo.InvariantCulture, out parsed))
                        {
                            probOfTrue = parsed;
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
            }
            if (!double.IsNaN(probOfTrue))
                MlFilterPassed = probOfTrue >= MinProbabilityThreshold;

            if (ioError != null)
            {
                Draw.TextFixed(this, "TOAIError", "TOAI file error: " + ioError,
                    TextPosition.BottomLeft, Brushes.Yellow, new SimpleFont("Arial", 12),
                    Brushes.Transparent, Brushes.Transparent, 0);
                ioError = null;
            }
            else
            {
                // Clear a stale error banner once the transient lock resolved.
                RemoveDrawObject("TOAIError");
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

                // Per-bar score tags are handled by TOAISignalLabel, which is
                // fed the BloodHound signal plot as its input — so the tag
                // appears only on bars where a signal actually fired.
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
