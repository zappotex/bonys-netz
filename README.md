# Bony-Netz

**Ein eigenes, sicheres Netz für die Agent-PCs von [Bony's Agents](https://github.com/zappotex/BonysAgents) –
mit Kursräumen für Schulungen über das Internet.**

Freie Software unter GPL-3.0-or-later. Videos und Anleitungen: [YouTube @BonysAgents](https://www.youtube.com/@BonysAgents)

---

## Was ist das Bony-Netz?

Das Bony-Netz verbindet die Agent-PCs einer Bony's-Agents-Installation sicher miteinander –
egal, an welchem Ort und hinter welchem Router sie stehen. Dazu kommen Kursräume, in denen
ein Kursleiter seinen Bildschirm zeigt, spricht, per Kamera zu sehen ist und mit den
Teilnehmern chattet.

Es besteht aus zwei Teilen:

| Ordner | Inhalt |
|---|---|
| [`server/`](server) | Der Server: Installationsskript, Zentrale (Anmeldedienst) und Vorlagen |
| [`baustein/`](baustein) | `bony_netz` – der Python-Baustein, mit dem [Bony's Agents](https://github.com/zappotex/BonysAgents) und [Bony's VPN](https://github.com/zappotex/bonys-vpn) mit dem Server sprechen |

Die Schnittstelle zwischen beiden ist in [API.md](API.md) beschrieben.

### Was das Netz garantiert

- **Jede Instanz bleibt für sich.** Die Agent-PCs einer Bony's-Agents-Installation erreichen nur
  einander. Andere Instanzen sind nicht nur gesperrt, sondern unsichtbar.
- **Kurse öffnen genau eine Tür.** Solange ein Kurs läuft, erreicht der Kursleiter genau den
  einen Agent-PC, den ein Teilnehmer für den Kurs ausgewählt hat. Teilnehmer erreichen sich
  untereinander nie. Pausieren oder Beenden schließt die Tür sofort.
- **Ende-zu-Ende verschlüsselt.** Die Agent-PCs verbinden sich direkt per WireGuard. Der Server
  vermittelt nur und kann den Verkehr zwischen ihnen nicht mitlesen.
- **Sparsam mit Daten.** Keine Konten, keine E-Mail-Adressen. Gespeichert wird nur, was für
  Netz und Kurse nötig ist (siehe [Datenschutz](#datenschutz)).

### Aus welchen Programmen der Server besteht

Alles Open Source, alles in Docker:

| Programm | Aufgabe |
|---|---|
| [Headscale](https://github.com/juanfont/headscale) | Zentrale des Netzes: verteilt Schlüssel und Regeln, eingebautes Relay für schwierige Router |
| [LiveKit](https://github.com/livekit/livekit) | Kursräume mit Bildschirm, Ton, Kamera und Chat |
| Zentrale (dieses Projekt) | Anmeldedienst für die Apps: Instanzen, Agent-PCs, Kurse, Eintrittskarten |
| [Caddy](https://github.com/caddyserver/caddy) | HTTPS mit automatischen Zertifikaten |

---

## Den öffentlichen Server nutzen

In Bony's Agents unter **Menü → Bony-Netz …** ist `https://zentrale.bony23.de` voreingestellt.
Schalter an, „Instanz anlegen“ – fertig. Kursleiter erhalten einen Kursleiter-Code von Bony.

## Eigenen Server aufsetzen

Wer unabhängig sein will, betreibt seinen eigenen Server. Das dauert etwa 15 Minuten.

### Du brauchst

- einen Server mit **Debian 12/13** oder **Ubuntu 24.04** und öffentlicher IPv4-Adresse –
  1 CPU und 1 GB RAM reichen für den Anfang
- **keinen** vorinstallierten Webserver oder Verwaltungspanel wie Plesk (Ports 80 und 443 müssen frei sein)
- eine Domain mit drei **A-Einträgen** auf die IP des Servers, zum Beispiel
  `vpn.example.de`, `kurs.example.de` und `zentrale.example.de`
- diese Ports offen, auch in der Firewall deines Anbieters:

  | Port | Wofür |
  |---|---|
  | 80/tcp, 443/tcp | Zertifikate und HTTPS |
  | 3478/udp | Netz: Geräte finden sich gegenseitig |
  | 7881/tcp, 7882/udp | Kursräume: Bild und Ton |

### Installation

```bash
git clone https://github.com/zappotex/bonys-netz.git
cd bonys-netz/server
sudo ./install.sh
```

Das Skript fragt nach den drei Adressen, installiert bei Bedarf Docker aus der offiziellen
Paketquelle, erzeugt alle Schlüssel und startet die Dienste. Am Ende zeigt es, ob alles
erreichbar ist.

In Bony's Agents und Bony's VPN trägst du dann als Server ein: `https://zentrale.example.de`

### Aktualisieren

```bash
cd bonys-netz
git pull
cd server && sudo ./install.sh
```

Schlüssel, Datenbanken und eigene Einstellungen bleiben dabei erhalten.

### Verwaltung

Alle Befehle im Installationsordner `/opt/bonynet`:

```bash
# Kursleiter-Code erzeugen (einmal verwendbar)
docker compose exec zentrale python -m app.admin kursleiter-code "für Anna"

# Übersichten
docker compose exec zentrale python -m app.admin instanzen
docker compose exec zentrale python -m app.admin kurse
docker compose exec zentrale python -m app.admin kursleiter-codes

# Kursleiter-Rechte entziehen
docker compose exec zentrale python -m app.admin kursleiter-entziehen <instanz_id>

# Logs
docker compose logs --tail 50
```

### Grenzen gegen Missbrauch

In `/opt/bonynet/zentrale-grenzen.env`, danach `docker compose up -d zentrale`.
Die Datei bleibt bei Aktualisierungen erhalten.

| Einstellung | Standard | Bedeutung |
|---|---|---|
| `MAX_INSTANZEN_PRO_IP_TAG` | 3 | neue Instanzen pro Internetanschluss und Tag – bei Schulungen vor Ort höher setzen |
| `MAX_GERAETE_PRO_INSTANZ` | 10 | Agent-PCs pro Instanz |
| `MAX_AKTIVE_KURSE_PRO_KURSLEITER` | 5 | gleichzeitig offene Kurse |
| `MAX_TEILNEHMER_PRO_KURS` | 49 | |
| `KURSCODE_GUELTIG_TAGE_MAX` | 60 | |

### Bekannte Einschränkungen

- Nur IPv4.
- Bildschirm teilen im Kursraum funktioniert beim Kursleiter unter Linux mit **Wayland**
  noch nicht (X11, Windows und macOS gehen). Teilnehmer sind nicht betroffen.

---

## Datenschutz

Die Zentrale speichert keine Namen, E-Mail-Adressen oder IP-Adressen von Instanzen.
IP-Adressen werden nur als nicht umkehrbarer Hash für die Grenze „Instanzen pro Tag“
verwendet. Gespeichert werden Kursnamen und die Anzeigenamen, die Teilnehmer beim Beitritt
selbst angeben. Headscale kennt die Gerätenamen und Netzadressen der Agent-PCs. Chat und
Kursraum werden nicht aufgezeichnet.

## Mitmachen

Siehe [CONTRIBUTING.md](CONTRIBUTING.md). Beiträge nur mit Zustimmung zur
[Beitragsvereinbarung (CLA)](CLA.md).

## Lizenz

Bony-Netz ist freie Software: GNU General Public License, Version 3 oder (nach deiner Wahl)
jede spätere Version – siehe [LICENSE](LICENSE). Die verwendeten Programme stehen unter
ihren eigenen Lizenzen, siehe [THIRD-PARTY-LICENSES](THIRD-PARTY-LICENSES).
