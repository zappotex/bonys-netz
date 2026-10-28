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
| PUT | `/kurse/{kurs_id}/kurspaket?paket_id=…&name=…&version=…&lektionen=…` | Rumpf: die `.bonyspaket`-Datei (`application/octet-stream`, ZIP, höchstens `MAX_KURSPAKET_MB`, Standard 25) → Kurs. Ersetzt ein vorhandenes Kurspaket; bei anderer `paket_id` verfällt der Fortschritt. `413` zu groß, `400` kein ZIP, `409` Kurs beendet |
| DELETE | `/kurse/{kurs_id}/kurspaket` | `204` – Kurspaket samt Fortschritt entfernen |

Ein Kurs-Objekt:

```json
{
  "kurs_id": "k3f9a...", "name": "Einführung Hermes", "kursleiter_name": "Bony",
  "status": "laeuft", "raum": "k3f9a...", "code": "K7QX-M3PA",
  "code_gueltig_bis": 1761000000, "erstellt": 1760000000,
  "kurspaket": {"paket_id": "einfuehrung-hermes-agent", "name": "Einführung in Hermes Agent",
                "version": "1.0.0", "lektionen": 9, "sha256": "…", "groesse": 30000,
                "hochgeladen": 1760000050},
  "teilnehmer": [
    {"instanz_id": "i8c2...", "anzeigename": "Anna", "geraet_name": "agent-1",
     "geraet_ip": "100.64.0.7", "beigetreten": 1760000100,
     "fortschritt": {"lektion": 3, "geschafft": true, "aktualisiert": 1760000900}}
  ]
}
```

`kurspaket` ist `null`, solange keins hochgeladen ist (steht auch in `/kurse/teilnahmen`). `fortschritt` ist `null`,
bis der Teilnehmer etwas meldet, und immer `null`, solange der Kurs nicht läuft (offen, pausiert, beendet); `geschafft` ist `true`, `false` oder
`null` (keine Prüfaufgabe bzw. noch nicht geprüft). Mehr speichert die Zentrale nicht – keine Inhalte aus dem
Agent-PC. Beim Beenden des Kurses werden Datei, Angaben und Fortschritt gelöscht.

`geraet_ip` ist die Adresse, über die der Kursleiter den Agenten-PC des Teilnehmers für
die Hilfe-Funktion erreicht. **Nur solange der Kurs den Status `laeuft` hat.**

## Kurse – Teilnehmer

| Methode | Pfad | Antwort / Hinweis |
|---|---|---|
| POST | `/kurse/beitreten` | Body `{code, geraet_id, anzeigename}` – Groß-/Kleinschreibung und Bindestrich egal. Erneuter Beitritt ersetzt Gerät und Namen |
| GET | `/kurse/teilnahmen` | eigene aktive Kurse mit `mein_geraet_id`, ohne Kurscode |
| DELETE | `/kurse/{kurs_id}/teilnahme` | `204` – Kurs verlassen (Fortschritt wird gelöscht) |
| GET | `/kurse/{kurs_id}/kurspaket` | die `.bonyspaket`-Datei (auch für den Kursleiter), Kopf `X-Kurspaket-Sha256`; `404` ohne Kurspaket, `409` Kurs beendet. Die App vergleicht die Prüfsumme mit `kurspaket.sha256` und prüft das Paket vollständig, bevor sie es übernimmt |
| POST | `/kurse/{kurs_id}/fortschritt` | Body `{lektion, geschafft?}` (Lektion ab 1, höchstens `kurspaket.lektionen`) → `204`; `409` ohne Kurspaket oder Kurs beendet |

## Kursraum

| Methode | Pfad | Antwort / Hinweis |
|---|---|---|
| POST | `/kurse/{kurs_id}/eintritt` | `{kursraum_url, raum, eintrittskarte, rolle, kursleiter_identitaet}` – nur bei Status `laeuft`, sonst `409` |

Mit `kursraum_url` und `eintrittskarte` verbindet sich die App über das LiveKit-SDK
(z. B. `livekit-client` im eingebetteten Browserfenster).

Rechte der Eintrittskarte:

| | Kursleiter | Teilnehmer |
|---|---|---|
| Mikrofon, Kamera | ja | ja (die App startet sie stumm/aus) |
| Bildschirm teilen | ja | nein |
| Chat, Handzeichen (Data-Nachrichten) | ja | ja |
| Teilnehmer stummschalten / entfernen | ja (`roomAdmin`) | nein |

| Eigene Metadaten oder Namen ändern | nein | nein |

Die Karte gilt `EINTRITTSKARTE_MINUTEN` (Standard 15) Minuten; LiveKit erneuert sie verbundenen Teilnehmern selbst,
zum Wiederverbinden holt die App eine neue. Räume legt nur die Zentrale an (`room.auto_create: false`): beim Start
und beim Eintritt; bei Pause und Ende löscht sie den Raum, beim Entfernen und Austreten wirft sie den Teilnehmer
sofort hinaus.

**Wer der Kursleiter ist**, erkennt die App ab 0.2.1 nur an `kursleiter_identitaet` (= Identität `sub` in seiner Karte).
Die Metadaten `{"rolle": …}` stehen weiter in der Karte, sind aber nur Anzeige – bis 0.2.0 konnte jeder Teilnehmer
sie selbst ändern.

## Statuswerte eines Kurses

| Status | Beitritt mit Code | Netzzugang Kursleiter → Teilnehmer | Kursraum |
|---|---|---|---|
| `offen` | ja | nein | nein |
| `laeuft` | ja | **ja – nur Port 5959 (Hilfe-Funktion)** | ja |
| `pausiert` | ja | nein | nein (Raum wird gelöscht) |
| `beendet` | nein | nein | Raum wird gelöscht; Teilnahmen werden gelöscht |

Ein Kurs endet von selbst `KURS_SELBST_BEENDEN_TAGE` (Standard 7) Tage nach Ablauf seines Kurscodes; beendete Kurse
werden nach `BEENDETE_KURSE_LOESCHEN_TAGE` (Standard 30) Tagen ganz gelöscht. Scheitert das Setzen der Netzregeln
(Headscale nicht erreichbar), antwortet die Zentrale `502`; der Hintergrund-Abgleich (alle 30 s) holt es nach.
`/health` meldet dann `regeln_aktuell: false`.
