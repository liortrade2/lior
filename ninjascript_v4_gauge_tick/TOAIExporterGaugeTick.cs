// TOAIExporterGaugeTick — EXPERIMENTAL v4: the gauge HUD (v3) + the ~2-second
// tick refresh (v2) combined. This is the "final candidate" variant.
//
//   * Calculate.OnEachTick — features still exported once per CLOSED bar, but
//     score.txt / gate / banner refresh every tick, so within ~2s of a bar
//     close the gate and HUD catch up (vs a full ~1-bar lag at bar close).
//   * Gauge HUD via Draw.TextFixed at the price panel's top-left — score +
//     verdict, a 0-100 block bar with a threshold marker, and a sparkline of
//     recent scores. TextFixed (unlike OnRender) is not clipped to the
//     sub-panel, so it reliably shows on the price chart.
//   * Same per-instrument file bridge + MLPass plot for BloodHound.
//
// Throttling: threshold.txt and entry_window.txt are read once per bar (not
// per tick); score.txt is stat-checked each tick and only re-parsed when the
// watch actually rewrote it.
//
// SAFE A/B: separate class. TOAIExporter (v1) is untouched — if this fails to
// compile, delete the file and recompile (NinjaTrader keeps the last good
// DLL). Writes the SAME C:\LIOR_ML\<INSTR>\ files, so run ONLY ONE exporter
// per instrument. Gate with TOAIExporterGaugeTick.MLPass. TEST IN SIM FIRST.

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
    public class TOAIExporterGaugeTick : Indicator
    {
        private const string LiveRoot = @"C:\LIOR_ML";
        private const string PlaybackRoot = @"C:\LIOR_ML_PLAYBACK";
        // Resolved in DataLoaded from PlaybackMode so Playback never touches the
        // live data root. ThresholdFile follows the same root.
        private string RootDir = LiveRoot;
        private string ThresholdFile = LiveRoot + @"\threshold.txt";
        private string dataDir, featuresFile, barDataFile, scoreFile, barScoresFile,
            entryWindowFile;
        private const string Header =
            "ATR20,EMA9,EMA20,EMA50,RSI14,ADX14,Distance_SwingHigh,Distance_SwingLow,Volume_Ratio,BBand_Width,ZScore";

        [NinjaScriptProperty]
        public double MinProbabilityThreshold { get; set; } = 55.0;

        [NinjaScriptProperty]
        public bool ExportBarData { get; set; } = true;

        // Set false when using the graphical TOAIGaugeHUD overlay, so the
        // text banner and the graphical gauge don't both show.
        [NinjaScriptProperty]
        public bool ShowTextHud { get; set; } = true;

        // The score (gate) file this instance reads. Default "score.txt" = the
        // active model. For a live PORTFOLIO, add one TOAIExporter per strategy
        // and point each at its own file (see portfolio.txt), e.g.
        // "score_1A_15min_Two_EMA_and_Parabolic_SAR....txt" — then each
        // BloodHound strategy gates on TOAIExporter.MLPass of its own instance.
        [NinjaScriptProperty]
        public string ScoreFileName { get; set; } = "score.txt";

        // Route ALL files to C:\LIOR_ML_PLAYBACK instead of C:\LIOR_ML, so a
        // Market-Replay chart can be tested without polluting live data. Set
        // true on a dedicated Playback chart (or template).
        [NinjaScriptProperty]
        public bool PlaybackMode { get; set; } = false;

        public bool MlFilterPassed { get; private set; }

        private System.Text.StringBuilder histBuffer;
        private string ioError;
        private System.Collections.Generic.HashSet<DateTime> exportedStamps;
        private System.Collections.Generic.Dictionary<DateTime, double> scoreMap;

        private double hudScore = double.NaN;
        private bool hudPassed;
        private bool hudInWindow = true;
        private double hudWinLo = -1, hudWinHi = -1;
        private bool hudHasWindow;
        private bool prevPassed;
        private DateTime flashUntil = DateTime.MinValue;
        private DateTime lastScoreStamp = DateTime.MinValue;
        private double lastScore = double.NaN;
        private readonly System.Collections.Generic.List<double> hudHistory =
            new System.Collections.Generic.List<double>();

        // Single-writer guard. The chart instance AND BloodHound's internal
        // solver copy both run OnBarUpdate; without this each appends every
        // bar and bar_data.csv (and current_features.csv) gets written twice.
        // Only ONE instance per data folder writes; the others still read the
        // score and compute MLPass for their own gate/display.
        private static readonly object writerLock = new object();
        private static readonly System.Collections.Generic.Dictionary<string, TOAIExporterGaugeTick> writers
            = new System.Collections.Generic.Dictionary<string, TOAIExporterGaugeTick>();

        // Standard time/price bar types only. BloodHound's solver copy runs on
        // a custom bars period (its type prints as e.g. "12345", not "Minute"),
        // so this automatically rules it out as a writer — no manual
        // ExportBarData=false needed on it.
        private bool IsStandardPeriod()
        {
            switch (BarsPeriod.BarsPeriodType.ToString())
            {
                case "Minute": case "Second": case "Tick": case "Day":
                case "Week": case "Month": case "Year": case "Volume":
                case "Range": return true;
                default: return false;
            }
        }

        private bool IsWriter()
        {
            // Readers never write: a copy with ExportBarData off, or one on a
            // non-standard bars period (BloodHound's solver series), can never
            // become the writer — so it can't archive or overwrite bar_data.
            if (!ExportBarData) return false;
            if (!IsStandardPeriod()) return false;
            if (dataDir == null) return true;
            lock (writerLock)
            {
                TOAIExporterGaugeTick cur;
                if (!writers.TryGetValue(dataDir, out cur) || cur == null)
                {
                    writers[dataDir] = this;
                    return true;
                }
                return cur == this;
            }
        }

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "TOAIExporterGaugeTick";
                Calculate = Calculate.OnEachTick;
                // Sub-panel for the ProbOfTrue line. The gauge HUD is drawn
                // with Draw.TextFixed (block-character bar) at the price panel's
                // top-left — TextFixed is NOT clipped to the sub-panel (unlike
                // OnRender), so it reliably appears on the price chart while the
                // line stays here, separate.
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
                RootDir = PlaybackMode ? PlaybackRoot : LiveRoot;
                ThresholdFile = RootDir + @"\threshold.txt";
                dataDir = RootDir + @"\" + SanitizeName(Instrument.MasterInstrument.Name);
                featuresFile = dataDir + @"\current_features.csv";
                barDataFile = dataDir + @"\bar_data.csv";
                scoreFile = dataDir + @"\" +
                    (string.IsNullOrWhiteSpace(ScoreFileName) ? "score.txt" : ScoreFileName.Trim());
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
                hudHasWindow = TryReadWindow(entryWindowFile, out hudWinLo, out hudWinHi);
            }
            else if (State == State.Realtime || State == State.Terminated)
            {
                FlushHistoryBuffer();
                if (State == State.Terminated && dataDir != null)
                    lock (writerLock)
                    {
                        TOAIExporterGaugeTick cur;
                        if (writers.TryGetValue(dataDir, out cur) && cur == this)
                            writers[dataDir] = null;   // release so another instance can write
                    }
            }
        }

        private void ArchiveBarDataOnTimeframeChange()
        {
            // Only the single writer manages bar_data and its tf marker. This
            // stops a SECOND instance (BloodHound's solver copy, which may run
            // on a different/custom bars period) from "archiving" — i.e.
            // wiping — the chart's real bar_data on every reload (the ping-pong
            // that left only a few days of history).
            if (!IsWriter()) return;
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
            if (!IsWriter()) { histBuffer.Clear(); return; }   // only one instance writes
            if (TryAppendShared(barDataFile, histBuffer.ToString()))
                histBuffer.Clear();
            else
                ioError = "bar_data.csv busy — history flushes on next chart reload";
        }

        // --- Self-contained helpers (this bundle has NO dependency on the
        // v1 TOAIExporter class). Shared with TOAISignalLabelGaugeTick. ---

        internal static string SanitizeName(string name)
        {
            if (string.IsNullOrEmpty(name)) return "UNKNOWN";
            var sb = new System.Text.StringBuilder(name.Length);
            foreach (char c in name)
                sb.Append(char.IsLetterOrDigit(c) ? c : '_');
            return sb.ToString();
        }

        internal static double SessionMinutes(DateTime barTime)
        {
            return barTime.Hour * 60 + barTime.Minute;
        }

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

        private void PushHistory(double v)
        {
            hudHistory.Add(v);
            if (hudHistory.Count > 32) hudHistory.RemoveAt(0);
        }

        protected override void OnBarUpdate()
        {
            if (CurrentBar < 20) return;

            // Historical: one update per bar, [0] = closed bar.
            if (State == State.Historical)
            {
                string hline = BuildFeatureLine(0);
                string hstamped = Time[0].ToString("yyyy-MM-dd HH:mm:ss") + "," + hline + Environment.NewLine;
                if (ExportBarData && exportedStamps != null && exportedStamps.Add(Time[0]))
                    histBuffer.Append(hstamped);
                double histScore;
                if (scoreMap != null && scoreMap.TryGetValue(Time[0], out histScore))
                {
                    Values[0][0] = histScore;
                    PushHistory(histScore);
                }
                Values[1][0] = 1;
                return;
            }

            // --- Realtime, OnEachTick ---

            // Once per bar: re-read threshold + window, export the just-closed bar.
            if (IsFirstTickOfBar)
            {
                MinProbabilityThreshold = ReadThreshold(ThresholdFile, MinProbabilityThreshold);
                Lines[0].Value = MinProbabilityThreshold;
                hudHasWindow = TryReadWindow(entryWindowFile, out hudWinLo, out hudWinHi);

                // Only the single writer touches the files (chart copy vs
                // BloodHound's solver copy) — prevents duplicate bar_data rows.
                if (IsWriter())
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
            }

            // Every tick: entry-window gate (cached window), using current time.
            if (hudHasWindow)
            {
                double barMinute = SessionMinutes(Time[0]);
                if (barMinute < hudWinLo || barMinute > hudWinHi)
                {
                    MlFilterPassed = false;
                    Values[1][0] = 0;
                    hudScore = double.NaN;
                    hudInWindow = false;
                    hudPassed = false;
                    prevPassed = false;
                    if (ShowTextHud) DrawGaugeHud();
                    return;
                }
            }
            hudInWindow = true;

            // Score for the last CLOSED bar ([1]). Precomputed map first, else
            // score.txt re-parsed only when its timestamp changed (one new
            // value per bar -> one history point).
            double probOfTrue = double.NaN;
            double mapped;
            if (scoreMap != null && scoreMap.TryGetValue(Time[1], out mapped))
                probOfTrue = mapped;
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
                            if (!double.IsNaN(lastScore))
                            {
                                Values[0][0] = lastScore;
                                PushHistory(lastScore);
                            }
                        }
                        probOfTrue = lastScore;
                    }
                }
                catch (Exception ex) { ioError = ex.Message; }
            }

            MlFilterPassed = !double.IsNaN(probOfTrue) && probOfTrue >= MinProbabilityThreshold;
            Values[1][0] = MlFilterPassed ? 1 : 0;

            hudScore = probOfTrue;
            hudPassed = MlFilterPassed;
            if (MlFilterPassed && !prevPassed) flashUntil = DateTime.Now.AddSeconds(2);
            prevPassed = MlFilterPassed;

            if (ShowTextHud) DrawGaugeHud();
        }

        // The gauge HUD as a Draw.TextFixed block — appears at the price
        // panel's top-left (TextFixed isn't clipped to the sub-panel). Three
        // lines: headline, the 0-100 bar with a threshold marker, a sparkline
        // of recent scores. Monospace so the blocks align. One colour by state.
        private void DrawGaugeHud()
        {
            Brush textBrush = !hudInWindow ? Brushes.Silver
                : hudPassed ? Brushes.LimeGreen : Brushes.OrangeRed;

            string line1, line2, line3 = "";
            if (!hudInWindow)
            {
                line1 = string.Format("  GATE CLOSED   {0:00}:{1:00}-{2:00}:{3:00}",
                    (int)hudWinLo / 60, (int)hudWinLo % 60, (int)hudWinHi / 60, (int)hudWinHi % 60);
                line2 = "  outside trading window";
            }
            else if (double.IsNaN(hudScore))
            {
                line1 = "  WIN  --    waiting for score";
                line2 = "";
            }
            else
            {
                int diff = (int)Math.Round(hudScore - MinProbabilityThreshold);
                line1 = string.Format("  WIN {0,3:F0}%  {1} {2:+0;-0;0}      {3}",
                    hudScore, TrendArrow(), diff, hudPassed ? "ALLOWED" : "SKIPPED");
                line2 = "  " + BuildTextBar() + string.Format("  min {0:F0}", MinProbabilityThreshold);
                line3 = "  " + BuildSparkline();
            }
            if (DateTime.Now < flashUntil) line1 += "  *NEW*";

            string text = line1;
            if (line2.Length > 0) text += "\n" + line2;
            if (line3.Trim().Length > 0) text += "\n" + line3;

            Draw.TextFixed(this, "TOAIGaugeHud", text, TextPosition.TopLeft,
                textBrush, new SimpleFont("Consolas", 16) { Bold = true },
                Brushes.Black, textBrush, 75);
        }

        // ▲ rising / ▼ falling / ─ flat, from the last two scores.
        private string TrendArrow()
        {
            int n = hudHistory.Count;
            if (n < 2) return "─";
            double a = hudHistory[n - 1], b = hudHistory[n - 2];
            if (a > b + 1.0) return "▲";
            if (a < b - 1.0) return "▼";
            return "─";
        }

        // 0-100 bar in brackets: full blocks up to the score, light shade after,
        // a vertical marker at the threshold position.
        private string BuildTextBar()
        {
            if (double.IsNaN(hudScore)) return "";
            const int n = 20;
            int fill = (int)Math.Round(Math.Max(0.0, Math.Min(100.0, hudScore)) / 100.0 * n);
            int thr = (int)Math.Round(Math.Max(0.0, Math.Min(100.0, MinProbabilityThreshold)) / 100.0 * n);
            var sb = new System.Text.StringBuilder(n + 2);
            sb.Append('[');
            for (int i = 0; i < n; i++)
            {
                if (i == thr) sb.Append('│');        // threshold marker
                else if (i < fill) sb.Append('█');   // full block
                else sb.Append('░');                 // light shade
            }
            sb.Append(']');
            return sb.ToString();
        }

        // Sparkline of the last scores using 8 block heights.
        private string BuildSparkline()
        {
            if (hudHistory.Count < 2) return "";
            const string lv = "▁▂▃▄▅▆▇█";
            int start = Math.Max(0, hudHistory.Count - 24);
            var sb = new System.Text.StringBuilder();
            for (int i = start; i < hudHistory.Count; i++)
            {
                double v = Math.Max(0.0, Math.Min(100.0, hudHistory[i]));
                sb.Append(lv[(int)Math.Round(v / 100.0 * 7)]);
            }
            return sb.ToString();
        }
    }
}
