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

        private string dataRoot;
        private readonly object writeLock = new object();
        private readonly List<Account> hooked = new List<Account>();

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "TOAIExecutionLogger";
                Description = "Logs completed trades to <DataRoot>\\<INSTRUMENT>\\executions.csv for the TOAI journal.";
                string env = Environment.GetEnvironmentVariable("TOAI_DATA_DIR");
                dataRoot = string.IsNullOrWhiteSpace(env) ? DefaultDataRoot : env;
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
            hooked.Add(a);
        }

        private void UnhookAllAccounts()
        {
            foreach (Account a in hooked)
            {
                try { a.ExecutionUpdate -= OnExecutionUpdate; } catch { }
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
                WriteAccount(account);
            }
            catch (Exception ex)
            {
                NinjaTrader.Code.Output.Process(
                    "TOAIExecutionLogger: " + ex.Message, PrintTo.OutputTab1);
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

                foreach (KeyValuePair<string, List<Trade>> kv in byInst)
                    WriteInstrument(account, kv.Key, kv.Value);
            }
        }

        private void WriteInstrument(Account account, string inst, List<Trade> trades)
        {
            string dir = Path.Combine(dataRoot, inst);
            Directory.CreateDirectory(dir);
            string dest = Path.Combine(dir, "executions.csv");

            StringBuilder sb = new StringBuilder();
            sb.AppendLine("Trade number,Instrument,Account,Market pos.,Qty,Entry price,Exit price,Entry time,Exit time,Profit");
            foreach (Trade t in trades)
            {
                Execution en = t.Entry;
                Execution ex = t.Exit;
                string entryTime = en != null ? en.Time.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) : "";
                string exitTime = ex != null ? ex.Time.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) : "";
                string pos = en != null ? en.MarketPosition.ToString() : "";
                double entryPrice = en != null ? en.Price : 0;
                double exitPrice = ex != null ? ex.Price : 0;

                sb.AppendLine(string.Format(CultureInfo.InvariantCulture,
                    "{0},{1},{2},{3},{4},{5},{6},{7},{8},{9}",
                    t.TradeNumber, inst, account.Name, pos, t.Quantity,
                    entryPrice, exitPrice, entryTime, exitTime, t.ProfitCurrency));
            }

            // Atomic-ish write (temp + overwrite) so the Python watch never
            // reads a half-written file.
            string tmp = dest + ".tmp";
            File.WriteAllText(tmp, sb.ToString());
            File.Copy(tmp, dest, true);
            File.Delete(tmp);
        }
    }
}
