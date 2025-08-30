import importlib, traceback, sys, os
print("cwd:", os.getcwd())
try:
    m = importlib.import_module("app")
    print("OK:", getattr(m, "__file__", None), "has Flask:", hasattr(m, "app"))
except Exception:
    print("IMPORT ERROR:")
    traceback.print_exc()
