# ebay-agent-cockpit – Mini-Runbook
**Stand:** stabil – Mails laufen**  
**Zuletzt aktualisiert:** 2025-08-31 07:16

---

## 1) Repos & Branches

- **Remote:** `origin` → https://github.com/LennyCollie/ebay-agent-cockpit.git  
- **Arbeits-Branch:** `staging` (mit Render verbunden)

### Typische Git-Befehle (PowerShell / CMD)

```powershell
# Status
git status

# Änderungen hinzufügen & committen
git add -A
git commit -m "feat/fix: <kurzer beschreibender Text>"

# Auf staging pushen
git push origin staging

# Neueste Remote-Änderungen holen (falls Push wegen non-fast-forward abgelehnt wird)
git fetch origin
git pull --rebase origin staging
# Danach erneut pushen
git push origin staging
```

### Stabilen Stand taggen (Rollback-Anker)
```powershell
git tag -a v0.9.0 -m "stable search + mail"
git push origin v0.9.0
```

### Rollback (lokal)
```powershell
git checkout staging
git reset --hard v0.9.0
git push origin staging --force   # nur wenn wirklich nötig
```
> **Hinweis:** Auf Render lieber die gewünschte Commit-Version wählen, statt force-push.

---

## 2) Umgebung / `.env.local` (Schlüssel)

> **Gmail-Hinweis:** Für Gmail Port **587** + **TLS=1, SSL=0**. Port 465 nur mit **SSL=1, TLS=0** – das machte Probleme.

```dotenv
# Flask
SECRET_KEY=irgendwas-langes

# eBay
EBAY_CLIENT_ID=...
EBAY_CLIENT_SECRET=...
EBAY_SCOPES=https://api.ebay.com/oauth/api_scope
EBAY_GLOBAL_ID=EBAY-DE
LIVE_SEARCH=1

# E-Mail (Gmail-Beispiel, Port 587)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=dein.name@gmail.com
SMTP_PASS=app-spezifisches-passwort
SMTP_FROM="Agent <dein.name@gmail.com>"
SMTP_USE_TLS=1
SMTP_USE_SSL=0

# Alerts
NOTIFY_COOLDOWN_MINUTES=120
NOTIFY_MAX_ITEMS_PER_MAIL=20

# DB
DB_PATH=sqlite:///instance/db.sqlite3

# HTTP-Agent Trigger
AGENT_TRIGGER_TOKEN=ein_langes_random_token

# (Optional) Amazon – standardmäßig AUS
AMZ_ENABLED=0
AMZ_ACCESS_KEY_ID=
AMZ_SECRET_ACCESS_KEY=
AMZ_PARTNER_TAG=
AMZ_COUNTRY=DE

# Plausible (optional)
PLAUSIBLE_DOMAIN=
```

---

## 3) Starten (lokal)

```powershell
# venv anlegen (falls fehlt)
python -m venv .venv

# aktivieren
.\.venv\Scripts\Activate.ps1

# Abhängigkeiten
pip install -U pip wheel
pip install -r requirements.txt

# starten
$env:FLASK_DEBUG="1"
python app.py
```

Wenn `.venv` „kaputt“:  
`pip freeze > req.lock`, dann `.venv` löschen, neu anlegen, `pip install -r requirements.txt`.

---

## 4) Render-Service

- **URL:** https://ebay-agent-heartbeat.onrender.com  
- **Health:** `/healthz`  
- **Debug:** `/_debug/ebay`, `/_debug/amazon`, `/debug`

### Agent (Cron) – interner Trigger
- **Endpoint:** `POST /internal/run-agent`  
- **Auth:** `Authorization: Bearer ${AGENT_TRIGGER_TOKEN}`

**Render Cronjob (Beispiel alle 15 Min):**
```bash
curl -sS -X POST   -H "Authorization: Bearer ${AGENT_TRIGGER_TOKEN}"   https://ebay-agent-heartbeat.onrender.com/internal/run-agent
```

**Logs ansehen:** Render-Dashboard → Service → Logs (Live tail).

---

## 5) Funktionen (Kurz)

- **Suche:** `/search` (`q1…q3`, `price_min/max`, `sort=best|newly|price_asc|price_desc`, `condition=USED|NEW` …)  
- **Alarm speichern:** `POST /alerts/subscribe` (Logged-in)  
- **Mail sofort testen:** `POST /alerts/send-now`  
- **De-Duping & Cooldown:** pro User+Suche+Quelle (ebay/amazon) werden Items nur nach Cooldown erneut gemailt.

---

## 6) Backups

**App-Datei (schneller Snapshot)**
```powershell
$TS = Get-Date -Format 'yyyyMMdd-HHmm'
Copy-Item app.py "app.py.bak-$TS"
```

**SQLite-DB**
```powershell
Copy-Item .\instance\db.sqlite3 ".\backups\db-$TS.sqlite3"
```

---

## 7) Häufige Fehler & schnelle Fixes

### Mails kommen nicht an / keine Fehler im Log
- Prüfe `/debug` → `SMTP_*` Werte.
- Bei Gmail: **App-Passwort** verwenden (2FA nötig).
- **Port/Flags:** 587 + TLS=1 + SSL=0 (empfohlen). 465 nur mit SSL=1 + TLS=0.
- In den Render-Logs erscheint beim Senden eine Zeile wie:  
  `[mail] sent via smtp.gmail.com:587 tls=True ssl=False`

### Connection reset by peer beim Mailversand
- Meist TLS/SSL-Mismatch oder kurzzeitiges Provider-Problem → EHLO+Retry eingebaut (stabilisiert).

### eBay 400 „Bad Request“
- Filter als Browse-API-Filter senden: `price:[<min>..<max>]`, `priceCurrency:EUR`, `conditions:{USED,NEW}`
- **Sort:** `price`, `-price` oder `newlyListed` – keine UI-Werte an die API schicken.
- Leere Min/Max als leere Strings zulassen: `price:[..220]` ist ok.

### IndentationError (`app.py`)
- Entsteht durch Tabs/Mix. Komplett zu Spaces normalisieren:  
  VS Code: *Convert Indentation to Spaces*
- PowerShell quick-fix (vorsichtig!):
  ```powershell
  (Get-Content app.py) -replace "	"," " | Set-Content app.py
  ```
- Vor Push testweise kompilieren:
  ```powershell
  python -m py_compile app.py
  ```

### `.venv`/Pfad kaputt (Windows)
- Aktivierung: `.\.venv\Scripts\Activate.ps1`  
- Wenn der Ordner fehlt: neu erzeugen und Pakete installieren (s.o.).

---

## 8) Tests (Smoke)

- `/healthz` → ok  
- `/_debug/ebay` → `configured=true`, `token_valid_for_s>0`  
- `/search` (z. B. `q1=iPhone 11`, Filter setzen) → Ergebnisse da  
- „Jetzt E-Mail testen“ → Erfolgsmeldung + Log-Zeile `[mail] sent via ...`  
- **Agent Trigger (Render Cron)** → Logs: `agent start run / alerts_emailed=n`

---

## 9) Nächste sinnvolle Schritte

- DB-Backup automatisieren (wöchentliches Kopieren der SQLite)  
- ENV-Rotation (SMTP-Pass & Tokens alle 90 Tage)  
- README/Runbook ins Repo (diese Notizen als `RUNBOOK.md`)  
- Tagging bei stabilen Deploys (z. B. `v0.9.1`, `v0.9.2` …)  
- Optionale Features später: Amazon PA-API wieder einschalten (`AMZ_ENABLED=1`) erst nach funktionierender Schlüsselprüfung.

---

## 10) Kurz-Cheatsheet (häufig genutzt)

```powershell
# Commit + Push
git add -A
git commit -m "fix: <beschreibung>"
git push origin staging

# Pull falls non-fast-forward
git fetch origin
git pull --rebase origin staging
git push origin staging

# App lokal
.\.venv\Scripts\Activate.ps1
python app.py

# Health / Debug (Render)
https://ebay-agent-heartbeat.onrender.com/healthz
https://ebay-agent-heartbeat.onrender.com/_debug/ebay
https://ebay-agent-heartbeat.onrender.com/debug
```