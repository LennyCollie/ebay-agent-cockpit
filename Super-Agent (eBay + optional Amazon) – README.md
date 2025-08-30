Ein kleiner Such-Agent mit Web-UI, E-Mail-Alerts und (optional) Amazon-PAAPI.
Stack: Python 3.10+, Flask, SQLite/Postgres, SMTP.

Features

Suche über eBay Browse API (Client-Credentials OAuth)

Optional: Amazon PA-API (wenn Schlüssel vorhanden)

Ergebnis-Caching, Paginierung, Filter (Preis, Zustand, Sortierung)

E-Mail-Benachrichtigungen inkl. De-Duping/Cooldown

Alerts speichern + Agent-Run via privatem HTTP-Trigger

Health/Debug Seiten: /status, /healthz, /_debug/*, /debug

1) Lokale Entwicklung
Voraussetzungen

Python 3.10 oder höher

(optional) Git

Setup
# In den Projektordner
cd ebay-agent-cockpit

# Virtuelle Umgebung
python -m venv .venv
# Windows PowerShell:
. .\.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

pip install -U pip
pip install -r requirements.txt  # falls vorhanden
# oder, wenn keine requirements.txt:
pip install flask requests python-dotenv amazon-paapi stripe

ENV anlegen

Erstelle .env.local im Projektroot (nie commiten):

# --- App ---
SECRET_KEY=change-this-in-prod
PLAUSIBLE_DOMAIN=

# --- Suche ---
LIVE_SEARCH=0            # lokal erst mal 0 (Demo-Ergebnisse). Auf 1 setzen, wenn Keys ok.

# --- eBay ---
EBAY_CLIENT_ID=
EBAY_CLIENT_SECRET=
EBAY_SCOPES=https://api.ebay.com/oauth/api_scope
EBAY_GLOBAL_ID=EBAY-DE

# --- Optional Amazon ---
AMZ_ENABLED=0
AMZ_ACCESS_KEY_ID=
AMZ_SECRET_ACCESS_KEY=
AMZ_PARTNER_TAG=
AMZ_COUNTRY=DE

# --- Affiliate optional (z.B. campid=...,customid=...) ---
AFFILIATE_PARAMS=

# --- SMTP ---
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
SMTP_FROM=Super-Agent <noreply@example.com>
SMTP_USE_TLS=1
SMTP_USE_SSL=0
NOTIFY_COOLDOWN_MINUTES=120
NOTIFY_MAX_ITEMS_PER_MAIL=20

# --- Limits & Cache ---
FREE_SEARCH_LIMIT=3
PREMIUM_SEARCH_LIMIT=10
PER_PAGE_DEFAULT=20
SEARCH_CACHE_TTL=60

# --- DB ---
DB_PATH=sqlite:///instance/db.sqlite3

# --- Stripe optional ---
STRIPE_SECRET_KEY=
STRIPE_PRICE_PRO=
STRIPE_WEBHOOK_SECRET=

# --- Interner Agent-Trigger ---
AGENT_TRIGGER_TOKEN=choose-a-long-random-token


Hinweis: Für echte eBay-Suche LIVE_SEARCH=1 setzen und EBAY_CLIENT_ID/SECRET füllen.

Starten (Entwicklungsserver)
# mit aktivierter venv:
python -c "from app import app; app.run(host='127.0.0.1', port=5000, debug=True, use_reloader=False)"
# dann öffnen: http://127.0.0.1:5000

Nützliche Routen

GET / → Start

GET /search → Suche (Form)

POST /alerts/send-now → E-Mail sofort senden (nutzt De-Duping)

POST /email/test → SMTP-Testmail

GET /status → Statusseite (oder ?format=json)

GET /_debug/ebay / /_debug/amazon / /debug / /healthz

2) E-Mail testen

Auf der Ergebnisseite „Jetzt E-Mail testen“ drücken oder manuell:

# Beispiel: per Formular aus /search (Button triggert POST /email/test)


Bei Problemen: siehe Troubleshooting unten.

3) Alerts & Agent-Run (Cron)
Manuell „Send now“

Button in der UI

Route: POST /alerts/send-now (nutzt De-Duping gegen Tabelle alert_seen)

Geplanter Run (HTTP-Trigger, empfohlen)

Der Agent-Runner lebt in agent.py und wird über eine private Endpoint aufgerufen:

POST /internal/run-agent
Authorization: Bearer <AGENT_TRIGGER_TOKEN>


PowerShell:

$Headers = @{ Authorization = 'Bearer YOUR_TOKEN' }
Invoke-WebRequest -Method POST -Uri 'https://<deine-app>/internal/run-agent' -Headers $Headers


curl:

curl -X POST https://<deine-app>/internal/run-agent \
  -H "Authorization: Bearer YOUR_TOKEN"


Auf Render kann das z.B. per Cron Job (Scheduler) stündlich/dauerhaft eingeplant werden.

4) Deployment auf Render
A) Web Service (Flask-App)

Repository verbinden (GitHub)

Build Command:
pip install -r requirements.txt

Start Command (Beispiel mit gunicorn, wenn vorhanden):
gunicorn app:app -w 2 -b 0.0.0.0:$PORT
(oder: python -m gunicorn app:app …; zur Not python app.py – aber Gunicorn ist empfohlen)

Environment: „Python“

Environment Variables in Render setzen:

Alle aus .env.local – ohne sie zu committen.

In Produktion LIVE_SEARCH=1.

Optional Storage:

Für SQLite: DB_PATH=sqlite:///instance/db.sqlite3 (Render Persistent Disk benutzen).

Oder Postgres nutzen: DATABASE_URL=postgresql://… und App darauf umstellen (App kann beides).

B) Scheduler (Cron)

Neuen Render Cron Job anlegen:

Command: curl -s -X POST https://<dein-service>/internal/run-agent -H "Authorization: Bearer <AGENT_TRIGGER_TOKEN>"

Intervall: z.B. alle 30–60 Minuten.

5) Datenbank
SQLite (default)

Datei: instance/db.sqlite3

Wird automatisch angelegt/migriert.

Backup: Datei einfach kopieren (siehe unten).

Postgres (optional)

DATABASE_URL setzen und Codepfad auf Postgres aktivieren (die App unterstützt bereits psycopg2-Fallback).

Migrationen werden beim Start angelegt (simple schema).

6) Backup & Restore
Backup (PowerShell)
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
New-Item -ItemType Directory -Force -Path .\backups | Out-Null
Compress-Archive -Path * `
  -DestinationPath "backups\super-agent-$stamp.zip" `
  -CompressionLevel Optimal `
  -Force `
  -Exclude ".venv*", "__pycache__*", "*.pyc", "node_modules*", "dist*", "build*"

# zusätzlich wichtige Einzelteile
$dst = "backups\super-agent-$stamp"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item app.py $dst
Copy-Item .env.local $dst -ErrorAction SilentlyContinue
Copy-Item .env $dst -ErrorAction SilentlyContinue
Copy-Item -Recurse templates,static,agent,instance $dst -ErrorAction SilentlyContinue

Restore

ZIP entpacken, instance/db.sqlite3 zurücklegen, .env.local kopieren.

venv aktivieren, starten.

7) Git Workflow
git init        # falls noch nicht
git switch -c main


.gitignore anlegen:

.venv/
__pycache__/
*.pyc

.env
.env.local

instance/*.sqlite*
instance/*.db*

node_modules/
dist/
build/


Commit:

git add -A
git commit -m "stable: search, alerts, SMTP working"
git tag -a backup-$(date +%Y%m%d-%H%M) -m "stable point"


Push:

git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main --tags

8) Sicherheit & Best Practices

Secrets (API-Keys, SMTP, Tokens) niemals committen → nur als Render Env Vars / .env.local.

Lange zufällige Werte für SECRET_KEY und AGENT_TRIGGER_TOKEN.

/internal/run-agent ist privat (Bearer), nicht öffentlich verlinken.

Wenn möglich: HTTPS erzwingen (Render macht das für dich).

9) Troubleshooting
„E-Mail Versand fehlgeschlagen (SMTP prüfen)“

/_health/diag aufrufen – zeigt SMTP-Status.

Prüfen:

SMTP_HOST/PORT korrekt?

TLS/SSL richtig? (SMTP_USE_TLS=1 oder SMTP_USE_SSL=1, nicht beides)

SMTP_USER/PASS korrekt? Reicht evtl. App-Passwort (z.B. bei Gmail)?

SMTP_FROM valide Adresse/Domain.

Test: Button „Jetzt E-Mail testen“ in der UI.

eBay liefert keine Ergebnisse / Auth-Fehler

/_debug/ebay prüfen (Token gecached? gültig?)

EBAY_CLIENT_ID/SECRET korrekt? LIVE_SEARCH=1?

EBAY_GLOBAL_ID (z.B. EBAY-DE) passt zu deinem Marktplatz.

Alerts werden „nicht neu“ erkannt

Cooldown: NOTIFY_COOLDOWN_MINUTES

De-Duping nutzt Tabelle alert_seen (Key u.a. item_id/url/title).

10) Projektstruktur (Kurz)
.
├─ app.py                 # Flask-App (UI + Endpoints)
├─ agent.py               # Agent-Runner (Cron/HTTP)
├─ templates/             # Jinja Templates
├─ static/                # CSS/JS/Assets
├─ instance/db.sqlite3    # lokale DB (nicht commiten)
├─ .env.local             # lokale Env (NICHT commiten)
└─ requirements.txt       # (empfohlen)

11) Lizenz / Hinweise

eBay/PA-API Nutzungsbedingungen beachten.

Affiliate-Parameter nur nutzen, wenn Richtlinien konform.

Fragen oder willst du, dass ich eine passende r