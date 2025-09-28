# diag_app.py — prüft, wie deine Flask-App bereitgestellt wird
import traceback

print("== Diagnose: app.py importieren ==")
try:
    import app  # dein app.py als Modul

    print("app.py gefunden:", getattr(app, "__file__", app))
    print("hat Variable 'app':", hasattr(app, "app"))
    print("hat Factory 'create_app':", hasattr(app, "create_app"))
except Exception:
    print("FEHLER: Import von app.py schlug fehl:")
    traceback.print_exc()
    raise SystemExit(1)

print("\n== Start-Test (nur ermitteln, nicht laufen lassen) ==")
try:
    if hasattr(app, "app"):
        print("Startpfad: --app app:app (Variable 'app')")
    elif hasattr(app, "create_app"):
        print("Startpfad: --app app:create_app (Factory)")
    else:
        print("Weder 'app' noch 'create_app' gefunden.")
except Exception:
    traceback.print_exc()
