# Kleinanzeigen: zentraler Abschalter

## Konfiguration

Die aktive Suchfunktion in `services/kleinanzeigen.py` prüft vor jeder Suche
`ENABLE_KLEINANZEIGEN` über `is_kleinanzeigen_enabled()`.

| Wert | Verhalten |
| --- | --- |
| `1` | Suche freigegeben; bestehende HTTP- und Fehlerbehandlung bleibt aktiv |
| `0` | Quelle pausiert |
| Fehlend oder jeder andere Wert, auch `true` oder `1 ` | Quelle pausiert |

Bei Pause wird `SOURCE_DISABLED` / `source_disabled` mit leerer Ergebnisliste,
`reason=disabled_by_config`, ohne HTTP-Status und mit `retryable=False`
zurückgegeben. Es wird keine Kleinanzeigen-HTTP-Session erstellt.

Für eine spätere Pause auf Render `ENABLE_KLEINANZEIGEN=0` in **allen betroffenen
Web- und Cron-/Worker-Diensten** konfigurieren. Zur Wiederaktivierung dort
ausdrücklich `1` setzen. Laufende Prozesse müssen die neue Umgebung erhalten;
eine Änderung in einem Webdienst ändert nicht automatisch einen separaten Worker.
Lokale `.env`-Werte können durch bestehende `load_dotenv()`-Aufrufe eingelesen
werden. Für eine eindeutige betriebliche Pause deshalb explizit `0` setzen.

Der Schalter verändert keine Datenbank und keine individuelle Alert-Aktivierung.
Es gibt keinen automatischen Wechsel zur E-Mail-Verarbeitung.

## Geschützte Pfade

- `/search`: `routes/search.py` → `services/kleinanzeigen_backend.py` →
  `services/kleinanzeigen.py`. eBay bleibt bei kombinierter Suche aktiv.
- `routes/alerts.py::alert_results()`: derselbe Backend-/Suchpfad.
- `/cron/check-alerts`, `/debug/run-alerts` und der Direktstart von
  `alert_checker.py`: `process_single_alert()` überspringt pausierte
  Kleinanzeigen-Alerts vor der Nutzerabfrage.
- Der zusätzliche Wrapper `app.py::search_kleinanzeigen()`,
  `services/search_integration.py::merge_all_marketplaces()` und
  `scripts/run_kleinanzeigen_test.py` verwenden ebenfalls das zentrale Suchmodul.

Pausierte Cron-Alerts verändern weder `last_run_ts` noch `alert_seen`,
`is_active` oder Benachrichtigungen. Sie werden nicht als Fehler oder
abgeschlossene Suchprüfung gezählt. Das gilt auch für neue Alerts mit
`last_run_ts=0`; nach Freigabe bleibt die bestehende Erstlaufbehandlung erhalten.

Die Intervallberechnung bleibt unverändert: standardmäßig Free 30 Minuten,
Pro/Premium drei Minuten und `ALERT_GRACE_SECONDS=20` als vorhandene Toleranz.
Die Quelle wird damit nicht automatisch nach einer bestimmten Zeit reaktiviert.

## Oberfläche

Einzel-/Kombinationssuche, Alert-Details, beide erreichbaren Verwaltungsansichten
und Speichermeldungen weisen auf die Quellenpause hin. Gespeicherte Suchaufträge
bleiben erhalten. Pausierte Alerts erhalten keine Anzeige eines nächsten Checks.
Die zusätzliche Ansicht mit gespeicherten Ergebnissen in `app.py` kennzeichnet
diese ausdrücklich als historische Ergebnisse.

## Unabhängige Test- und Legacy-Zugriffe

Diese Skripte wurden nicht verändert und sind nicht vom zentralen Schalter
vollständig abgesichert. Es wurde kein Aufruf aus den aktiven
Web-/Alert-Hauptpfaden gefunden:

- `ka_test.py`: direkter `requests.get()` bereits beim Import.
- `kleinanzeigen_scraper.py::fetch_rss_feed()`: direkter RSS-Abruf mit
  `feedparser.parse(url)`; eigener Dauerlauf, außerdem von
  `telegram_notifier.py` referenziert.
- `services/parallel_search.py`: die Suchfunktionen berücksichtigen bereits
  `ENABLE_KLEINANZEIGEN == "1"`. Der eigenständige Benchmark unter
  `__main__` setzt die Variable jedoch selbst auf `1`. Sein
  Kleinanzeigen-Worker verweist zudem auf eine nicht vorhandene Suchfunktion
  im E-Mail-Parser. Dieser separate Benchmark wurde weder repariert noch gestartet.

Diese unabhängigen Skripte bei einer gewünschten globalen Pause nicht starten
oder importieren. Ob sie außerhalb des Repository-Hauptpfads als eigene Dienste
laufen, lässt sich aus dem lokalen Code nicht feststellen.

## Offline-Tests

Mit der vorhandenen virtuellen Umgebung unter PowerShell:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
.\.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider
```

`tests/conftest.py` ersetzt Datenbank-, Mail- und Telegram-Grenzen bereits vor
der Testsammlung und sperrt echte HTTP-, Socket- und Datenbankzugriffe.
Das ist notwendig, weil `database.py` beim Import Tabellen initialisiert.
Die Tests laden keine lokalen `.env`-Dateien. HTTP-Antworten, Cursor und
Versandergebnisse werden simuliert; die Anwendung wird nicht gestartet.

Nur die isolierte Suite unter `tests/` ausführen. Mehrere unabhängige
Testskripte im Projektwurzelverzeichnis führen echte Zugriffe aus.

Der Sprint beinhaltet keine Migration und keine Änderungen am E-Mail-Importer,
an Stripe, Telegram oder Postmark. Commit, Push und Deployment erfolgen separat
nach ausdrücklicher Freigabe.
