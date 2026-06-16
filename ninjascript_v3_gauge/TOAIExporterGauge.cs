// TOAIExporterGauge — EXPERIMENTAL visual variant of TOAIExporter.
//
// Same file bridge + gate as the stable TOAIExporter (Calculate.OnBarClose,
// writes current_features.csv, reads score.txt, sets the MLPass plot for
// BloodHound), but the plain "Probability of Win" text banner is replaced by
// a GAUGE HUD drawn with SharpDX in OnRender:
//   * big colored score + verdict (ALLOWED / SKIPPED / GATE CLOSED)
//   * a 0-100 gauge bar with the threshold marked, filled to the score
//   * a mini-history strip of the last scores (trend at a glance)
//   * a brief flash when the score crosses up through the threshold
//
// SAFE A/B: separate class (TOAIExporterGauge). The proven TOAIExporter is NOT
// modified — if this file fails to compile, delete it and recompile and v1
// keeps working. It writes the SAME C:\LIOR_ML\<INSTR>\ files, so run ONLY ONE
// exporter per instrument. To gate with it, point BloodHound's solver at
// TOAIExporterGauge.MLPass. TEST IN SIM FIRST.
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
    public class TOAIExporterGauge : Indicator
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

        // HUD state (set in OnBarUpdate, drawn in OnRender).
        private double hudScore = double.NaN;
        private bool hudPassed;
        private bool hudInWindow = true;
        private double hudWinLo = -1, hudWinHi = -1;
        private bool hudHasWindow;
        private bool prevPassed;
        private int flashCount;
        private readonly System.Collections.Generic.List<double> hudHistory =
            new System.Collections.Generic.List<double>();

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "TOAIExporterGauge";
                Calculate = Calculate.OnBarClose;
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

            if (State == State.Historical)
            {
                if (ExportBarData && exportedStamps != null && exportedStamps.Add(Time[0]))
                    histBuffer.Append(stamped);
                double histScore;
                if (scoreMap != null && scoreMap.TryGetValue(Time[0], out histScore))
                {
                    Values[0][0] = histScore;
                    PushHistory(histScore);
                }
                Values[1][0] = 1;
                return;
            }

            MinProbabilityThreshold = TOAIExporter.ReadThreshold(ThresholdFile, MinProbabilityThreshold);
            Lines[0].Value = MinProbabilityThreshold;

            if (ExportBarData && (exportedStamps == null || !exportedStamps.Contains(Time[0])))
            {
                if (TryAppendShared(barDataFile, stamped))
                {
                    if (exportedStamps != null) exportedStamps.Add(Time[0]);
                }
                else
                    ioError = "bar_data.csv busy — retried, will refresh next bar";
            }

            if (!TryWriteShared(featuresFile, Header + Environment.NewLine + line + Environment.NewLine))
                ioError = "current_features.csv busy — retried, will refresh next bar";

            // Entry window: gate closed outside it.
            double winLo, winHi;
            hudHasWindow = TOAIExporter.TryReadWindow(entryWindowFile, out winLo, out winHi);
            if (hudHasWindow)
            {
                hudWinLo = winLo; hudWinHi = winHi;
                double barMinute = TOAIExporter.SessionMinutes(Time[0]);
                if (barMinute < winLo || barMinute > winHi)
                {
                    MlFilterPassed = false;
                    Values[1][0] = 0;
                    hudScore = double.NaN;
                    hudInWindow = false;
                    hudPassed = false;
                    prevPassed = false;
                    return;
                }
            }
            hudInWindow = true;

            MlFilterPassed = false;
            double probOfTrue = double.NaN;
            double mapped;
            if (scoreMap != null && scoreMap.TryGetValue(Time[0], out mapped))
                probOfTrue = mapped;
            else
            {
                try
                {
                    if (System.IO.File.Exists(scoreFile))
                    {
                        string sc = System.IO.File.ReadAllText(scoreFile).Trim();
                        double parsed;
                        if (double.TryParse(sc, System.Globalization.NumberStyles.Float,
                                System.Globalization.CultureInfo.InvariantCulture, out parsed))
                            probOfTrue = parsed;
                    }
                }
                catch (Exception ex) { ioError = ex.Message; }
            }
            if (!double.IsNaN(probOfTrue))
                MlFilterPassed = probOfTrue >= MinProbabilityThreshold;

            Values[1][0] = MlFilterPassed ? 1 : 0;
            if (!double.IsNaN(probOfTrue))
            {
                Values[0][0] = probOfTrue;
                PushHistory(probOfTrue);
            }

            // HUD state + flash when the score crosses UP through the threshold.
            hudScore = probOfTrue;
            hudPassed = MlFilterPassed;
            if (MlFilterPassed && !prevPassed) flashCount = 8;
            prevPassed = MlFilterPassed;
            if (flashCount > 0) flashCount--;
        }

        private void PushHistory(double v)
        {
            hudHistory.Add(v);
            if (hudHistory.Count > 32) hudHistory.RemoveAt(0);
        }

        // ---- Gauge HUD (SharpDX) ----
        protected override void OnRender(NinjaTrader.Gui.Chart.ChartControl chartControl,
                                         NinjaTrader.Gui.Chart.ChartScale chartScale)
        {
            base.OnRender(chartControl, chartScale);
            if (RenderTarget == null || ChartPanel == null) return;

            float x = (float)ChartPanel.X + 10f;
            float y = (float)ChartPanel.Y + 8f;
            float w = 300f, h = 56f;

            SharpDX.Color accent =
                !hudInWindow ? new SharpDX.Color(120, 144, 156, 255) :
                hudPassed ? new SharpDX.Color(46, 200, 90, 255) :
                            new SharpDX.Color(255, 82, 54, 255);

            // Panel background.
            var bgBrush = new SharpDX.Direct2D1.SolidColorBrush(RenderTarget, new SharpDX.Color(11, 11, 13, 220));
            var panel = new SharpDX.Direct2D1.RoundedRectangle
            { Rect = new SharpDX.RectangleF(x, y, w, h), RadiusX = 6f, RadiusY = 6f };
            RenderTarget.FillRoundedRectangle(panel, bgBrush);
            bgBrush.Dispose();

            var accentBrush = new SharpDX.Direct2D1.SolidColorBrush(RenderTarget, accent);

            // Flash outline on threshold cross-up.
            if (flashCount > 0)
            {
                RenderTarget.DrawRoundedRectangle(panel, accentBrush, 2.5f);
            }

            // Big score (or em dash when no prediction).
            string bigText = double.IsNaN(hudScore) ? "—" : string.Format("{0:F0}%", hudScore);
            var tfBig = new SharpDX.DirectWrite.TextFormat(NinjaTrader.Core.Globals.DirectWriteFactory,
                "Arial", SharpDX.DirectWrite.FontWeight.Bold, SharpDX.DirectWrite.FontStyle.Normal, 26f);
            RenderTarget.DrawText(bigText, tfBig,
                new SharpDX.RectangleF(x + 12f, y + 8f, 110f, 34f), accentBrush);
            tfBig.Dispose();

            // Verdict + subtitle.
            string verdict = !hudInWindow ? "GATE CLOSED" : hudPassed ? "ALLOWED" : "SKIPPED";
            string subtitle = !hudInWindow
                ? string.Format("outside {0:00}:{1:00}-{2:00}:{3:00}",
                    (int)hudWinLo / 60, (int)hudWinLo % 60, (int)hudWinHi / 60, (int)hudWinHi % 60)
                : string.Format("min {0:F0}", MinProbabilityThreshold);

            var tfMid = new SharpDX.DirectWrite.TextFormat(NinjaTrader.Core.Globals.DirectWriteFactory,
                "Arial", SharpDX.DirectWrite.FontWeight.Bold, SharpDX.DirectWrite.FontStyle.Normal, 13f);
            RenderTarget.DrawText(verdict, tfMid,
                new SharpDX.RectangleF(x + 120f, y + 7f, 175f, 18f), accentBrush);
            tfMid.Dispose();

            var subBrush = new SharpDX.Direct2D1.SolidColorBrush(RenderTarget, new SharpDX.Color(160, 165, 170, 255));
            var tfSmall = new SharpDX.DirectWrite.TextFormat(NinjaTrader.Core.Globals.DirectWriteFactory,
                "Arial", SharpDX.DirectWrite.FontWeight.Normal, SharpDX.DirectWrite.FontStyle.Normal, 11f);

            // Gauge bar.
            float gx = x + 120f, gy = y + 28f, gw = 168f, gh = 10f;
            var track = new SharpDX.Direct2D1.SolidColorBrush(RenderTarget, new SharpDX.Color(38, 38, 43, 255));
            RenderTarget.FillRectangle(new SharpDX.RectangleF(gx, gy, gw, gh), track);
            track.Dispose();

            if (!double.IsNaN(hudScore))
            {
                float frac = (float)Math.Max(0.0, Math.Min(1.0, hudScore / 100.0));
                RenderTarget.FillRectangle(new SharpDX.RectangleF(gx, gy, gw * frac, gh), accentBrush);
            }

            // Threshold tick + label.
            float tfrac = (float)Math.Max(0.0, Math.Min(1.0, MinProbabilityThreshold / 100.0));
            float tx = gx + gw * tfrac;
            var tickBrush = new SharpDX.Direct2D1.SolidColorBrush(RenderTarget, new SharpDX.Color(255, 255, 255, 255));
            RenderTarget.FillRectangle(new SharpDX.RectangleF(tx - 1f, gy - 3f, 2f, gh + 6f), tickBrush);
            tickBrush.Dispose();
            RenderTarget.DrawText(string.Format("{0:F0}", MinProbabilityThreshold), tfSmall,
                new SharpDX.RectangleF(tx - 10f, gy + gh + 1f, 26f, 14f), subBrush);

            // Subtitle next to the big score.
            RenderTarget.DrawText(subtitle, tfSmall,
                new SharpDX.RectangleF(x + 12f, y + 36f, 105f, 14f), subBrush);

            // Mini-history strip (last scores as thin bars under the gauge).
            int n = hudHistory.Count;
            if (n > 1)
            {
                float hx = gx, hy = y + h - 9f, hw = gw, barW = hw / 32f;
                for (int i = 0; i < n; i++)
                {
                    double v = hudHistory[i];
                    float bh = (float)(Math.Max(0.0, Math.Min(1.0, v / 100.0)) * 6.0) + 1f;
                    var c = v >= MinProbabilityThreshold
                        ? new SharpDX.Color(46, 200, 90, 200)
                        : new SharpDX.Color(120, 124, 130, 200);
                    var hb = new SharpDX.Direct2D1.SolidColorBrush(RenderTarget, c);
                    RenderTarget.FillRectangle(
                        new SharpDX.RectangleF(hx + i * barW, hy + (7f - bh), barW * 0.7f, bh), hb);
                    hb.Dispose();
                }
            }

            tfSmall.Dispose();
            subBrush.Dispose();
            accentBrush.Dispose();
        }
    }
}
