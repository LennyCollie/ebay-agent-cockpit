import traceback
try:
    import app
    print("OK: app importiert. Flask-Instanz:", getattr(app, "app", None))
except Exception:
    print("\nFEHLER BEIM IMPORT VON app.py:\n")
    traceback.print_exc()
