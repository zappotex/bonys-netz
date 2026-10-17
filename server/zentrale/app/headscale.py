# SPDX-License-Identifier: GPL-3.0-or-later
"""Schlanker Client für die REST-Schnittstelle von Headscale (/api/v1)."""

from datetime import datetime, timedelta, timezone

import httpx


class HeadscaleFehler(Exception):
    pass


def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Headscale:
    def __init__(self, url: str, api_key: str) -> None:
        self._client = httpx.Client(
            base_url=url.rstrip("/") + "/api/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )

    def _anfrage(self, methode: str, pfad: str, **kwargs) -> dict:
        try:
            antwort = self._client.request(methode, pfad, **kwargs)
        except httpx.HTTPError as e:
            raise HeadscaleFehler(f"Headscale nicht erreichbar: {e}") from e
        if antwort.status_code >= 400:
            raise HeadscaleFehler(f"Headscale {methode} {pfad}: {antwort.status_code} {antwort.text}")
        return antwort.json() if antwort.content else {}

    # --- Benutzer (= Instanzen) ---

    def benutzer_anlegen(self, name: str) -> dict:
        return self._anfrage("POST", "/user", json={"name": name})["user"]

    def benutzer_loeschen(self, user_id: str) -> None:
        self._anfrage("DELETE", f"/user/{user_id}")

    # --- Anmeldeschlüssel ---

    def anmeldeschluessel(self, user_id: str, minuten: int) -> str:
        ablauf = datetime.now(timezone.utc) + timedelta(minutes=minuten)
        daten = self._anfrage(
            "POST",
            "/preauthkey",
            json={
                "user": str(user_id),
                "reusable": False,
                "ephemeral": False,
                "expiration": _rfc3339(ablauf),
            },
        )
        return daten["preAuthKey"]["key"]

    # --- Geräte ---

    def geraete(self, benutzer_name: str) -> list[dict]:
        return self._anfrage("GET", "/node", params={"user": benutzer_name}).get("nodes", [])

    def geraet(self, geraet_id: str) -> dict | None:
        try:
            return self._anfrage("GET", f"/node/{geraet_id}").get("node")
        except HeadscaleFehler:
            return None

    def geraet_loeschen(self, geraet_id: str) -> None:
        self._anfrage("DELETE", f"/node/{geraet_id}")

    # --- Regeln ---

    def regeln_setzen(self, regeln_json: str) -> None:
        self._anfrage("PUT", "/policy", json={"policy": regeln_json})

    def erreichbar(self) -> bool:
        try:
            self._anfrage("GET", "/health")
            return True
        except HeadscaleFehler:
            return False
