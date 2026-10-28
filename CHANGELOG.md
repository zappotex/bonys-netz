# Änderungen

Alle wichtigen Änderungen am Bony-Netz.

## 0.2.1 – Sicherheit und Datenschutz (Durchsicht vor 1.0)

### Server (Zentrale 0.2.1)
- **Kursleiter erreicht nur noch die Hilfe-Funktion:** Die Netzregel eines laufenden Kurses gibt nur Port 5959 der
  gewählten Agent-PCs frei, nicht mehr alle Ports (vorher auch SSH mit Passwort).
- **Rollen nicht mehr fälschbar:** Eintrittskarten erlauben kein `canUpdateOwnMetadata` mehr; `/eintritt` liefert
  `kursleiter_identitaet`, an der die App den Kursleiter erkennt.
- **Zugänge schließen zuverlässig:** Karten gelten 15 Minuten (`EINTRITTSKARTE_MINUTEN`, vorher 6 Stunden), Räume legt
  nur die Zentrale an (`room.auto_create: false` – `install.sh` trägt es auch in vorhandene `livekit.yaml` ein), Pause
  löscht den Raum, Entfernen und Austreten werfen sofort hinaus. Netzregeln werden nicht mehr unter der
  Datenbanksperre gesetzt; scheitert Headscale, holt ein Abgleich alle 30 s den Stand nach (`/health` →
  `regeln_aktuell`).
- **Datenschutz:** kein Zugriffsprotokoll mehr (IP-Adressen standen mit Pfad im Docker-Log), Container-Protokolle aller
  Dienste begrenzt (3 × 5 MB), IP-Hash nur noch 24 Stunden in eigener Tabelle (vorhandene Hashes werden geleert),
  Teilnahmen werden beim Kursende gelöscht, Kurse enden 7 Tage nach Ablauf des Kurscodes von selbst, beendete Kurse
  werden nach 30 Tagen gelöscht.
- Keine öffentliche Schnittstellen-Doku mehr (`/docs`, `/redoc`, `/openapi.json`).

### Baustein `bony_netz` 0.2.1
- Das Instanz-Token folgt keiner Weiterleitung mehr und geht nie über unverschlüsseltes `http://` (außer an
  `localhost`).

## 0.2.0 – Kurspakete in Kursen

### Server (Zentrale 0.2.0)
- **Kurspaket zum Kurs:** Der Kursleiter lädt eine `.bonyspaket`-Datei hoch (`PUT /kurse/{id}/kurspaket`, höchstens
  `MAX_KURSPAKET_MB`, Standard 25 MB), die Teilnehmer holen sie (`GET`). Gespeichert in `/data/kurspakete/`,
  gelöscht beim Beenden des Kurses und mit der Instanz des Kursleiters.
- **Fortschritt:** Teilnehmer melden nur Lektion und „geschafft / noch nicht“ (`POST /kurse/{id}/fortschritt`);
  der Kursleiter sieht das je Teilnehmer, solange der Kurs läuft.
- Neue Tabellen `kurspakete` und `fortschritt` entstehen beim Start von selbst – bestehende Daten bleiben.

### Baustein `bony_netz` 0.2.0
- `kurspaket_hochladen`, `kurspaket_entfernen`, `kurspaket_holen`, `fortschritt_melden`.

## 0.1.0 – Erste Version

### Server
- **Installationsskript** `server/install.sh` für Debian und Ubuntu: fragt drei Adressen ab,
  installiert bei Bedarf Docker aus der offiziellen Paketquelle, erzeugt alle Schlüssel und
  startet Headscale, LiveKit, Zentrale und Caddy. Kann beliebig oft laufen, ohne Schlüssel,
  Daten oder eigene Einstellungen zu verlieren.
- **Netz** mit Headscale 0.29.5: Jede Instanz erreicht nur ihre eigenen Agent-PCs.
  Eigenes Relay auf dem Server, kein Kontakt zu Servern von Tailscale.
- **Zentrale** (Anmeldedienst): Instanzen ohne Konten, einmal nutzbare Geräteschlüssel,
  Kursleiter-Codes, Kurse mit Kurscode, Eintrittskarten für die Kursräume. Netzregeln für
  laufende Kurse: Der Kursleiter erreicht nur den gewählten Agent-PC jedes Teilnehmers.
- **Kursräume** mit LiveKit: Bildschirm, Ton, Kamera, Chat.
- **Grenzen gegen Missbrauch**, einstellbar in `zentrale-grenzen.env`.
- **Verwaltung** über `python -m app.admin`.

### Baustein `bony_netz` 0.1.0
- Client der Zentrale, nur Python-Standardbibliothek.
- Gemeinsame Anmeldung für Bony's Agents und Bony's VPN (`konto.json`).
- Beitrittsskript für Agent-PCs: Tailscale aus der offiziellen Paketquelle.
