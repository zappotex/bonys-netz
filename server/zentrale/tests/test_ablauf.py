# SPDX-License-Identifier: GPL-3.0-or-later
"""Durchlauf aller Funktionen der Zentrale mit nachgebildetem Headscale und LiveKit.

Start: cd zentrale && python -m pytest -q
"""

import json
import os

import jwt
import pytest
from fastapi.testclient import TestClient

os.environ.update({
    "HEADSCALE_API_KEY": "test", "LIVEKIT_KEY": "lkkey", "LIVEKIT_SECRET": "x" * 64,
    "VPN_PUBLIC_URL": "https://vpn.test", "KURS_PUBLIC_URL": "wss://kurs.test",
    "ZENTRALE_SALZ": "salz", "MAX_GERAETE_PRO_INSTANZ": "2",
})

from app.admin import main as admin_main  # noqa: E402
from app.config import Einstellungen  # noqa: E402
from app.headscale import HeadscaleFehler  # noqa: E402
from app.livekit import LiveKit  # noqa: E402
from app.main import app_erstellen  # noqa: E402


class FalschesHeadscale:
    def __init__(self):
        self.benutzer, self.alle_geraete, self.regeln, self.naechste_id = {}, {}, None, 1

    def benutzer_anlegen(self, name):
        uid = str(len(self.benutzer) + 1)
        self.benutzer[uid] = name
        return {"id": uid, "name": name}

    def benutzer_loeschen(self, uid):
        if any(g["user"]["name"] == self.benutzer[uid] for g in self.alle_geraete.values()):
            raise HeadscaleFehler("Benutzer hat noch Geräte")
        del self.benutzer[uid]

    def anmeldeschluessel(self, uid, minuten):
        return f"hskey-{uid}"

    def geraet_hinzufuegen(self, benutzer_name, name):
        gid = str(self.naechste_id)
        self.naechste_id += 1
        self.alle_geraete[gid] = {"id": gid, "givenName": name, "online": True,
                             "ipAddresses": [f"100.64.0.{gid}"], "user": {"name": benutzer_name}}
        return gid

    def geraete(self, name):
        return [g for g in self.alle_geraete.values() if g["user"]["name"] == name]

    def geraet(self, gid):
        return self.alle_geraete.get(gid)

    def geraet_loeschen(self, gid):
        self.alle_geraete.pop(gid)

    def regeln_setzen(self, regeln):
        self.regeln = json.loads(regeln)

    def erreichbar(self):
        return True


class FalschesLiveKit(LiveKit):
    def __init__(self):
        super().__init__("http://livekit", "lkkey", "x" * 64)
        self.geloeschte_raeume = []

    def raum_loeschen(self, raum):
        self.geloeschte_raeume.append(raum)


@pytest.fixture
def umgebung(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PFAD", str(tmp_path / "z.db"))
    hs, lk = FalschesHeadscale(), FalschesLiveKit()
    app = app_erstellen(Einstellungen(), hs, lk)
    with TestClient(app) as client:
        yield client, hs, lk


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def neue_instanz(client, ip):
    r = client.post("/api/v1/instanzen", headers={"X-Forwarded-For": ip})
    assert r.status_code == 201, r.text
    return r.json()


def test_gesamter_ablauf(umgebung, capsys):
    client, hs, lk = umgebung
    assert client.get("/api/v1/info").json()["login_server"] == "https://vpn.test"
    assert hs.regeln["acls"][0]["dst"] == ["autogroup:self:*"]

    leiter = neue_instanz(client, "1.1.1.1")
    tn1 = neue_instanz(client, "2.2.2.2")
    tn2 = neue_instanz(client, "3.3.3.3")
    leiter_user = hs.benutzer["1"]

    # Ohne Token geht nichts
    assert client.get("/api/v1/geraete").status_code == 401

    # Gerätegrenze: zwei erlaubt
    assert client.post("/api/v1/geraete/schluessel", headers=auth(leiter["token"])).json()["schluessel"] == "hskey-1"
    leiter_pc = hs.geraet_hinzufuegen(leiter_user, "kursleiter-pc")
    tn1_pc = hs.geraet_hinzufuegen(hs.benutzer["2"], "agent-1")
    tn1_pc2 = hs.geraet_hinzufuegen(hs.benutzer["2"], "agent-2")
    tn2_pc = hs.geraet_hinzufuegen(hs.benutzer["3"], "agent-1")
    assert client.post("/api/v1/geraete/schluessel", headers=auth(tn1["token"])).status_code == 409
    liste = client.get("/api/v1/geraete", headers=auth(tn1["token"])).json()
    assert {g["name"] for g in liste} == {"agent-1", "agent-2"}

    # Kurs anlegen nur als Kursleiter
    kurs_daten = {"name": "Einführung Hermes", "kursleiter_name": "Bony"}
    assert client.post("/api/v1/kurse", json=kurs_daten, headers=auth(leiter["token"])).status_code == 403
    admin_main(["kursleiter-code", "Test"])
    code = capsys.readouterr().out.split("Code: ")[1].split()[0]
    assert client.post("/api/v1/instanz/kursleiter", json={"code": code.lower().replace("-", " ")},
                       headers=auth(leiter["token"])).status_code == 200
    # Code ist nur einmal gültig
    assert client.post("/api/v1/instanz/kursleiter", json={"code": code},
                       headers=auth(tn1["token"])).status_code == 400

    kurs = client.post("/api/v1/kurse", json=kurs_daten, headers=auth(leiter["token"])).json()
    kid, kcode = kurs["kurs_id"], kurs["code"]
    assert kurs["status"] == "offen"

    # Fremdes Gerät kann nicht für den Beitritt benutzt werden
    r = client.post("/api/v1/kurse/beitreten", headers=auth(tn1["token"]),
                    json={"code": kcode, "geraet_id": tn2_pc, "anzeigename": "Anna"})
    assert r.status_code == 404
    # Falscher Code
    r = client.post("/api/v1/kurse/beitreten", headers=auth(tn1["token"]),
                    json={"code": "AAAA-AAAA", "geraet_id": tn1_pc, "anzeigename": "Anna"})
    assert r.status_code == 404
    # Kursleiter kann nicht dem eigenen Kurs beitreten
    r = client.post("/api/v1/kurse/beitreten", headers=auth(leiter["token"]),
                    json={"code": kcode, "geraet_id": leiter_pc, "anzeigename": "Bony"})
    assert r.status_code == 409

    for t, pc, name in ((tn1, tn1_pc, "Anna"), (tn2, tn2_pc, "Ben")):
        r = client.post("/api/v1/kurse/beitreten", headers=auth(t["token"]),
                        json={"code": kcode.lower(), "geraet_id": pc, "anzeigename": name})
        assert r.status_code == 200, r.text

    # Solange der Kurs nicht läuft: keine Zusatzregel, keine Eintrittskarte
    assert len(hs.regeln["acls"]) == 1
    assert client.post(f"/api/v1/kurse/{kid}/eintritt", headers=auth(tn1["token"])).status_code == 409

    # Kurs starten
    r = client.post(f"/api/v1/kurse/{kid}/status", json={"status": "laeuft"}, headers=auth(leiter["token"]))
    assert r.json()["status"] == "laeuft"
    assert len(r.json()["teilnehmer"]) == 2
    zusatz = hs.regeln["acls"][1]
    assert zusatz["src"] == [f"{leiter_user}@"]
    assert zusatz["dst"] == sorted([f"100.64.0.{tn1_pc}:*", f"100.64.0.{tn2_pc}:*"])
    assert f"100.64.0.{tn1_pc2}:*" not in zusatz["dst"]   # nur das gewählte Gerät

    # Eintrittskarten
    karte_l = client.post(f"/api/v1/kurse/{kid}/eintritt", headers=auth(leiter["token"])).json()
    karte_t = client.post(f"/api/v1/kurse/{kid}/eintritt", headers=auth(tn1["token"])).json()
    dl = jwt.decode(karte_l["eintrittskarte"], "x" * 64, algorithms=["HS256"])
    dt = jwt.decode(karte_t["eintrittskarte"], "x" * 64, algorithms=["HS256"])
    assert dl["video"]["roomAdmin"] and "screen_share" in dl["video"]["canPublishSources"]
    assert "roomAdmin" not in dt["video"] and "screen_share" not in dt["video"]["canPublishSources"]
    assert dt["name"] == "Anna" and dt["video"]["room"] == kid
    # Fremde Instanz bekommt keine Karte
    fremd = neue_instanz(client, "4.4.4.4")
    assert client.post(f"/api/v1/kurse/{kid}/eintritt", headers=auth(fremd["token"])).status_code == 403

    # Teilnehmer sieht seinen Kurs, aber nicht den Code
    teilnahmen = client.get("/api/v1/kurse/teilnahmen", headers=auth(tn1["token"])).json()
    assert teilnahmen[0]["kurs_id"] == kid and "code" not in teilnahmen[0]

    # Kursleiter entfernt Ben
    tn2_id = tn2["instanz_id"]
    assert client.delete(f"/api/v1/kurse/{kid}/teilnehmer/{tn2_id}", headers=auth(leiter["token"])).status_code == 204
    assert hs.regeln["acls"][1]["dst"] == [f"100.64.0.{tn1_pc}:*"]

    # Pausieren nimmt die Zusatzregel weg
    client.post(f"/api/v1/kurse/{kid}/status", json={"status": "pausiert"}, headers=auth(leiter["token"]))
    assert len(hs.regeln["acls"]) == 1

    # Beenden: Regel weg, Raum gelöscht, Code ungültig
    client.post(f"/api/v1/kurse/{kid}/status", json={"status": "laeuft"}, headers=auth(leiter["token"]))
    client.post(f"/api/v1/kurse/{kid}/status", json={"status": "beendet"}, headers=auth(leiter["token"]))
    assert len(hs.regeln["acls"]) == 1 and lk.geloeschte_raeume == [kid]
    r = client.post("/api/v1/kurse/beitreten", headers=auth(tn2["token"]),
                    json={"code": kcode, "geraet_id": tn2_pc, "anzeigename": "Ben"})
    assert r.status_code == 404

    # Instanz löschen entfernt Geräte und Benutzer
    assert client.delete("/api/v1/instanz", headers=auth(tn1["token"])).status_code == 204
    assert "2" not in hs.benutzer and not hs.geraete(f"{tn1['instanz_id']}")
    assert client.get("/api/v1/instanz", headers=auth(tn1["token"])).status_code == 401


def test_grenze_instanzen_pro_ip(umgebung):
    client, _, _ = umgebung
    for _ in range(3):
        neue_instanz(client, "9.9.9.9")
    r = client.post("/api/v1/instanzen", headers={"X-Forwarded-For": "9.9.9.9"})
    assert r.status_code == 429
    neue_instanz(client, "8.8.8.8")


def test_regeln_nach_neustart(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PFAD", str(tmp_path / "z.db"))
    hs = FalschesHeadscale()
    with TestClient(app_erstellen(Einstellungen(), hs, FalschesLiveKit())):
        pass
    hs.regeln = None
    with TestClient(app_erstellen(Einstellungen(), hs, FalschesLiveKit())):
        assert hs.regeln is not None
