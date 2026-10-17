# SPDX-License-Identifier: GPL-3.0-or-later
"""Eintrittskarten (Zugangstoken) und Raumverwaltung für LiveKit."""

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
                       kursleiter: bool, stunden: int) -> str:
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
            "canUpdateOwnMetadata": True,
        }
        if kursleiter:
            video["roomAdmin"] = True        # Stummschalten, Teilnehmer entfernen
        return self._token(
            video,
            identitaet=identitaet,
            name=name,
            metadaten={"rolle": "kursleiter" if kursleiter else "teilnehmer"},
            gueltig_sekunden=stunden * 3600,
        )

    def raum_loeschen(self, raum: str) -> None:
        token = self._token({"roomCreate": True})
        try:
            httpx.post(
                f"{self._url}/twirp/livekit.RoomService/DeleteRoom",
                headers={"Authorization": f"Bearer {token}"},
                json={"room": raum},
                timeout=10,
            )
        except httpx.HTTPError:
            # Ein Raum, der nicht mehr existiert oder nicht erreichbar ist, ist kein Grund
            # das Kursende scheitern zu lassen. LiveKit räumt leere Räume selbst auf.
            pass
