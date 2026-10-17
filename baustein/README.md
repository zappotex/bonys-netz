# bony_netz – Baustein für Bony's Agents und Bony's VPN

Spricht mit der Zentrale eines Bony-Netz-Servers und merkt sich die Anmeldung.
Benutzt **nur die Python-Standardbibliothek** (Python 3.10 oder neuer).

## Einbinden

Den Ordner `bony_netz/` unverändert ins Projekt kopieren. Bony's Agents und Bony's VPN
enthalten jeweils eine Kopie; beide müssen auf demselben Stand sein
(Version in `bony_netz/__init__.py`).

## Kurzbeispiel

```python
from bony_netz import Konto, Zentrale, ZentraleFehler, NetzFehler

konto = Konto.laden()                    # gemeinsame Datei beider Apps
zentrale = Zentrale(konto.server, konto.token)

try:
    if not konto.angemeldet:
        konto.uebernehmen(zentrale.instanz_registrieren())
        konto.speichern()
    for geraet in zentrale.geraete():
        print(geraet["name"], geraet["ip"], geraet["online"])
except NetzFehler as e:
    print("Keine Verbindung:", e)          # Text kann direkt angezeigt werden
except ZentraleFehler as e:
    if e.anmeldung_ungueltig:              # Instanz wurde auf dem Server gelöscht
        konto.abmelden(); konto.speichern()
    print(e.meldung)
```

Alle Aufrufe blockieren bis zu 15 Sekunden – in einer Oberfläche nie im Hauptthread
aufrufen.

## Was drin ist

| Teil | Aufgabe |
|---|---|
| `Konto` | Serveradresse und Anmeldung, gespeichert in einer gemeinsamen Datei: Linux `~/.config/bonys-netz/konto.json`, Windows `%APPDATA%\BonysNetz\konto.json`, macOS `~/Library/Application Support/BonysNetz/konto.json` (unter Linux/macOS nur für den Benutzer lesbar) |
| `Zentrale` | Alle Aufrufe der [Schnittstelle](../API.md): Instanz, Geräte, Kurse, Eintrittskarten |
| `erstbeitritt_skript()` | Shell-Skript, das im Agent-PC beim ersten Start als root läuft: installiert Tailscale aus der offiziellen Paketquelle und tritt dem Netz bei |
| `geraetename()` | macht aus einem Anzeigenamen einen gültigen Netznamen |

## Regeln

- Das Instanz-Token nie anzeigen, loggen oder in Fehlermeldungen schreiben.
- Geräteschlüssel sind einmal nutzbar und 60 Minuten gültig – erst kurz vor dem ersten Start holen.
- Meldungen der Zentrale (`e.meldung`) sind für Nutzer geschrieben und können direkt angezeigt werden.

## Tests

```bash
cd baustein
python -m pytest -q
```

`tests/test_gegen_zentrale.py` spielt den kompletten Ablauf gegen eine **Test**-Zentrale
mit echtem Headscale durch; die nötigen Umgebungsvariablen stehen oben in der Datei.
Ohne sie wird der Test übersprungen.
