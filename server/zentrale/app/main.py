# SPDX-License-Identifier: GPL-3.0-or-later
"""Die Zentrale: Schnittstelle zwischen der App Bony's Agents und Headscale/LiveKit.

Alle Pfade liegen unter /api/v1. Angemeldete Aufrufe schicken das
Instanz-Token im Kopf 'Authorization: Bearer <token>'.
"""

import hashlib
import logging
import os
import tempfile
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import VERSION
from .config import Einstellungen, einstellungen
from .db import Datenbank, jetzt, sha256
from .headscale import Headscale, HeadscaleFehler
from .kennungen import (code_normalisieren, instanz_id, kurs_id, lesbarer_code,
                        zugangstoken)
from .livekit import LiveKit
from .regeln import regeln_bauen

log = logging.getLogger("zentrale")


# ---------------------------------------------------------------------------
# Datenmodelle für Anfragen
# ---------------------------------------------------------------------------

class KursleiterFreischalten(BaseModel):
    code: str = Field(min_length=4, max_length=40)


class KursAnlegen(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kursleiter_name: str = Field(min_length=1, max_length=60)
    code_gueltig_tage: int = Field(default=14, ge=1)


class KursBeitreten(BaseModel):
    code: str = Field(min_length=4, max_length=20)
    geraet_id: str = Field(min_length=1, max_length=20)
    anzeigename: str = Field(min_length=1, max_length=60)


class KursStatus(BaseModel):
    status: str = Field(pattern="^(laeuft|pausiert|beendet)$")


class Fortschritt(BaseModel):
    lektion: int = Field(ge=1, le=100)
    geschafft: bool | None = None


# Wie die App die Angaben eines Kurspakets prüft (bonys_agents.kurspaket)
PAKET_ID_MUSTER = r"^[a-z0-9][a-z0-9-]{1,58}[a-z0-9]$"
VERSION_MUSTER = r"^[0-9]+(\.[0-9]+){0,3}$"
ZIP_ANFANG = b"PK\x03\x04"


# ---------------------------------------------------------------------------
# Aufbau
# ---------------------------------------------------------------------------

def app_erstellen(eins: Einstellungen | None = None,
                  headscale: Headscale | None = None,
                  livekit: LiveKit | None = None) -> FastAPI:
    eins = eins or einstellungen()
    db = Datenbank(eins.db_pfad)
    hs = headscale or Headscale(eins.headscale_url, eins.headscale_api_key)
    lk = livekit or LiveKit(eins.livekit_url, eins.livekit_key, eins.livekit_secret)

    @asynccontextmanager
    async def lebenszyklus(_app: FastAPI):
        # Nach jedem Neustart den Stand der Regeln aus der Datenbank herstellen.
        try:
            hs.regeln_setzen(regeln_bauen(db))
            log.info("Netzregeln beim Start gesetzt")
        except HeadscaleFehler as e:
            log.error("Netzregeln beim Start nicht gesetzt: %s", e)
        yield

    app = FastAPI(title=f"{eins.server_name} – Zentrale", version=VERSION, lifespan=lebenszyklus)
    os.makedirs(eins.kurspaket_ordner, exist_ok=True)

    # -----------------------------------------------------------------------
    # Hilfsfunktionen
    # -----------------------------------------------------------------------

    def regeln_aktualisieren() -> None:
        """Schreibt die aktuellen Regeln nach Headscale."""
        with db.sperre:
            try:
                hs.regeln_setzen(regeln_bauen(db))
            except HeadscaleFehler as e:
                log.error("Regeln konnten nicht gesetzt werden: %s", e)
                raise HTTPException(502, "Die Netzregeln konnten nicht aktualisiert werden.")

    def client_ip(request: Request) -> str:
        # Die Zentrale ist nur über Caddy erreichbar, deshalb ist dieser Kopf vertrauenswürdig.
        weitergeleitet = request.headers.get("x-forwarded-for", "")
        if weitergeleitet:
            return weitergeleitet.split(",")[0].strip()
        return request.client.host if request.client else "unbekannt"

    def instanz_aus_token(authorization: str = Header(default="")):
        if not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Anmeldung fehlt.")
        token = authorization[7:].strip()
        zeile = db.eins("SELECT * FROM instanzen WHERE token_hash = ?", sha256(token))
        if zeile is None:
            raise HTTPException(401, "Unbekannte Instanz oder ungültiges Token.")
        return zeile

    def nur_kursleiter(instanz=Depends(instanz_aus_token)):
        if not instanz["ist_kursleiter"]:
            raise HTTPException(403, "Diese Instanz ist nicht als Kursleiter freigeschaltet.")
        return instanz

    def eigener_kurs(kurs_id_: str, instanz) -> dict:
        kurs = db.eins("SELECT * FROM kurse WHERE id = ? AND kursleiter = ?", kurs_id_, instanz["id"])
        if kurs is None:
            raise HTTPException(404, "Kurs nicht gefunden.")
        return kurs

    def geraet_der_instanz(geraet_id: str, instanz) -> dict:
        geraet = hs.geraet(geraet_id)
        if not geraet or geraet.get("user", {}).get("name") != instanz["hs_user_name"]:
            raise HTTPException(404, "Gerät nicht gefunden.")
        return geraet

    def paket_datei(kurs_id_: str) -> str:
        return os.path.join(eins.kurspaket_ordner, f"{kurs_id_}.bonyspaket")

    def paket_loeschen(kurs_id_: str) -> None:
        """Kurspaket eines Kurses samt Fortschritt entfernen (Datei und Angaben)."""
        db.ausfuehren("DELETE FROM fortschritt WHERE kurs_id = ?", kurs_id_)
        db.ausfuehren("DELETE FROM kurspakete WHERE kurs_id = ?", kurs_id_)
        try:
            os.remove(paket_datei(kurs_id_))
        except FileNotFoundError:
            pass

    def paket_angaben(kurs_id_: str) -> dict | None:
        p = db.eins("SELECT * FROM kurspakete WHERE kurs_id = ?", kurs_id_)
        if p is None:
            return None
        return {"paket_id": p["paket_id"], "name": p["name"], "version": p["version"],
                "lektionen": p["lektionen"], "sha256": p["sha256"], "groesse": p["groesse"],
                "hochgeladen": p["hochgeladen"]}

    def teilnehmer_oder_leiter(kurs_id_: str, instanz) -> dict:
        k = db.eins("SELECT * FROM kurse WHERE id = ?", kurs_id_)
        if k is None:
            raise HTTPException(404, "Kurs nicht gefunden.")
        if k["kursleiter"] != instanz["id"] and db.eins(
            "SELECT 1 FROM teilnahmen WHERE kurs_id = ? AND instanz_id = ?", k["id"], instanz["id"]
        ) is None:
            raise HTTPException(403, "Du nimmst an diesem Kurs nicht teil.")
        return k

    def kurs_ausgabe(kurs, mit_teilnehmern: bool) -> dict:
        daten = {
            "kurs_id": kurs["id"],
            "name": kurs["name"],
            "kursleiter_name": kurs["kursleiter_name"],
            "status": kurs["status"],
            "raum": kurs["id"],
            "code": f"{kurs['code'][:4]}-{kurs['code'][4:]}",
            "code_gueltig_bis": kurs["code_gueltig_bis"],
            "erstellt": kurs["erstellt"],
            "kurspaket": paket_angaben(kurs["id"]),
        }
        if mit_teilnehmern:
            # Fortschritt (Lektion, geschafft / noch nicht) sieht der Kursleiter nur, solange der Kurs läuft
            mit_fortschritt = kurs["status"] == "laeuft"
            daten["teilnehmer"] = [
                {
                    "instanz_id": t["instanz_id"],
                    "anzeigename": t["anzeigename"],
                    "geraet_name": t["geraet_name"],
                    "geraet_ip": t["geraet_ip"],
                    "beigetreten": t["beigetreten"],
                    "fortschritt": {
                        "lektion": t["lektion"],
                        "geschafft": None if t["geschafft"] is None else bool(t["geschafft"]),
                        "aktualisiert": t["aktualisiert"],
                    } if mit_fortschritt and t["lektion"] is not None else None,
                }
                for t in db.alle(
                    "SELECT t.*, f.lektion, f.geschafft, f.aktualisiert FROM teilnahmen t "
                    "LEFT JOIN fortschritt f ON f.kurs_id = t.kurs_id AND f.instanz_id = t.instanz_id "
                    "WHERE t.kurs_id = ? ORDER BY t.beigetreten", kurs["id"]
                )
            ]
        return daten

    def kurs_beenden(kurs) -> None:
        db.ausfuehren("UPDATE kurse SET status = 'beendet', beendet = ? WHERE id = ?", jetzt(), kurs["id"])
        lk.raum_loeschen(kurs["id"])
        paket_loeschen(kurs["id"])

    # -----------------------------------------------------------------------
    # Allgemein
    # -----------------------------------------------------------------------

    @app.get("/health")
    def gesundheit():
        return {"status": "ok", "headscale": hs.erreichbar()}

    @app.get("/api/v1/info")
    def info():
        """Alles, was die App braucht, um sich mit diesem Server zu verbinden."""
        return {
            "server_name": eins.server_name,
            "version": VERSION,
            "login_server": eins.vpn_public_url,
            "kursraum_url": eins.kurs_public_url,
            "grenzen": {
                "geraete_pro_instanz": eins.max_geraete_pro_instanz,
                "teilnehmer_pro_kurs": eins.max_teilnehmer_pro_kurs,
                "aktive_kurse_pro_kursleiter": eins.max_aktive_kurse_pro_kursleiter,
            },
        }

    # -----------------------------------------------------------------------
    # Instanzen
    # -----------------------------------------------------------------------

    @app.post("/api/v1/instanzen", status_code=201)
    def instanz_registrieren(request: Request):
        ip_hash = sha256(eins.salz + client_ip(request))
        seit = jetzt() - 86400
        with db.transaktion() as v:
            anzahl = v.execute(
                "SELECT COUNT(*) FROM instanzen WHERE ip_hash = ? AND erstellt > ?", (ip_hash, seit)
            ).fetchone()[0]
            if anzahl >= eins.max_instanzen_pro_ip_tag:
                raise HTTPException(429, "Von diesem Anschluss wurden heute schon zu viele Instanzen angelegt.")

            neue_id = instanz_id()
            try:
                benutzer = hs.benutzer_anlegen(neue_id)
            except HeadscaleFehler as e:
                log.error("Benutzer anlegen fehlgeschlagen: %s", e)
                raise HTTPException(502, "Die Instanz konnte im Netz nicht angelegt werden.")

            token = zugangstoken()
            v.execute(
                "INSERT INTO instanzen (id, hs_user_id, hs_user_name, token_hash, ip_hash, erstellt) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (neue_id, str(benutzer["id"]), benutzer["name"], sha256(token), ip_hash, jetzt()),
            )
        return {
            "instanz_id": neue_id,
            "token": token,
            "login_server": eins.vpn_public_url,
            "hinweis": "Das Token wird nur jetzt angezeigt. Bitte sicher speichern.",
        }

    @app.get("/api/v1/instanz")
    def instanz_anzeigen(instanz=Depends(instanz_aus_token)):
        return {
            "instanz_id": instanz["id"],
            "ist_kursleiter": bool(instanz["ist_kursleiter"]),
            "erstellt": instanz["erstellt"],
        }

    @app.delete("/api/v1/instanz", status_code=204)
    def instanz_loeschen(instanz=Depends(instanz_aus_token)):
        """Löscht die Instanz samt Geräten, eigenen Kursen (mit Kurspaketen) und Kursteilnahmen."""
        for kurs in db.alle(
            "SELECT * FROM kurse WHERE kursleiter = ? AND status != 'beendet'", instanz["id"]
        ):
            lk.raum_loeschen(kurs["id"])
        for kurs in db.alle("SELECT id FROM kurse WHERE kursleiter = ?", instanz["id"]):
            paket_loeschen(kurs["id"])
        try:
            for geraet in hs.geraete(instanz["hs_user_name"]):
                hs.geraet_loeschen(geraet["id"])
            hs.benutzer_loeschen(instanz["hs_user_id"])
        except HeadscaleFehler as e:
            log.error("Instanz %s im Netz nicht vollständig gelöscht: %s", instanz["id"], e)
            raise HTTPException(502, "Die Instanz konnte im Netz nicht gelöscht werden.")
        db.ausfuehren("DELETE FROM instanzen WHERE id = ?", instanz["id"])
        regeln_aktualisieren()

    @app.post("/api/v1/instanz/kursleiter")
    def kursleiter_freischalten(daten: KursleiterFreischalten, instanz=Depends(instanz_aus_token)):
        code_hash = sha256(code_normalisieren(daten.code))
        with db.transaktion() as v:
            zeile = v.execute(
                "SELECT * FROM kursleiter_codes WHERE code_hash = ?", (code_hash,)
            ).fetchone()
            if zeile is None or zeile["eingeloest_von"] is not None:
                raise HTTPException(400, "Der Kursleiter-Code ist ungültig oder wurde schon benutzt.")
            v.execute(
                "UPDATE kursleiter_codes SET eingeloest_von = ?, eingeloest = ? WHERE code_hash = ?",
                (instanz["id"], jetzt(), code_hash),
            )
            v.execute("UPDATE instanzen SET ist_kursleiter = 1 WHERE id = ?", (instanz["id"],))
        return {"ist_kursleiter": True}

    # -----------------------------------------------------------------------
    # Geräte (Agenten-PCs)
    # -----------------------------------------------------------------------

    @app.get("/api/v1/geraete")
    def geraete_auflisten(instanz=Depends(instanz_aus_token)):
        try:
            geraete = hs.geraete(instanz["hs_user_name"])
        except HeadscaleFehler:
            raise HTTPException(502, "Die Geräte konnten nicht abgefragt werden.")
        return [
            {
                "geraet_id": g["id"],
                "name": g.get("givenName") or g.get("name"),
                "ip": (g.get("ipAddresses") or [""])[0],
                "online": bool(g.get("online")),
                "zuletzt_gesehen": g.get("lastSeen"),
            }
            for g in geraete
        ]

    @app.post("/api/v1/geraete/schluessel")
    def geraeteschluessel(instanz=Depends(instanz_aus_token)):
        """Einmal nutzbarer, kurz gültiger Schlüssel für einen neuen Agenten-PC."""
        try:
            anzahl = len(hs.geraete(instanz["hs_user_name"]))
        except HeadscaleFehler:
            raise HTTPException(502, "Die Geräte konnten nicht abgefragt werden.")
        if anzahl >= eins.max_geraete_pro_instanz:
            raise HTTPException(
                409, f"Diese Instanz hat schon {anzahl} Geräte. Erlaubt sind {eins.max_geraete_pro_instanz}."
            )
        try:
            schluessel = hs.anmeldeschluessel(instanz["hs_user_id"], eins.geraeteschluessel_minuten)
        except HeadscaleFehler as e:
            log.error("Anmeldeschlüssel fehlgeschlagen: %s", e)
            raise HTTPException(502, "Es konnte kein Anmeldeschlüssel erzeugt werden.")
        return {
            "schluessel": schluessel,
            "login_server": eins.vpn_public_url,
            "gueltig_minuten": eins.geraeteschluessel_minuten,
        }

    @app.delete("/api/v1/geraete/{geraet_id}", status_code=204)
    def geraet_entfernen(geraet_id: str, instanz=Depends(instanz_aus_token)):
        geraet_der_instanz(geraet_id, instanz)
        try:
            hs.geraet_loeschen(geraet_id)
        except HeadscaleFehler:
            raise HTTPException(502, "Das Gerät konnte nicht entfernt werden.")
        geloescht = db.ausfuehren(
            "DELETE FROM teilnahmen WHERE instanz_id = ? AND geraet_id = ?", instanz["id"], geraet_id
        )
        if geloescht:
            regeln_aktualisieren()

    # -----------------------------------------------------------------------
    # Kurse: Kursleiter
    # -----------------------------------------------------------------------

    @app.post("/api/v1/kurse", status_code=201)
    def kurs_anlegen(daten: KursAnlegen, instanz=Depends(nur_kursleiter)):
        tage = min(daten.code_gueltig_tage, eins.kurscode_gueltig_tage_max)
        with db.transaktion() as v:
            aktiv = v.execute(
                "SELECT COUNT(*) FROM kurse WHERE kursleiter = ? AND status != 'beendet'",
                (instanz["id"],),
            ).fetchone()[0]
            if aktiv >= eins.max_aktive_kurse_pro_kursleiter:
                raise HTTPException(
                    409, f"Es sind schon {aktiv} Kurse aktiv. Bitte zuerst einen Kurs beenden."
                )
            neue_id = kurs_id()
            while True:
                code = code_normalisieren(lesbarer_code())
                if v.execute("SELECT 1 FROM kurse WHERE code = ?", (code,)).fetchone() is None:
                    break
            v.execute(
                "INSERT INTO kurse (id, code, kursleiter, kursleiter_name, name, status, "
                "code_gueltig_bis, erstellt) VALUES (?, ?, ?, ?, ?, 'offen', ?, ?)",
                (neue_id, code, instanz["id"], daten.kursleiter_name.strip(), daten.name.strip(),
                 jetzt() + tage * 86400, jetzt()),
            )
        return kurs_ausgabe(db.eins("SELECT * FROM kurse WHERE id = ?", neue_id), mit_teilnehmern=True)

    @app.get("/api/v1/kurse/geleitet")
    def geleitete_kurse(alle: bool = False, instanz=Depends(nur_kursleiter)):
        sql = "SELECT * FROM kurse WHERE kursleiter = ?"
        if not alle:
            sql += " AND status != 'beendet'"
        return [kurs_ausgabe(k, mit_teilnehmern=True)
                for k in db.alle(sql + " ORDER BY erstellt DESC", instanz["id"])]

    @app.post("/api/v1/kurse/{kurs}/status")
    def kurs_status(kurs: str, daten: KursStatus, instanz=Depends(nur_kursleiter)):
        k = eigener_kurs(kurs, instanz)
        if k["status"] == "beendet":
            raise HTTPException(409, "Der Kurs ist schon beendet.")
        if daten.status == "beendet":
            kurs_beenden(k)
        else:
            db.ausfuehren("UPDATE kurse SET status = ? WHERE id = ?", daten.status, k["id"])
        regeln_aktualisieren()
        return kurs_ausgabe(db.eins("SELECT * FROM kurse WHERE id = ?", k["id"]), mit_teilnehmern=True)

    @app.delete("/api/v1/kurse/{kurs}/teilnehmer/{teilnehmer}", status_code=204)
    def teilnehmer_entfernen(kurs: str, teilnehmer: str, instanz=Depends(nur_kursleiter)):
        k = eigener_kurs(kurs, instanz)
        if not db.ausfuehren(
            "DELETE FROM teilnahmen WHERE kurs_id = ? AND instanz_id = ?", k["id"], teilnehmer
        ):
            raise HTTPException(404, "Teilnehmer nicht gefunden.")
        regeln_aktualisieren()

    # -----------------------------------------------------------------------
    # Kurse: Kurspaket (hochladen nur der Kursleiter, holen auch die Teilnehmer)
    # -----------------------------------------------------------------------

    @app.put("/api/v1/kurse/{kurs}/kurspaket")
    async def kurspaket_hochladen(
        kurs: str,
        request: Request,
        paket_id: str = Query(pattern=PAKET_ID_MUSTER),
        name: str = Query(min_length=1, max_length=120),
        version: str = Query(max_length=20, pattern=VERSION_MUSTER),
        lektionen: int = Query(default=0, ge=0, le=100),
        instanz=Depends(nur_kursleiter),
    ):
        """Rumpf: die .bonyspaket-Datei (application/octet-stream). Ersetzt ein vorhandenes Kurspaket."""
        k = eigener_kurs(kurs, instanz)
        if k["status"] == "beendet":
            raise HTTPException(409, "Der Kurs ist schon beendet.")
        grenze = eins.max_kurspaket_mb * 1024 * 1024
        zu_gross = HTTPException(413, f"Das Kurspaket ist zu groß (höchstens {eins.max_kurspaket_mb} MB).")
        laenge = request.headers.get("content-length", "")
        if laenge.isdigit() and int(laenge) > grenze:
            raise zu_gross
        pruefsumme, groesse = hashlib.sha256(), 0
        fd, tmp = tempfile.mkstemp(dir=eins.kurspaket_ordner, prefix=".hochladen-")
        try:
            with os.fdopen(fd, "wb") as f:
                async for stueck in request.stream():
                    groesse += len(stueck)
                    if groesse > grenze:
                        raise zu_gross
                    pruefsumme.update(stueck)
                    f.write(stueck)
            with open(tmp, "rb") as f:
                if f.read(len(ZIP_ANFANG)) != ZIP_ANFANG:
                    raise HTTPException(400, "Das ist kein Kurspaket (.bonyspaket).")
            os.replace(tmp, paket_datei(k["id"]))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        alt = db.eins("SELECT paket_id FROM kurspakete WHERE kurs_id = ?", k["id"])
        if alt is not None and alt["paket_id"] != paket_id:
            db.ausfuehren("DELETE FROM fortschritt WHERE kurs_id = ?", k["id"])   # gehört zum alten Paket
        db.ausfuehren(
            "INSERT INTO kurspakete (kurs_id, paket_id, name, version, lektionen, sha256, groesse, hochgeladen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(kurs_id) DO UPDATE SET paket_id = excluded.paket_id, "
            "name = excluded.name, version = excluded.version, lektionen = excluded.lektionen, "
            "sha256 = excluded.sha256, groesse = excluded.groesse, hochgeladen = excluded.hochgeladen",
            k["id"], paket_id, " ".join(name.split()), version, lektionen, pruefsumme.hexdigest(), groesse, jetzt(),
        )
        return kurs_ausgabe(db.eins("SELECT * FROM kurse WHERE id = ?", k["id"]), mit_teilnehmern=True)

    @app.delete("/api/v1/kurse/{kurs}/kurspaket", status_code=204)
    def kurspaket_entfernen(kurs: str, instanz=Depends(nur_kursleiter)):
        k = eigener_kurs(kurs, instanz)
        if db.eins("SELECT 1 FROM kurspakete WHERE kurs_id = ?", k["id"]) is None:
            raise HTTPException(404, "Dieser Kurs hat kein Kurspaket.")
        paket_loeschen(k["id"])

    @app.get("/api/v1/kurse/{kurs}/kurspaket")
    def kurspaket_holen(kurs: str, instanz=Depends(instanz_aus_token)):
        k = teilnehmer_oder_leiter(kurs, instanz)
        if k["status"] == "beendet":
            raise HTTPException(409, "Der Kurs ist schon beendet.")
        p = db.eins("SELECT * FROM kurspakete WHERE kurs_id = ?", k["id"])
        if p is None or not os.path.isfile(paket_datei(k["id"])):
            raise HTTPException(404, "Dieser Kurs hat kein Kurspaket.")
        return FileResponse(paket_datei(k["id"]), media_type="application/octet-stream",
                            filename=f"{p['paket_id']}-{p['version']}.bonyspaket",
                            headers={"X-Kurspaket-Sha256": p["sha256"]})

    # -----------------------------------------------------------------------
    # Kurse: Teilnehmer
    # -----------------------------------------------------------------------

    @app.post("/api/v1/kurse/{kurs}/fortschritt", status_code=204)
    def fortschritt_melden(kurs: str, daten: Fortschritt, instanz=Depends(instanz_aus_token)):
        """Nur Lektion und „geschafft / noch nicht“ – keine Inhalte aus dem Agent-PC."""
        k = db.eins("SELECT * FROM kurse WHERE id = ?", kurs)
        if k is None or db.eins(
            "SELECT 1 FROM teilnahmen WHERE kurs_id = ? AND instanz_id = ?", kurs, instanz["id"]
        ) is None:
            raise HTTPException(404, "Du nimmst an diesem Kurs nicht teil.")
        if k["status"] == "beendet":
            raise HTTPException(409, "Der Kurs ist schon beendet.")
        p = db.eins("SELECT lektionen FROM kurspakete WHERE kurs_id = ?", kurs)
        if p is None:
            raise HTTPException(409, "Dieser Kurs hat kein Kurspaket.")
        if p["lektionen"] and daten.lektion > p["lektionen"]:
            raise HTTPException(422, "Diese Lektion gibt es im Kurspaket nicht.")
        db.ausfuehren(
            "INSERT INTO fortschritt (kurs_id, instanz_id, lektion, geschafft, aktualisiert) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(kurs_id, instanz_id) DO UPDATE SET lektion = excluded.lektion, "
            "geschafft = excluded.geschafft, aktualisiert = excluded.aktualisiert",
            kurs, instanz["id"], daten.lektion, None if daten.geschafft is None else int(daten.geschafft), jetzt(),
        )

    @app.post("/api/v1/kurse/beitreten")
    def kurs_beitreten(daten: KursBeitreten, instanz=Depends(instanz_aus_token)):
        code = code_normalisieren(daten.code)
        geraet = geraet_der_instanz(daten.geraet_id, instanz)
        ip = (geraet.get("ipAddresses") or [""])[0]
        if not ip:
            raise HTTPException(409, "Das Gerät hat noch keine Adresse im Netz.")

        with db.transaktion() as v:
            k = v.execute("SELECT * FROM kurse WHERE code = ?", (code,)).fetchone()
            if k is None or k["status"] == "beendet" or k["code_gueltig_bis"] < jetzt():
                raise HTTPException(404, "Diesen Kurscode gibt es nicht oder er ist abgelaufen.")
            if k["kursleiter"] == instanz["id"]:
                raise HTTPException(409, "Du leitest diesen Kurs selbst.")
            schon_dabei = v.execute(
                "SELECT 1 FROM teilnahmen WHERE kurs_id = ? AND instanz_id = ?", (k["id"], instanz["id"])
            ).fetchone()
            if not schon_dabei:
                anzahl = v.execute(
                    "SELECT COUNT(*) FROM teilnahmen WHERE kurs_id = ?", (k["id"],)
                ).fetchone()[0]
                if anzahl >= eins.max_teilnehmer_pro_kurs:
                    raise HTTPException(409, "Der Kurs ist voll.")
            # Ein Teilnehmer nimmt mit genau einem Agenten-PC teil. Ein erneuter Beitritt
            # ersetzt das Gerät und den Anzeigenamen.
            v.execute(
                "INSERT INTO teilnahmen (kurs_id, instanz_id, geraet_id, geraet_name, geraet_ip, "
                "anzeigename, beigetreten) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(kurs_id, instanz_id) DO UPDATE SET geraet_id = excluded.geraet_id, "
                "geraet_name = excluded.geraet_name, geraet_ip = excluded.geraet_ip, "
                "anzeigename = excluded.anzeigename",
                (k["id"], instanz["id"], str(geraet["id"]), geraet.get("givenName") or geraet.get("name", ""),
                 ip, daten.anzeigename.strip(), jetzt()),
            )
        regeln_aktualisieren()
        return kurs_ausgabe(db.eins("SELECT * FROM kurse WHERE id = ?", k["id"]), mit_teilnehmern=False)

    @app.get("/api/v1/kurse/teilnahmen")
    def meine_teilnahmen(instanz=Depends(instanz_aus_token)):
        kurse = db.alle(
            "SELECT k.*, t.geraet_id, t.anzeigename FROM teilnahmen t JOIN kurse k ON k.id = t.kurs_id "
            "WHERE t.instanz_id = ? AND k.status != 'beendet' ORDER BY k.erstellt DESC",
            instanz["id"],
        )
        ergebnis = []
        for k in kurse:
            daten = kurs_ausgabe(k, mit_teilnehmern=False)
            daten.pop("code", None)
            daten["mein_geraet_id"] = k["geraet_id"]
            daten["mein_anzeigename"] = k["anzeigename"]
            ergebnis.append(daten)
        return ergebnis

    @app.delete("/api/v1/kurse/{kurs}/teilnahme", status_code=204)
    def kurs_verlassen(kurs: str, instanz=Depends(instanz_aus_token)):
        if not db.ausfuehren(
            "DELETE FROM teilnahmen WHERE kurs_id = ? AND instanz_id = ?", kurs, instanz["id"]
        ):
            raise HTTPException(404, "Du nimmst an diesem Kurs nicht teil.")
        regeln_aktualisieren()

    # -----------------------------------------------------------------------
    # Kursraum
    # -----------------------------------------------------------------------

    @app.post("/api/v1/kurse/{kurs}/eintritt")
    def eintrittskarte(kurs: str, instanz=Depends(instanz_aus_token)):
        k = db.eins("SELECT * FROM kurse WHERE id = ?", kurs)
        if k is None:
            raise HTTPException(404, "Kurs nicht gefunden.")
        ist_leiter = k["kursleiter"] == instanz["id"]
        if ist_leiter:
            name = k["kursleiter_name"]
        else:
            teilnahme = db.eins(
                "SELECT * FROM teilnahmen WHERE kurs_id = ? AND instanz_id = ?", k["id"], instanz["id"]
            )
            if teilnahme is None:
                raise HTTPException(403, "Du nimmst an diesem Kurs nicht teil.")
            name = teilnahme["anzeigename"]
        if k["status"] != "laeuft":
            raise HTTPException(409, "Der Kurs läuft gerade nicht.")
        karte = lk.eintrittskarte(
            raum=k["id"],
            identitaet=instanz["id"],
            name=name,
            kursleiter=ist_leiter,
            stunden=eins.eintrittskarte_stunden,
        )
        return {
            "kursraum_url": eins.kurs_public_url,
            "raum": k["id"],
            "eintrittskarte": karte,
            "rolle": "kursleiter" if ist_leiter else "teilnehmer",
        }

    app.state.db = db
    return app


def _app_fuer_uvicorn() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return app_erstellen()


# Start: uvicorn app.main:_app_fuer_uvicorn --factory
