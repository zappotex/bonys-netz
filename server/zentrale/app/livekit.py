# SPDX-License-Identifier: GPL-3.0-or-later
"""Eintrittskarten (Zugangstoken) und Raumverwaltung für LiveKit.

Räume legt nur die Zentrale an (``room.auto_create: false`` in livekit.yaml): beim Start eines Kurses bzw. beim
Eintritt, gelöscht bei Pause und Ende – eine alte Karte öffnet dann keinen Raum mehr. Karten gelten nur kurz; LiveKit
erneuert sie verbundenen Teilnehmern selbst.
"""

import json
import time

import httpx
import jwt


class LiveKit:
    def __init__(self, url: str, key: str, secret: str) -> None:
        self._url = url.rstrip("/")
        self._key = key
        self._secret = secret

    def _token(self, video: dict, identitaet: str = "zentrale", name: str = "",
               metadaten: dict | None = None, gueltig_sekunden: int = 600) -> str:
        jetzt = int(time.time())
        daten = {
            "iss": self._key,
            "sub": identitaet,
            "nbf": jetzt - 10,
            "exp": jetzt + gueltig_sekunden,
            "video": video,
        }
        if name:
            daten["name"] = name
        if metadaten is not None:
            daten["metadata"] = json.dumps(metadaten)
        return jwt.encode(daten, self._secret, algorithm="HS256")

    def eintrittskarte(self, raum: str, identitaet: str, name: str,
                       kursleiter: bool, minuten: int) -> str:
        quellen = ["microphone", "camera"]
        if kursleiter:
            quellen += ["screen_share", "screen_share_audio"]
        video = {
            "room": raum,
            "roomJoin": True,
            "canSubscribe": True,
            "canPublish": True,
            "canPublishData": True,          # Chat und Handzeichen
            "canPublishSources": quellen,
            # Kein canUpdateOwnMetadata: Name und Rolle stehen fest in der Karte. Sonst könnte sich ein Teilnehmer
            # selbst die Rolle „kursleiter“ geben (die App erkennt den Kursleiter zusätzlich an seiner Identität).
        }
        if kursleiter:
            video["roomAdmin"] = True        # Stummschalten, Teilnehmer entfernen
        return self._token(
            video,
            identitaet=identitaet,
            name=name,
            metadaten={"rolle": "kursleiter" if kursleiter else "teilnehmer"},
            gueltig_sekunden=minuten * 60,
        )

    def _dienst(self, methode: str, daten: dict, video: dict) -> bool:
        """Twirp-Aufruf an den RoomService. False, wenn LiveKit nicht erreichbar ist oder ablehnt."""
        try:
            antwort = httpx.post(
                f"{self._url}/twirp/livekit.RoomService/{methode}",
                headers={"Authorization": f"Bearer {self._token(video)}"},
                json=daten,
                timeout=10,
            )
        except httpx.HTTPError:
            return False
        return antwort.status_code < 400

    def raum_anlegen(self, raum: str) -> bool:
        """Raum anlegen (gibt es ihn schon, bleibt er, wie er ist)."""
        return self._dienst("CreateRoom", {"name": raum, "empty_timeout": 300}, {"roomCreate": True})

    def raum_loeschen(self, raum: str) -> None:
        # Ein Raum, der nicht mehr existiert oder nicht erreichbar ist, ist kein Grund, Pause oder Kursende
        # scheitern zu lassen. Ohne auto_create kann ihn danach niemand neu öffnen.
        self._dienst("DeleteRoom", {"room": raum}, {"roomCreate": True})

    def teilnehmer_entfernen(self, raum: str, identitaet: str) -> None:
        """Teilnehmer sofort aus dem Raum werfen (aus dem Kurs entfernt oder ausgetreten)."""
        self._dienst("RemoveParticipant", {"room": raum, "identity": identitaet},
                     {"room": raum, "roomAdmin": True})
