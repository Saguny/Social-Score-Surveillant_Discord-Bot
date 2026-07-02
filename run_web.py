import subprocess
import sys

RESTART_CODE = 42

while True:
    result = subprocess.run([sys.executable, "web_service.py"])
    if result.returncode != RESTART_CODE:
        break
    print("Restarting web service...")
