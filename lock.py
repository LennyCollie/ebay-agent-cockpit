# lock.py
import os
import contextlib
import time

LOCK_PATH = os.environ.get("AGENT_LOCK_PATH", "instance/agent.lock")

# fcntl = Unix-Datei-Lock (Render läuft auf Linux). Für Windows-Lokalentwicklung fallback.
try:
    import fcntl
    HAVE_FCNTL = True
except Exception:
    HAVE_FCNTL = False

from threading import Lock
_process_lock = Lock()

@contextlib.contextmanager
def agent_lock(timeout=110):
    """
    Sichert, dass immer nur EIN Agent-Lauf gleichzeitig startet.
    Unter Linux per Datei-Lock (prozessübergreifend), sonst Fallback auf Prozess-Lock.
    """
    if HAVE_FCNTL:
        os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
        f = open(LOCK_PATH, "a+")
        start = time.time()
        try:
            while True:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.time() - start > timeout:
                        raise TimeoutError("Agent lock timeout")
                    time.sleep(1)
            yield
        finally:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except Exception:
                pass
            f.close()
    else:
        # Fallback (z.B. Windows lokal)
        acquired = _process_lock.acquire(timeout=timeout)
        if not acquired:
            raise TimeoutError("Agent lock timeout")
        try:
            yield
        finally:
            _process_lock.release()