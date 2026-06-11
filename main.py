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
  5. Exit
"""


def main():
    while True:
        print(MENU.format(data_dir=config.DATA_DIR))
        choice = input("Select option [1-5]: ").strip()

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
            sys.exit(0)

        else:
            print("Invalid choice.")


if __name__ == "__main__":
    main()
