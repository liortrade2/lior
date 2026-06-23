#region Using declarations
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using NinjaTrader.Cbi;
#endregion

// ============================================================================
//  TOAI Execution Logger  —  closes the live learning loop.
//
//  This is a background NinjaScript AddOn (no window). It listens to every
//  account's executions and, whenever a trade completes, writes the account's
//  completed trades to:
//
//        <DataRoot>\<INSTRUMENT>\executions.csv
//
//  in the same column layout as a NinjaTrader "Trades" export, which TOAI's
//  journal (toai/journal.py) already understands. The TOAI Control Panel's
//  watch picks the file up automatically and appends each new fill — next to
//  the score the ML gate gave it — into the permanent journal.csv ledger.
//
//  This is the local, no-cloud equivalent of the TradesViz / CrossTrade
//  auto-sync connectors: fills never leave the machine, and the loop is fully
//  autonomous.
//
//  INSTALL (once):
//    1. NinjaScript Editor -> right-click -> New -> AddOn  (or paste this file
//       into Documents\NinjaTrader 8\bin\Custom\AddOns\TOAIExecutionLogger.cs).
//    2. Press F5 to compile. It loads at platform startup and runs in the
//       background — nothing to open.
//    3. Make sure the TOAI Control Panel is running during trading so it
//       ingests executions.csv into journal.csv before the session resets.
//
//  NOTE: executions.csv holds the CURRENT session's completed trades and is
//  rewritten as trades close; journal.csv (written by the Python watch) is the
//  permanent, deduped accumulation across all sessions. Keep the Control Panel
//  open while trading so nothing is missed.
//
//  Data root defaults to C:\LIOR_ML (or the TOAI_DATA_DIR env var, matching
//  toai/config.py). Edit DefaultDataRoot below if your path differs.
// ============================================================================

namespace NinjaTrader.NinjaScript.AddOns
{
    public class TOAIExecutionLogger : NinjaTrader.NinjaScript.AddOnBase
    {
        private const string DefaultDataRoot = @"C:\LIOR_ML";
        private const string DefaultPlaybackRoot = @"C:\LIOR_ML_PLAYBACK";

        private string dataRoot;
        private string playbackRoot;
        private readonly object writeLock = new object();
        private readonly List<Account> hooked = new List<Account>();

        // Initial Stop-Loss / Take-Profit capture per instrument, so Edgewonk
        // gets SL/TP (and can compute R-Multiple). Entries here are Market
        // orders, so any Stop order is the protective SL and any Limit order is
        // the TP. We keep the FIRST price seen after each entry (the INITIAL
        // risk — for a trailing SAR that's the SAR at entry). Net position is
        // tracked from execution quantities (no Positions API needed).
        private readonly object slLock = new object();
        private readonly Dictionary<string, double> netQty = new Dictionary<string, double>();
        private readonly Dictionary<string, double> initStop = new Dictionary<string, double>();
        private readonly Dictionary<string, double> initTarget = new Dictionary<string, double>();
        private readonly Dictionary<string, string> openKey = new Dictionary<string, string>();
        private readonly Dictionary<string, double[]> doneSlTp = new Dictionary<string, double[]>();

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "TOAIExecutionLogger";
                Description = "Logs completed trades to <DataRoot>\\<INSTRUMENT>\\executions.csv for the TOAI journal.";
                string env = Environment.GetEnvironmentVariable("TOAI_DATA_DIR");
                dataRoot = string.IsNullOrWhiteSpace(env) ? DefaultDataRoot : env;
                // Market-Replay fills come from the "Playback101" account — route
                // them to a separate root so the live journal stays clean.
                string pbEnv = Environment.GetEnvironmentVariable("TOAI_PLAYBACK_DIR");
                playbackRoot = string.IsNullOrWhiteSpace(pbEnv) ? DefaultPlaybackRoot : pbEnv;
            }
            else if (State == State.Configure)
            {
                // Account.All is a plain Collection (not observable), so we hook
                // the accounts present at startup. Sim101 / live accounts exist
                // by the time AddOns configure, so this covers the normal case.
                HookAllAccounts();
            }
            else if (State == State.Terminated)
            {
                UnhookAllAccounts();
            }
        }

        private void HookAllAccounts()
        {
            lock (Account.All)
                foreach (Account a in Account.All)
                    Hook(a);
        }

        private void Hook(Account a)
        {
            if (a == null || hooked.Contains(a))
                return;
            a.ExecutionUpdate += OnExecutionUpdate;
            a.OrderUpdate += OnOrderUpdate;
            hooked.Add(a);
        }

        private void UnhookAllAccounts()
        {
            foreach (Account a in hooked)
            {
                try { a.ExecutionUpdate -= OnExecutionUpdate; } catch { }
                try { a.OrderUpdate -= OnOrderUpdate; } catch { }
            }
            hooked.Clear();
        }

        private void OnExecutionUpdate(object sender, ExecutionEventArgs e)
        {
            Account account = sender as Account;
            if (account == null)
                return;
            try
            {
                TrackPosition(e);
                WriteAccount(account);
            }
            catch (Exception ex)
            {
                NinjaTrader.Code.Output.Process(
                    "TOAIExecutionLogger: " + ex.Message, PrintTo.OutputTab1);
            }
        }

        // Capture the protective Stop / Target prices submitted right after an
        // entry. Keep the first one per open trade = the INITIAL SL / TP.
        private void OnOrderUpdate(object sender, OrderEventArgs e)
        {
            try
            {
                Order o = e.Order;
                if (o == null || o.Instrument == null)
                    return;
                string instr = o.Instrument.MasterInstrument.Name;
                lock (slLock)
                {
                    bool open = netQty.ContainsKey(instr) && netQty[instr] != 0;
                    if (!open)
                        return;   // only while a position is live
                    if (o.OrderType == OrderType.StopMarket || o.OrderType == OrderType.StopLimit)
                    {
                        if (!initStop.ContainsKey(instr) && o.StopPrice > 0)
                            initStop[instr] = o.StopPrice;
                    }
                    else if (o.OrderType == OrderType.Limit)
                    {
                        if (!initTarget.ContainsKey(instr) && o.LimitPrice > 0)
                            initTarget[instr] = o.LimitPrice;
                    }
                }
            }
            catch { }
        }

        // Track net position from execution quantities (Long adds, Short
        // subtracts) so we know when a trade opens (reset SL/TP) and closes
        // (store the captured SL/TP under the entry-time key WriteInstrument
        // looks up).
        private void TrackPosition(ExecutionEventArgs e)
        {
            if (e == null || e.Execution == null || e.Execution.Instrument == null)
                return;
            Execution x = e.Execution;
            string instr = x.Instrument.MasterInstrument.Name;
            double signed = (x.MarketPosition == MarketPosition.Long ? 1.0 : -1.0) * x.Quantity;
            lock (slLock)
            {
                double prev = netQty.ContainsKey(instr) ? netQty[instr] : 0.0;
                double now = prev + signed;
                netQty[instr] = now;
                if (prev == 0 && now != 0)            // opened a new trade
                {
                    initStop.Remove(instr);
                    initTarget.Remove(instr);
                    openKey[instr] = instr + "|" +
                        x.Time.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);
                }
                else if (prev != 0 && now == 0)       // closed -> finalize
                {
                    string key = openKey.ContainsKey(instr) ? openKey[instr] : null;
                    if (key != null)
                        doneSlTp[key] = new double[] {
                            initStop.ContainsKey(instr) ? initStop[instr] : double.NaN,
                            initTarget.ContainsKey(instr) ? initTarget[instr] : double.NaN };
                }
            }
        }

        private void WriteAccount(Account account)
        {
            List<Execution> execs = account.Executions.ToList();
            if (execs.Count == 0)
                return;

            // SystemPerformance.Calculate() pairs entry/exit executions into
            // completed Trade objects (with realized ProfitCurrency) and returns
            // a SystemPerformance instance whose AllTrades we read. Wrapped in
            // writeLock so calculate + read + write is atomic across threads.
            lock (writeLock)
            {
                var perf = SystemPerformance.Calculate(execs);
                if (perf == null)
                    return;

                Dictionary<string, List<Trade>> byInst = new Dictionary<string, List<Trade>>();
                foreach (Trade t in perf.AllTrades)
                {
                    if (t == null || t.Entry == null || t.Entry.Instrument == null)
                        continue;
                    string inst = t.Entry.Instrument.MasterInstrument.Name;
                    if (!byInst.ContainsKey(inst))
                        byInst[inst] = new List<Trade>();
                    byInst[inst].Add(t);
                }

                // Playback fills (account "Playback101") go to the playback root.
                bool isPlayback = account.Name != null &&
                    account.Name.IndexOf("Playback", StringComparison.OrdinalIgnoreCase) >= 0;
                string root = isPlayback ? playbackRoot : dataRoot;

                foreach (KeyValuePair<string, List<Trade>> kv in byInst)
                    WriteInstrument(root, account, kv.Key, kv.Value);
            }
        }

        private void WriteInstrument(string root, Account account, string inst, List<Trade> trades)
        {
            string dir = Path.Combine(root, inst);
            Directory.CreateDirectory(dir);
            // Per-ACCOUNT filenames so multiple accounts trading the same
            // instrument never overwrite each other. The dashboard/watch glob
            // executions_*.csv and tell accounts apart by the "Account" column
            // (the pro-journal pattern: one store, filter by account).
            string acct = SanitizeAccount(account.Name);
            string dest = Path.Combine(dir, "executions_" + acct + ".csv");

            // Commission + MAE/MFE + Highest/Lowest price feed Edgewonk's
            // optional fields (the TOAI Python export maps them straight over).
            string header = "Trade number,Instrument,Account,Market pos.,Qty,Entry price,Exit price,Entry time,Exit time,Profit,Commission,MAE,MFE,Highest price,Lowest price,Stop Loss,Take Profit";
            StringBuilder sb = new StringBuilder();
            sb.AppendLine(header);
            // Per-entry-date rows for the durable executions_<date>.csv files,
            // so a session that closes while the Control Panel is OFF is still
            // ingested later (executions.csv is overwritten each session).
            Dictionary<string, StringBuilder> byDate = new Dictionary<string, StringBuilder>();
            foreach (Trade t in trades)
            {
                Execution en = t.Entry;
                Execution ex = t.Exit;
                string entryTime = en != null ? en.Time.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) : "";
                string exitTime = ex != null ? ex.Time.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) : "";
                string pos = en != null ? en.MarketPosition.ToString() : "";
                double entryPrice = en != null ? en.Price : 0;
                double exitPrice = ex != null ? ex.Price : 0;

                // Initial SL/TP captured at entry (blank if none was placed).
                double sl = double.NaN, tp = double.NaN;
                string slKey = inst + "|" + entryTime;
                lock (slLock)
                {
                    if (doneSlTp.ContainsKey(slKey))
                    {
                        sl = doneSlTp[slKey][0];
                        tp = doneSlTp[slKey][1];
                    }
                }
                string slStr = double.IsNaN(sl) ? "" : sl.ToString(CultureInfo.InvariantCulture);
                string tpStr = double.IsNaN(tp) ? "" : tp.ToString(CultureInfo.InvariantCulture);

                double commission = (en != null ? en.Commission : 0) + (ex != null ? ex.Commission : 0);
                // MAE/MFE come in $ — convert to points via the contract's point
                // value, then to the actual high/low price the trade reached.
                double maeCur = t.MaeCurrency;
                double mfeCur = t.MfeCurrency;
                double pv = (en != null && en.Instrument != null)
                    ? en.Instrument.MasterInstrument.PointValue : 0;
                double denom = pv * t.Quantity;
                double maePts = denom > 0 ? maeCur / denom : 0;
                double mfePts = denom > 0 ? mfeCur / denom : 0;
                bool isLong = en != null && en.MarketPosition == MarketPosition.Long;
                double highest = isLong ? entryPrice + mfePts : entryPrice + maePts;
                double lowest = isLong ? entryPrice - maePts : entryPrice - mfePts;

                string line = string.Format(CultureInfo.InvariantCulture,
                    "{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10},{11},{12},{13},{14},{15},{16}",
                    t.TradeNumber, inst, account.Name, pos, t.Quantity,
                    entryPrice, exitPrice, entryTime, exitTime, t.ProfitCurrency,
                    commission, maeCur, mfeCur, highest, lowest, slStr, tpStr);
                sb.AppendLine(line);

                string day = entryTime.Length >= 10 ? entryTime.Substring(0, 10) : "unknown";
                if (!byDate.ContainsKey(day))
                {
                    byDate[day] = new StringBuilder();
                    byDate[day].AppendLine(header);
                }
                byDate[day].AppendLine(line);
            }

            // Current-session snapshot (the live watch reads this).
            WriteAtomic(dest, sb.ToString());
            // Durable per-day files — never overwritten across sessions, so the
            // watch ingests any session it missed on its next pass.
            foreach (KeyValuePair<string, StringBuilder> kv in byDate)
                WriteAtomic(Path.Combine(dir, "executions_" + acct + "_" + kv.Key + ".csv"),
                            kv.Value.ToString());
        }

        // Make a NinjaTrader account name (e.g. "BX104751-01!Bulenox!Bulenox")
        // safe and clean for a filename, without losing the raw name in the CSV.
        private static string SanitizeAccount(string name)
        {
            if (string.IsNullOrEmpty(name))
                return "Unknown";
            foreach (char c in Path.GetInvalidFileNameChars())
                name = name.Replace(c, '_');
            return name.Replace('!', '_').Replace(' ', '_');
        }

        // Atomic-ish write (temp + overwrite) so the Python watch never reads a
        // half-written file.
        private static void WriteAtomic(string dest, string content)
        {
            string tmp = dest + ".tmp";
            File.WriteAllText(tmp, content);
            File.Copy(tmp, dest, true);
            File.Delete(tmp);
        }
    }
}
