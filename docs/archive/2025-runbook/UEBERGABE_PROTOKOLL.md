# Übergabeprotokoll – „Runbook laden“
**Projekt/Service:** ebay-agent-cockpit  
**Stand:** stabil – Mails laufen  
**Datum:** 2025-08-31 07:16

---

## A) Kerndaten
- **Repo:** https://github.com/LennyCollie/ebay-agent-cockpit.git  
- **Branch:** `staging` (Render)  
- **Prod-URL:** https://ebay-agent-heartbeat.onrender.com  
- **Health:** `/healthz` • **Debug:** `/_debug/ebay`, `/_debug/amazon`, `/debug`

## B) Checkliste (Vorab)
- [ ] `.env.local` vollständig (SMTP 587 + TLS=1 + SSL=0)
- [ ] eBay OAuth konfiguriert (`EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, Scopes)
- [ ] `AGENT_TRIGGER_TOKEN` gesetzt (Render Cron)
- [ ] Backups-Pfad vorhanden (`/backups`)
- [ ] Tag als Rollback-Anker vorhanden (z. B. `v0.9.0`)

## C) Deploy/Operate (Kurz)
```powershell
git checkout staging
git pull --rebase origin staging
# prüfen & starten (lokal)
.\.venv\Scripts\Activate.ps1
python app.py
```
Render-Cron (alle 15 Min):
```bash
curl -sS -X POST -H "Authorization: Bearer ${AGENT_TRIGGER_TOKEN}" \
  https://ebay-agent-heartbeat.onrender.com/internal/run-agent
```

## D) Smoke-Tests
- `/healthz` → OK  
- `/_debug/ebay` → `configured=true`, `token_valid_for_s>0`  
- `/search?q1=iPhone 11` → Ergebnisse  
- `POST /alerts/send-now` → `[mail] sent via ...` im Log

## E) Rollback
```powershell
git checkout staging
git reset --hard v0.9.0
git push origin staging --force   # nur wenn unbedingt nötig
```
> Besser: auf Render gezielt Commit-Version auswählen.

## F) Häufige Fehler
- **Mail**: App-Passwort + TLS=1/SSL=0 auf 587; Log-Zeile bestätigt Versand  
- **eBay 400**: Filter/Sort exakt wie Browse-API (`price`, `-price`, `newlyListed`)  
- **IndentationError**: Tabs → Spaces (VS Code: Convert Indentation to Spaces)

## G) Nächste Schritte
- Wöchentliches SQLite-Backup automatisieren  
- Secrets/ENV alle 90 Tage rotieren  
- `RUNBOOK.md` ins Repo

---

**Abnahme Betrieb:** __________________  **Datum:** __________  
**Abgabe Engineering:** _______________  **Datum:** __________