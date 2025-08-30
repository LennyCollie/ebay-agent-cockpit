import sys, os, traceback, importlib

print("PY:", sys.version)
print("EXE:", sys.executable)
print("CWD:", os.getcwd())

try:
    m = importlib.import_module("app")
    print("OK app import:", getattr(m, "__file__", None), "has Flask:", hasattr(m, "app"))
    app = getattr(m, "app")
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
except Exception:
    print("\nIMPORT/RUN ERROR:\n")
    traceback.print_exc()
    input("\n[ENTER] to close...")
