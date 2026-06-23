import subprocess
import sys

RESTART_CODE = 42

while True:
    result = subprocess.run([sys.executable, "scheduler.py"])
    if result.returncode != RESTART_CODE:
        break
    print("Restarting scheduler...")
