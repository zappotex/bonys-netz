# Schnittstelle der Zentrale

Basisadresse: `https://zentrale.example.de/api/v1`
Alle Antworten sind JSON. Fehler kommen als `{"detail": "Text für den Nutzer"}`.

Angemeldete Aufrufe schicken das Instanz-Token im Kopf:
`Authorization: Bearer bz_...`

## Ablauf in der App

1. `GET /info` – Server prüfen, `login_server` und `kursraum_url` merken.
2. `POST /instanzen` – einmalig. `instanz_id` und `token` sicher speichern
   (Linux: Schlüsselbund oder Datei mit Rechten 600).
3. Für jeden neuen Agenten-PC: `POST /geraete/schluessel`, dann im Agenten-PC
   `tailscale up --login-server <login_server> --authkey <schluessel> --hostname <name>`.

## Allgemein

| Methode | Pfad | Anmeldung | Zweck |
|---|---|---|---|
| GET | `/info` | nein | Servername, Version, `login_server`, `kursraum_url`, Grenzen |
| GET | `/health` (ohne `/api/v1`) | nein | Zustand der Zentrale |

## Instanz

| Methode | Pfad | Antwort / Hinweis |
|---|---|---|
| POST | `/instanzen` | `201 {instanz_id, token, login_server}` – `429` bei zu vielen Anmeldungen vom selben Anschluss |
| GET | `/instanz` | `{instanz_id, ist_kursleiter, erstellt}` |
| DELETE | `/instanz` | `204` – löscht Instanz, alle Agenten-PCs, eigene Kurse und Teilnahmen |
| POST | `/instanz/kursleiter` | Body `{code}` – Kursleiter-Code einlösen, `400` wenn ungültig |

## Geräte (Agenten-PCs)

| Methode | Pfad | Antwort / Hinweis |
|---|---|---|
| GET | `/geraete` | `[{geraet_id, name, ip, online, zuletzt_gesehen}]` |
| POST | `/geraete/schluessel` | `{schluessel, login_server, gueltig_minuten}` – einmal nutzbar; `409` wenn die Gerätegrenze erreicht ist |
| DELETE | `/geraete/{geraet_id}` | `204` – entfernt das Gerät aus dem Netz und aus Kursen |

## Kurse – Kursleiter

Nur für freigeschaltete Instanzen, sonst `403`.

| Methode | Pfad | Antwort / Hinweis |
|---|---|---|
| POST | `/kurse` | Body `{name, kursleiter_name, code_gueltig_tage?}` → Kurs mit `code` (z. B. `K7QX-M3PA`), Status `offen` |
| GET | `/kurse/geleitet?alle=false` | Liste eigener Kurse mit Teilnehmern |
| POST | `/kurse/{kurs_id}/status` | Body `{status}`: `laeuft`, `pausiert` oder `beendet` |
| DELETE | `/kurse/{kurs_id}/teilnehmer/{instanz_id}` | `204` – Teilnehmer entfernen |

Ein Kurs-Objekt:

```json
{
  "kurs_id": "k3f9a...", "name": "Einführung Hermes", "kursleiter_name": "Bony",
  "status": "laeuft", "raum": "k3f9a...", "code": "K7QX-M3PA",
  "code_gueltig_bis": 1761000000, "erstellt": 1760000000,
  "teilnehmer": [
    {"instanz_id": "i8c2...", "anzeigename": "Anna", "geraet_name": "agent-1",
     "geraet_ip": "100.64.0.7", "beigetreten": 1760000100}
  ]
}
```

`geraet_ip` ist die Adresse, über die der Kursleiter den Agenten-PC des Teilnehmers für
die Hilfe-Funktion erreicht. **Nur solange der Kurs den Status `laeuft` hat.**

## Kurse – Teilnehmer

| Methode | Pfad | Antwort / Hinweis |
|---|---|---|
| POST | `/kurse/beitreten` | Body `{code, geraet_id, anzeigename}` – Groß-/Kleinschreibung und Bindestrich egal. Erneuter Beitritt ersetzt Gerät und Namen |
| GET | `/kurse/teilnahmen` | eigene aktive Kurse mit `mein_geraet_id`, ohne Kurscode |
| DELETE | `/kurse/{kurs_id}/teilnahme` | `204` – Kurs verlassen |

## Kursraum

| Methode | Pfad | Antwort / Hinweis |
|---|---|---|
| POST | `/kurse/{kurs_id}/eintritt` | `{kursraum_url, raum, eintrittskarte, rolle}` – nur bei Status `laeuft`, sonst `409` |

Mit `kursraum_url` und `eintrittskarte` verbindet sich die App über das LiveKit-SDK
(z. B. `livekit-client` im eingebetteten Browserfenster).

Rechte der Eintrittskarte:

| | Kursleiter | Teilnehmer |
|---|---|---|
| Mikrofon, Kamera | ja | ja (die App startet sie stumm/aus) |
| Bildschirm teilen | ja | nein |
| Chat, Handzeichen (Data-Nachrichten) | ja | ja |
| Teilnehmer stummschalten / entfernen | ja (`roomAdmin`) | nein |

Die Rolle steht zusätzlich in den Metadaten des Teilnehmers: `{"rolle": "kursleiter"}`.

## Statuswerte eines Kurses

| Status | Beitritt mit Code | Netzzugang Kursleiter → Teilnehmer | Kursraum |
|---|---|---|---|
| `offen` | ja | nein | nein |
| `laeuft` | ja | **ja** | ja |
| `pausiert` | ja | nein | nein |
| `beendet` | nein | nein | Raum wird gelöscht |
