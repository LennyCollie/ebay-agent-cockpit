---
name: "💄 Styling, Responsiveness & Performance Update (Render)"
about: "Render-Version auf Stand der lokalen Version bringen"
title: "💄 Styling & Performance – Render-Version verbessern"
labels: enhancement
assignees: ''
---

## 🎯 Ziel
Die Render-Version des Projekts **ebay-agent-cockpit** soll optisch & funktional an die lokale Version angeglichen werden – inkl. CSS-Migration, Responsive Design, schönerer Fehlermeldungen, Performance-Tuning und Sicherheit.

---

## ✅ To-Do-Checkliste

### 1. CSS & Frontend wiederherstellen
- [ ] Stylesheets aus altem lokalen Projekt ins `static/`-Verzeichnis kopieren
- [ ] HTML-Templates im `templates/`-Ordner so anpassen, dass sie auf diese CSS-Dateien verlinken

### 2. Responsive Design optimieren
- [ ] Bootstrap, Materialize oder eigenes CSS-Grid/Flexbox einbinden
- [ ] Mobile Ansicht des Dashboards testen & optimieren

### 3. Fehlermeldungen schöner gestalten
- [ ] Flash-Messages mit Bootstrap-Alerts stylen
- [ ] Eigene **404.html** erstellen
- [ ] Eigene **500.html** erstellen

### 4. Render Performance verbessern
- [ ] Keep-Alive-Mechanismus einrichten (Cronjob oder externer Ping-Dienst wie UptimeRobot)
- [ ] CSS- & JS-Dateien minifizieren (`flask-minify` oder Pre-Build)

### 5. Datenbank & Sicherheit
- [ ] Regelmäßige Backups der SQLite-Datei automatisieren
- [ ] `.gitignore` prüfen – sensible Dateien ausschließen (`instance/`, `.env`, SQLite-DB)

---

💡 **Hinweis:**
Nach Umsetzung dieser Punkte sollte das Projekt auf Render optisch und funktional identisch mit der lokalen Version sein – bei gleichzeitig besserer Performance und höherer Sicherheit.
