"""TOAI — Trade Optimizer AI

Interactive entry point. Run: python main.py
"""
import sys

from toai import config


MENU = """
==============================================
  TOAI — Trade Optimizer AI
  ML Trade Filter for NinjaTrader / BlackBird
==============================================
  Data directory: {data_dir}

  1. Generate sample data (synthetic, for testing the pipeline)
  2. Train model + show PMV score
  3. Score latest bar (one-shot)
  4. Watch mode (real-time scoring loop for NinjaTrader)
  5. Control panel (live monitor + variant switch + auto-train) ← NEW
  6. Build training file from backtest (trades export + bar_data.csv)
  7. Score history (bar_scores.csv — retroactive + Playback display)
  8. Strategy variants (list / switch the active model)
  9. Live scorecard (win-rate + expectancy by score, vs real PnL)
  10. Trade journal (REALIZED results from actual fills)
  11. Expectancy model (train on $ not win/loss — compare + save variant)
  12. Position sizing (does score-tiered sizing beat uniform?)
  13. Export to Edgewonk (.xlsx, tagged with the TOAI score) ← NEW
  14. Model health (stale-model + live-vs-backtest drift alerts) ← NEW
  15. Exit
"""


def manage_variants():
    from toai import variants
    insts = config.list_instruments()
    if not insts:
        print("No instruments with data yet. Train an export first.")
        return
    print("\nInstruments:")
    for i, name in enumerate(insts, 1):
        print(f"  {i}. {name}")
    pick = input("Pick instrument # (Enter to cancel): ").strip()
    if not pick:
        return
    try:
        inst = insts[int(pick) - 1]
    except (ValueError, IndexError):
        print("Invalid choice.")
        return
    config.set_instrument(inst)

    vs = variants.list_variants()
    if not vs:
        print(f"\nNo saved variants for {inst} yet — train a backtest export "
              "and it will be saved automatically.")
        return
    print(f"\nSaved variants for {inst}:")
    for i, (s, info) in enumerate(vs, 1):
        mark = "  <== ACTIVE" if info.get("active") else ""
        print(f"  {i}. {info['name'][:55]}{mark}")
        print(f"       PMV {info.get('pmv')}   WF {info.get('wf_mean')}   "
              f"saved {info.get('saved')}")
    print("\n  Enter a number to ACTIVATE that variant,")
    print("  or 'd<number>' to DELETE it (e.g. d2), or Enter to cancel.")
    sel = input("> ").strip().lower()
    if not sel:
        return
    delete = sel.startswith("d")
    num = sel[1:] if delete else sel
    try:
        s, info = vs[int(num) - 1]
    except (ValueError, IndexError):
        print("Invalid choice.")
        return
    if delete:
        variants.delete_variant(s)
        print(f"Deleted variant: {info['name']}")
    elif variants.select_variant(s):
        print(f"\nActivated: {info['name']}")
        print("History rescored. RELOAD the chart and the live scores now use "
              "this variant.")
    else:
        print("Could not activate (model file missing).")


def show_scorecard():
    from toai import scorecard
    insts = config.list_instruments() or [None]
    if insts == [None] and not (config.DATA_ROOT / "training_data.csv").exists():
        print("No instruments with trade data yet. Train a backtest export first.")
        return
    if len(insts) > 1:
        print("\nInstruments:")
        for i, name in enumerate(insts, 1):
            print(f"  {i}. {name}")
        pick = input("Pick instrument # (Enter for all): ").strip()
        if pick:
            try:
                insts = [insts[int(pick) - 1]]
            except (ValueError, IndexError):
                print("Invalid choice.")
                return
    for inst in insts:
        print("\n(computing walk-forward scorecard…)")
        sc = scorecard.scorecard_for_instrument(inst)
        if sc is None:
            print(f"No scorecard for {inst or 'root'} — needs training_data.csv "
                  "with both winning and losing trades.")
            continue
        print(scorecard.format_scorecard(sc))


def show_journal():
    from toai import journal, scorecard
    insts = config.list_instruments() or [None]
    for inst in insts:
        s = journal.summary_for(inst)
        if not s:
            print(f"\n{inst or 'root'}: journal empty — live fills appear here as "
                  "the watch logs trades from executions.csv.")
            continue
        srcs = "  ".join(f"{k}:{v}" for k, v in s["by_source"].items())
        print(f"\n{inst or 'root'} journal: {s['total']} trades  ({srcs})")
        sc = journal.live_scorecard_for(inst)   # realized (live) only
        if sc is None:
            print("  (no live fills yet — backtest rows are tracked but the "
                  "realized scorecard needs actual fills)")
            continue
        print(scorecard.format_scorecard(sc))


def run_expectancy():
    from toai import expectancy
    insts = config.list_instruments() or [None]
    for inst in insts:
        try:
            print(expectancy.compare(inst))
        except FileNotFoundError:
            print(f"{inst or 'root'}: no training_data.csv — train a backtest first.")
            continue
        ans = input(f"Train + save the expectancy variant for {inst}? (it stays "
                    "INACTIVE — compare in the panel, activate if it wins) [y/N]: ").strip().lower()
        if ans == "y":
            try:
                slug = expectancy.train_expectancy(inst)
                print(f"Saved variant: {slug}. Open the Control Panel -> {inst} -> "
                      "⚖ Compare to see it vs the active model, then Activate if you like.")
            except Exception as e:
                print(f"Could not train: {e}")


def main():
    while True:
        print(MENU.format(data_dir=config.DATA_DIR))
        choice = input("Select option [1-15]: ").strip()

        if choice == "1":
            from toai.simulate import write_sample_files
            write_sample_files()

        elif choice == "2":
            from toai.train import train
            try:
                train()
            except FileNotFoundError:
                print(f"No training file at {config.TRAINING_FILE}.")
                print("Export trades from NinjaTrader first, or use option 1 to test.")
            except ValueError as e:
                print(f"Error: {e}")

        elif choice == "3":
            from toai.score import score_latest_bar
            try:
                score = score_latest_bar()
                verdict = "ALLOW" if score >= config.MIN_PROBABILITY_THRESHOLD else "SKIP"
                print(f"ProbOfTrue: {score}  ->  {verdict} "
                      f"(threshold {config.MIN_PROBABILITY_THRESHOLD})")
            except FileNotFoundError as e:
                print(f"Missing file: {e.filename}. Train a model first (option 2).")

        elif choice == "4":
            from toai.score import watch
            try:
                watch()
            except KeyboardInterrupt:
                print("\nStopped watching.")
            except FileNotFoundError as e:
                print(f"Missing file: {e.filename}. Train a model first (option 2).")

        elif choice == "5":
            from toai.control_panel import main as panel_main
            panel_main()

        elif choice == "6":
            from toai.merge import merge_backtest
            trades_path = input("Path to the Strategy Analyzer trades CSV: ").strip().strip('"')
            try:
                merge_backtest(trades_path)
            except FileNotFoundError as e:
                print(f"Missing file: {e.filename}")
                print(f"(bar_data.csv expected at {config.BAR_DATA_FILE} — "
                      "load the chart with TOAIExporter and ExportBarData=true first)")
            except ValueError as e:
                print(f"Error: {e}")

        elif choice == "7":
            from toai.score_history import score_history
            try:
                score_history()
            except FileNotFoundError as e:
                print(f"Missing file: {e.filename}. Need a trained model (option 2)")
                print("and bar_data.csv (chart with TOAIExporter, ExportBarData=true).")

        elif choice == "8":
            manage_variants()

        elif choice == "9":
            show_scorecard()

        elif choice == "10":
            show_journal()

        elif choice == "11":
            run_expectancy()

        elif choice == "12":
            from toai import sizing
            for inst in (config.list_instruments() or [None]):
                print(sizing.report(inst))

        elif choice == "13":
            from toai import edgewonk
            src = input("Folder/file with NinjaTrader exports "
                        f"(Enter = {config.DATA_ROOT}): ").strip().strip('"')
            results = (edgewonk.convert_all(src or None)
                       if not src or not src.lower().endswith((".csv", ".xlsx"))
                       else [(src, *edgewonk.to_edgewonk(src))])
            for row in results:
                print(f"  -> {row[1]}{row[2] if len(row) > 2 else ''}")
            print(f"\nReady in {config.DATA_ROOT}\\_edgewonk\\ — import the .xlsx into Edgewonk.")

        elif choice == "14":
            from toai import health
            print("\nMODEL HEALTH")
            for inst in (config.list_instruments() or [None]):
                print(health.format_report(inst))

        elif choice == "15":
            sys.exit(0)

        else:
            print("Invalid choice.")


if __name__ == "__main__":
    main()
