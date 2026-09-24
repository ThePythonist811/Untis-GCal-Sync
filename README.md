# untis-gcal-sync

Einweg-Sync: WebUntis Stundenplan -> Google Kalender (via GitHub Actions, 3x pro Werktag).
Aenderungen im Google-Kalender an Untis-Terminen werden beim naechsten Lauf ueberschrieben.
Nur Events mit `extendedProperties.private.src=untis` werden angefasst; manuelle Termine bleiben unberuehrt.

## 1. Lokal testen (zuerst!)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # ausfuellen (Google-Werte fuer Schritt 1a/1b nicht noetig)
set -a; source .env; set +a

python sync.py --raw       # Lehrer-Test: "teacher names present: True/False"
python sync.py --dry-run   # zeigt die Events, die entstehen wuerden
```

- `teacher names present: False` -> Lehrer kommen nicht inline. Der Sync laeuft trotzdem, nur ohne Lehrer.
- Bei Login-Fehler: NICHT wiederholt probieren (Account-Sperre). Zugangsdaten pruefen.

## 2. Google einrichten

1. Google Cloud Console: Projekt anlegen, Google Calendar API aktivieren.
2. Dienstkonto anlegen, JSON-Key erzeugen (nicht committen).
3. Ziel-Kalender in Google Kalender mit der Dienstkonto-Mail teilen: "Änderungen an Terminen vornehmen".
4. Kalender-ID kopieren (Kalendereinstellungen, "Kalender integrieren"). Empfehlung: eigener Test-Kalender.

Lokal komplett testen: `GOOGLE_SERVICE_ACCOUNT_JSON` in `.env` als eine Zeile mit dem JSON-Inhalt setzen, dann `python sync.py`.

## 3. Repo + Secrets (siehe setup.sh)

```bash
bash setup.sh
```

Braucht die GitHub CLI (`gh auth login`). Repo wird PRIVAT angelegt.

## 4. Betrieb

- Actions-Tab: Lauf manuell starten ("Run workflow").
- Cron: 3x werktags (UTC, siehe `.github/workflows/sync.yml`). Verbrauch ca. 66-130 von 2000 Free-Minuten pro Monat.
- Fehlgeschlagene Runs: GitHub schickt eine Mail.
- Sicherheitsnetz: liefert Untis 0 Stunden, werden keine Events geloescht.
