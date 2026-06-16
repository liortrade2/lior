// TOAIGaugeHUD — modern graphical gauge for the v4 bundle (price-panel overlay).
//
// Pure DISPLAY: reads score.txt / threshold.txt / entry_window.txt and draws a
// smooth SharpDX gauge at the top-left of the PRICE panel (a real graphic, not
// text blocks). It does NO file bridge and NO gating — TOAIExporterGaugeTick
// still does those and the per-instrument writing.
//
// Why a separate indicator: OnRender from a sub-panel indicator is clipped to
// its own panel, so a graphical HUD can't reach the price panel from there. An
// IsOverlay=true indicator's panel IS the price panel, so its OnRender draws
// there freely.
//
// Setup:
//   1. Add to the PRICE panel (it's an overlay).
//   2. On TOAIExporterGaugeTick set ShowTextHud = false (so the text banner and
//      this graphic don't both show).
//   3. Keeps using the same C:\LIOR_ML\<INSTR>\ files written by the exporter.
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
    public class TOAIGaugeHUD : Indicator
    {
        private const string RootDir = @"C:\LIOR_ML";
        private const string ThresholdFile = RootDir + @"\threshold.txt";
        private string scoreFile, entryWindowFile;

        [NinjaScriptProperty]
        public double MinProbabilityThreshold { get; set; } = 55.0;

        private double score = double.NaN, threshold = 55.0;
        private bool passed, inWindow = true, hasWindow;
        private double winLo = -1, winHi = -1;
        private bool prevPassed;
        private DateTime flashUntil = DateTime.MinValue;
        private DateTime lastScoreStamp = DateTime.MinValue;
        private readonly System.Collections.Generic.List<double> hist =
            new System.Collections.Generic.List<double>();

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "TOAIGaugeHUD";
                Calculate = Calculate.OnEachTick;
                IsOverlay = true;            // price panel — OnRender not clipped
                IsAutoScale = false;
                DisplayInDataBox = false;
                PaintPriceMarkers = false;
            }
            else if (State == State.DataLoaded)
            {
                string dataDir = RootDir + @"\" +
                    TOAIExporterGaugeTick.SanitizeName(Bars.Instrument.MasterInstrument.Name);
                scoreFile = dataDir + @"\score.txt";
                entryWindowFile = dataDir + @"\entry_window.txt";
                threshold = TOAIExporterGaugeTick.ReadThreshold(ThresholdFile, MinProbabilityThreshold);
                hasWindow = TOAIExporterGaugeTick.TryReadWindow(entryWindowFile, out winLo, out winHi);
            }
        }

        protected override void OnBarUpdate()
        {
            if (State == State.Historical) return;

            if (IsFirstTickOfBar)
            {
                threshold = TOAIExporterGaugeTick.ReadThreshold(ThresholdFile, threshold);
                hasWindow = TOAIExporterGaugeTick.TryReadWindow(entryWindowFile, out winLo, out winHi);
            }

            if (hasWindow)
            {
                double m = TOAIExporterGaugeTick.SessionMinutes(Time[0]);
                if (m < winLo || m > winHi)
                {
                    inWindow = false; passed = false; score = double.NaN; prevPassed = false;
                    return;
                }
            }
            inWindow = true;

            try
            {
                if (System.IO.File.Exists(scoreFile))
                {
                    DateTime st = System.IO.File.GetLastWriteTimeUtc(scoreFile);
                    if (st != lastScoreStamp)
                    {
                        lastScoreStamp = st;
                        double p;
                        if (double.TryParse(System.IO.File.ReadAllText(scoreFile).Trim(),
                                System.Globalization.NumberStyles.Float,
                                System.Globalization.CultureInfo.InvariantCulture, out p))
                        {
                            score = p;
                            hist.Add(p);
                            if (hist.Count > 40) hist.RemoveAt(0);
                        }
                    }
                }
            }
            catch { }

            passed = !double.IsNaN(score) && score >= threshold;
            if (passed && !prevPassed) flashUntil = DateTime.Now.AddSeconds(2);
            prevPassed = passed;
        }

        protected override void OnRender(NinjaTrader.Gui.Chart.ChartControl chartControl,
                                         NinjaTrader.Gui.Chart.ChartScale chartScale)
        {
            base.OnRender(chartControl, chartScale);
            if (RenderTarget == null || ChartPanel == null) return;

            float x = (float)ChartPanel.X + 14f;
            float y = (float)ChartPanel.Y + 12f;
            float w = 332f, h = 78f;

            SharpDX.Color accent =
                !inWindow ? new SharpDX.Color(120, 144, 156, 255) :
                passed ? new SharpDX.Color(38, 205, 96, 255) :
                         new SharpDX.Color(255, 86, 54, 255);
            SharpDX.Color dim = new SharpDX.Color(150, 156, 162, 255);

            var bg = new SharpDX.Direct2D1.SolidColorBrush(RenderTarget, new SharpDX.Color(16, 17, 20, 230));
            var panel = new SharpDX.Direct2D1.RoundedRectangle
            { Rect = new SharpDX.RectangleF(x, y, w, h), RadiusX = 10f, RadiusY = 10f };
            RenderTarget.FillRoundedRectangle(panel, bg);
            bg.Dispose();

            var aBrush = new SharpDX.Direct2D1.SolidColorBrush(RenderTarget, accent);
            var dBrush = new SharpDX.Direct2D1.SolidColorBrush(RenderTarget, dim);

            // Accent stripe down the left edge.
            RenderTarget.FillRectangle(new SharpDX.RectangleF(x, y + 8f, 4f, h - 16f), aBrush);
            if (DateTime.Now < flashUntil)
                RenderTarget.DrawRoundedRectangle(panel, aBrush, 2.5f);

            var dw = NinjaTrader.Core.Globals.DirectWriteFactory;

            // Small label.
            var fSmall = new SharpDX.DirectWrite.TextFormat(dw, "Segoe UI",
                SharpDX.DirectWrite.FontWeight.Normal, SharpDX.DirectWrite.FontStyle.Normal, 11f);
            RenderTarget.DrawText("WIN PROBABILITY", fSmall,
                new SharpDX.RectangleF(x + 18f, y + 9f, 160f, 14f), dBrush);

            // Big score.
            string big = double.IsNaN(score) ? "--" : string.Format("{0:F0}%", score);
            var fBig = new SharpDX.DirectWrite.TextFormat(dw, "Segoe UI",
                SharpDX.DirectWrite.FontWeight.Bold, SharpDX.DirectWrite.FontStyle.Normal, 33f);
            RenderTarget.DrawText(big, fBig,
                new SharpDX.RectangleF(x + 16f, y + 24f, 130f, 42f), aBrush);
            fBig.Dispose();

            // Verdict.
            string verdict = !inWindow ? "GATE CLOSED" : passed ? "ALLOWED" : "SKIPPED";
            var fMid = new SharpDX.DirectWrite.TextFormat(dw, "Segoe UI",
                SharpDX.DirectWrite.FontWeight.Bold, SharpDX.DirectWrite.FontStyle.Normal, 14f);
            RenderTarget.DrawText(verdict, fMid,
                new SharpDX.RectangleF(x + 150f, y + 50f, 170f, 20f), aBrush);
            fMid.Dispose();

            // Gauge bar (rounded track + rounded fill + threshold tick).
            float gx = x + 150f, gy = y + 20f, gw = 166f, gh = 12f;
            var track = new SharpDX.Direct2D1.SolidColorBrush(RenderTarget, new SharpDX.Color(44, 46, 52, 255));
            var trackRR = new SharpDX.Direct2D1.RoundedRectangle
            { Rect = new SharpDX.RectangleF(gx, gy, gw, gh), RadiusX = gh / 2f, RadiusY = gh / 2f };
            RenderTarget.FillRoundedRectangle(trackRR, track);
            track.Dispose();

            if (!double.IsNaN(score))
            {
                float frac = (float)Math.Max(0.05, Math.Min(1.0, score / 100.0));
                var fillRR = new SharpDX.Direct2D1.RoundedRectangle
                { Rect = new SharpDX.RectangleF(gx, gy, gw * frac, gh), RadiusX = gh / 2f, RadiusY = gh / 2f };
                RenderTarget.FillRoundedRectangle(fillRR, aBrush);
            }

            float tx = gx + gw * (float)Math.Max(0.0, Math.Min(1.0, threshold / 100.0));
            var tick = new SharpDX.Direct2D1.SolidColorBrush(RenderTarget, new SharpDX.Color(255, 255, 255, 235));
            RenderTarget.FillRectangle(new SharpDX.RectangleF(tx - 1f, gy - 3f, 2f, gh + 6f), tick);
            tick.Dispose();
            RenderTarget.DrawText(string.Format("min {0:F0}", threshold), fSmall,
                new SharpDX.RectangleF(gx, gy + gh + 3f, 90f, 14f), dBrush);

            // Sparkline of recent scores (thin bars; green above threshold).
            if (hist.Count > 1)
            {
                float sx = gx, sy = y + 50f, sh = 20f, bw = gw / 40f;
                int n = hist.Count, start = Math.Max(0, n - 40), cnt = n - start;
                for (int i = 0; i < cnt; i++)
                {
                    double v = Math.Max(0.0, Math.Min(100.0, hist[start + i]));
                    float bh = (float)(v / 100.0) * sh + 1f;
                    SharpDX.Color c = v >= threshold ? accent : dim;
                    var hb = new SharpDX.Direct2D1.SolidColorBrush(RenderTarget,
                        new SharpDX.Color(c.R, c.G, c.B, (byte)165));
                    RenderTarget.FillRectangle(
                        new SharpDX.RectangleF(sx + i * bw, sy + sh - bh, bw * 0.7f, bh), hb);
                    hb.Dispose();
                }
            }

            fSmall.Dispose();
            aBrush.Dispose();
            dBrush.Dispose();
        }
    }
}
