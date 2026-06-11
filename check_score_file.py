"""Check if score.txt exists and what it contains."""
import time
from pathlib import Path
from toai import config

score_file = config.DATA_DIR / "score.txt"

print(f"Watching: {score_file}")
print(f"Data dir: {config.DATA_DIR}")
print()

for i in range(10):
    if score_file.exists():
        content = score_file.read_text().strip()
        size = score_file.stat().st_size
        mtime = score_file.stat().st_mtime
        now = time.time()
        age_sec = now - mtime
        print(f"✓ EXISTS | Content: '{content}' | Size: {size} bytes | Age: {age_sec:.1f}s")
    else:
        print(f"✗ NOT FOUND")
    time.sleep(1)
