# Änderungen

Alle wichtigen Änderungen am Bony-Netz.

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
