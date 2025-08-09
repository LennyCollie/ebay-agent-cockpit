
# Frontend Bootstrap Pack – ebay-agent-cockpit

Sofort nutzbare Bootstrap-Variante (v5) für schnelles, schönes UI auf Render.

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
    │   └── custom.css
    └── js/
        └── main.js

## Einbindung (Flask/Jinja)
- `Flask(__name__, template_folder="templates", static_folder="static")`
- In deinen Views: `return render_template("dashboard.html")`
- Optional Error-Handler registrieren (404/500).

## Hinweise
- Bootstrap via CDN (CSS + JS bundle) wird in `base.html` eingebunden.
- Flash-Messages nutzen Bootstrap Alerts (dismissible).
