import subprocess
import sys

RESTART_CODE = 42

while True:
    result = subprocess.run([sys.executable, "bot.py"])
    if result.returncode != RESTART_CODE:
        break
    print("Restarting bot...")
