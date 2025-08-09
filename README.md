
# Frontend Starter Pack – ebay-agent-cockpit

Sofort verwendbare Templates & CSS, damit die Render-App wieder aussieht wie gewohnt.

## Struktur
.
├── templates/
│   ├── base.html
│   ├── _flash.html
│   ├── dashboard.html
│   ├── 404.html
│   └── 500.html
└── static/
    ├── css/
    │   ├── base.css
    │   └── dashboard.css
    └── js/
        └── main.js

## Einbindung (Flask/Jinja)
1) Stelle sicher, dass `Flask(__name__, template_folder="templates", static_folder="static")` korrekt ist.
2) In deinen Views: `return render_template("dashboard.html", ...)`
3) Optional: Error-Handler registrieren:
   ```python
   @app.errorhandler(404)
   def not_found(e): return render_template("404.html"), 404

   @app.errorhandler(500)
   def server_error(e): return render_template("500.html"), 500
   ```

## Hinweise
- Pure CSS (kein CDN nötig). Bootstrap kann später zusätzlich eingebunden werden.
- Farben, Spacing und Breakpoints sind in `base.css` zentral definiert.
- Flash-Messages: `flash("Dein Text", "success|info|warning|danger")`
