import subprocess
import sys
import time

proc = subprocess.Popen(
    [sys.executable, "app.py"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1
)

start = time.time()
timeout = 15

for line in proc.stdout:
    print(line, end="")
    if time.time() - start > timeout:
        print(f"\n[Timeout after {timeout}s]")
        proc.terminate()
        break

proc.wait()
