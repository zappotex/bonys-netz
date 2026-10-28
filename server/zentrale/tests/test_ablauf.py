# SPDX-License-Identifier: GPL-3.0-or-later
"""Durchlauf aller Funktionen der Zentrale mit nachgebildetem Headscale und LiveKit.

Start: cd zentrale && python -m pytest -q
"""

import hashlib
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
        self.kaputt = False

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
        if self.kaputt:
            raise HeadscaleFehler("nicht erreichbar")
        self.regeln = json.loads(regeln)

    def erreichbar(self):
        return True


class FalschesLiveKit(LiveKit):
    def __init__(self):
        super().__init__("http://livekit", "lkkey", "x" * 64)
        self.geloeschte_raeume, self.angelegte_raeume, self.entfernte = [], [], []

    def raum_loeschen(self, raum):
        self.geloeschte_raeume.append(raum)

    def raum_anlegen(self, raum):
        self.angelegte_raeume.append(raum)
        return True

    def teilnehmer_entfernen(self, raum, identitaet):
        self.entfernte.append((raum, identitaet))


@pytest.fixture
def umgebung(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PFAD", str(tmp_path / "z.db"))
    monkeypatch.setattr("app.config._einstellungen", None)   # admin_main liest die Einstellungen neu
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
    # Nur der Hilfe-Port (x11vnc nach Zustimmung) – kein SSH, kein Fernzugriff, keine anderen Dienste
    assert zusatz["dst"] == sorted([f"100.64.0.{tn1_pc}:5959", f"100.64.0.{tn2_pc}:5959"])
    assert not [z for z in zusatz["dst"] if z.endswith(":*")]
    assert not [z for z in zusatz["dst"] if z.startswith(f"100.64.0.{tn1_pc2}:")]   # nur das gewählte Gerät
    assert lk.angelegte_raeume == [kid]

    # Eintrittskarten
    karte_l = client.post(f"/api/v1/kurse/{kid}/eintritt", headers=auth(leiter["token"])).json()
    karte_t = client.post(f"/api/v1/kurse/{kid}/eintritt", headers=auth(tn1["token"])).json()
    dl = jwt.decode(karte_l["eintrittskarte"], "x" * 64, algorithms=["HS256"])
    dt = jwt.decode(karte_t["eintrittskarte"], "x" * 64, algorithms=["HS256"])
    assert dl["video"]["roomAdmin"] and "screen_share" in dl["video"]["canPublishSources"]
    assert "roomAdmin" not in dt["video"] and "screen_share" not in dt["video"]["canPublishSources"]
    assert dt["name"] == "Anna" and dt["video"]["room"] == kid
    # Niemand darf seine eigenen Metadaten (Rolle) ändern; die Rolle erkennt die App an der Identität
    assert "canUpdateOwnMetadata" not in dl["video"] and "canUpdateOwnMetadata" not in dt["video"]
    assert karte_t["kursleiter_identitaet"] == leiter["instanz_id"] == dl["sub"]
    assert 14 * 60 <= dt["exp"] - dt["nbf"] <= 16 * 60   # kurz gültig, LiveKit erneuert sie verbundenen
    # Fremde Instanz bekommt keine Karte
    fremd = neue_instanz(client, "4.4.4.4")
    assert client.post(f"/api/v1/kurse/{kid}/eintritt", headers=auth(fremd["token"])).status_code == 403

    # Teilnehmer sieht seinen Kurs, aber nicht den Code
    teilnahmen = client.get("/api/v1/kurse/teilnahmen", headers=auth(tn1["token"])).json()
    assert teilnahmen[0]["kurs_id"] == kid and "code" not in teilnahmen[0]

    # Kursleiter entfernt Ben
    tn2_id = tn2["instanz_id"]
    assert client.delete(f"/api/v1/kurse/{kid}/teilnehmer/{tn2_id}", headers=auth(leiter["token"])).status_code == 204
    assert hs.regeln["acls"][1]["dst"] == [f"100.64.0.{tn1_pc}:5959"]
    assert lk.entfernte == [(kid, tn2_id)]   # sofort aus dem Kursraum

    # Pausieren nimmt die Zusatzregel weg und schließt den Raum
    client.post(f"/api/v1/kurse/{kid}/status", json={"status": "pausiert"}, headers=auth(leiter["token"]))
    assert len(hs.regeln["acls"]) == 1 and lk.geloeschte_raeume == [kid]

    # Beenden: Regel weg, Raum gelöscht, Code ungültig, Teilnahmen gelöscht
    client.post(f"/api/v1/kurse/{kid}/status", json={"status": "laeuft"}, headers=auth(leiter["token"]))
    client.post(f"/api/v1/kurse/{kid}/status", json={"status": "beendet"}, headers=auth(leiter["token"]))
    assert len(hs.regeln["acls"]) == 1 and lk.geloeschte_raeume == [kid, kid]
    assert client.app.state.db.eins("SELECT COUNT(*) AS n FROM teilnahmen WHERE kurs_id = ?", kid)["n"] == 0
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


def _kurs_mit_teilnehmer(client, hs, capsys):
    leiter = neue_instanz(client, "1.1.1.1")
    tn = neue_instanz(client, "2.2.2.2")
    admin_main(["kursleiter-code"])
    code = capsys.readouterr().out.split("Code: ")[1].split()[0]
    client.post("/api/v1/instanz/kursleiter", json={"code": code}, headers=auth(leiter["token"]))
    r = client.post("/api/v1/kurse", json={"name": "Hermes", "kursleiter_name": "Bony"},
                    headers=auth(leiter["token"]))
    assert r.status_code == 201, r.text
    kurs = r.json()
    pc = hs.geraet_hinzufuegen(hs.benutzer["2"], "agent-1")
    r = client.post("/api/v1/kurse/beitreten", headers=auth(tn["token"]),
                    json={"code": kurs["code"], "geraet_id": pc, "anzeigename": "Anna"})
    assert r.status_code == 200, r.text
    return leiter, tn, kurs["kurs_id"]


PAKET = b"PK\x03\x04" + b"inhalt" * 100
ANGABEN = {"paket_id": "einfuehrung-hermes-agent", "name": "Einführung in Hermes Agent", "version": "1.0.0",
           "lektionen": 9}


def test_kurspaket_und_fortschritt(umgebung, capsys, tmp_path):
    client, hs, _ = umgebung
    leiter, tn, kid = _kurs_mit_teilnehmer(client, hs, capsys)
    fremd = neue_instanz(client, "3.3.3.3")
    url = f"/api/v1/kurse/{kid}/kurspaket"

    # Noch kein Kurspaket
    assert client.get("/api/v1/kurse/teilnahmen", headers=auth(tn["token"])).json()[0]["kurspaket"] is None
    assert client.get(url, headers=auth(tn["token"])).status_code == 404
    assert client.post(f"/api/v1/kurse/{kid}/fortschritt", json={"lektion": 1},
                       headers=auth(tn["token"])).status_code == 409

    # Hochladen nur der Kursleiter dieses Kurses, nur ZIP, mit gültigen Angaben
    assert client.put(url, params=ANGABEN, content=PAKET, headers=auth(tn["token"])).status_code == 403
    assert client.put(url, params=ANGABEN, content=b"kein zip", headers=auth(leiter["token"])).status_code == 400
    assert client.put(url, params={**ANGABEN, "paket_id": "../x"}, content=PAKET,
                      headers=auth(leiter["token"])).status_code == 422
    r = client.put(url, params=ANGABEN, content=PAKET, headers=auth(leiter["token"]))
    assert r.status_code == 200, r.text
    angaben = r.json()["kurspaket"]
    assert angaben["paket_id"] == "einfuehrung-hermes-agent" and angaben["groesse"] == len(PAKET)
    assert angaben["sha256"] == hashlib.sha256(PAKET).hexdigest() and angaben["lektionen"] == 9
    assert not [p for p in (tmp_path / "kurspakete").iterdir() if p.name.startswith(".")]   # kein Rest

    # Teilnehmer sieht die Angaben und holt die Datei; Fremde nicht
    assert client.get("/api/v1/kurse/teilnahmen", headers=auth(tn["token"])).json()[0]["kurspaket"] == angaben
    r = client.get(url, headers=auth(tn["token"]))
    assert r.status_code == 200 and r.content == PAKET
    assert r.headers["x-kurspaket-sha256"] == angaben["sha256"]
    assert client.get(url, headers=auth(fremd["token"])).status_code == 403

    # Fortschritt: nur Teilnehmer, nur gültige Lektionen; der Kursleiter sieht ihn nur, solange der Kurs läuft
    melden = f"/api/v1/kurse/{kid}/fortschritt"
    assert client.post(melden, json={"lektion": 3}, headers=auth(fremd["token"])).status_code == 404
    assert client.post(melden, json={"lektion": 10}, headers=auth(tn["token"])).status_code == 422
    assert client.post(melden, json={"lektion": 3, "geschafft": True}, headers=auth(tn["token"])).status_code == 204
    kurs = client.get("/api/v1/kurse/geleitet", headers=auth(leiter["token"])).json()[0]
    assert kurs["status"] == "offen" and kurs["teilnehmer"][0]["fortschritt"] is None
    client.post(f"/api/v1/kurse/{kid}/status", json={"status": "laeuft"}, headers=auth(leiter["token"]))
    kurs = client.get("/api/v1/kurse/geleitet", headers=auth(leiter["token"])).json()[0]
    assert kurs["teilnehmer"][0]["fortschritt"]["lektion"] == 3
    assert kurs["teilnehmer"][0]["fortschritt"]["geschafft"] is True
    client.post(melden, json={"lektion": 4}, headers=auth(tn["token"]))
    kurs = client.get("/api/v1/kurse/geleitet", headers=auth(leiter["token"])).json()[0]
    assert kurs["teilnehmer"][0]["fortschritt"]["geschafft"] is None

    # Zu groß
    os.environ["MAX_KURSPAKET_MB"] = "0"
    try:
        klein = app_erstellen(Einstellungen(), FalschesHeadscale(), FalschesLiveKit())
        with TestClient(klein) as c2:
            assert c2.put(url, params=ANGABEN, content=PAKET, headers=auth(leiter["token"])).status_code == 413
    finally:
        del os.environ["MAX_KURSPAKET_MB"]

    # Anderes Paket: alter Fortschritt verfällt
    r = client.put(url, params={**ANGABEN, "paket_id": "anderes-paket"}, content=PAKET + b"x",
                   headers=auth(leiter["token"]))
    assert r.json()["teilnehmer"][0]["fortschritt"] is None

    # Beenden löscht Datei, Angaben und Fortschritt
    client.post(melden, json={"lektion": 2}, headers=auth(tn["token"]))
    client.post(f"/api/v1/kurse/{kid}/status", json={"status": "beendet"}, headers=auth(leiter["token"]))
    assert not (tmp_path / "kurspakete" / f"{kid}.bonyspaket").exists()
    kurs = client.get("/api/v1/kurse/geleitet", params={"alle": "true"}, headers=auth(leiter["token"])).json()[0]
    assert kurs["kurspaket"] is None and kurs["teilnehmer"] == []
    # Die Teilnahme ist mit dem Kursende gelöscht – Meldungen werden abgewiesen
    assert client.post(melden, json={"lektion": 2}, headers=auth(tn["token"])).status_code == 404


def test_kurspaket_entfernen_und_instanz_loeschen(umgebung, capsys, tmp_path):
    client, hs, _ = umgebung
    leiter, tn, kid = _kurs_mit_teilnehmer(client, hs, capsys)
    url = f"/api/v1/kurse/{kid}/kurspaket"
    client.put(url, params=ANGABEN, content=PAKET, headers=auth(leiter["token"]))
    client.post(f"/api/v1/kurse/{kid}/fortschritt", json={"lektion": 1}, headers=auth(tn["token"]))
    # Teilnehmer verlässt den Kurs: sein Fortschritt geht mit
    client.delete(f"/api/v1/kurse/{kid}/teilnahme", headers=auth(tn["token"]))
    assert client.app.state.db.eins("SELECT COUNT(*) AS n FROM fortschritt")["n"] == 0
    assert client.delete(url, headers=auth(tn["token"])).status_code == 403
    assert client.delete(url, headers=auth(leiter["token"])).status_code == 204
    assert client.delete(url, headers=auth(leiter["token"])).status_code == 404
    assert not (tmp_path / "kurspakete" / f"{kid}.bonyspaket").exists()
    # Instanz des Kursleiters löschen entfernt auch hochgeladene Dateien
    client.put(url, params=ANGABEN, content=PAKET, headers=auth(leiter["token"]))
    assert (tmp_path / "kurspakete" / f"{kid}.bonyspaket").exists()
    assert client.delete("/api/v1/instanz", headers=auth(leiter["token"])).status_code == 204
    assert not (tmp_path / "kurspakete" / f"{kid}.bonyspaket").exists()


def test_ip_adresse_nicht_dauerhaft(umgebung):
    client, _, _ = umgebung
    neue_instanz(client, "7.7.7.7")
    db = client.app.state.db
    assert db.eins("SELECT ip_hash FROM instanzen")["ip_hash"] == ""
    assert db.eins("SELECT COUNT(*) AS n FROM anlegen_grenze")["n"] == 1
    # Nach 24 Stunden ist der Eintrag weg – und die Grenze wieder frei
    db.ausfuehren("UPDATE anlegen_grenze SET zeit = zeit - 86401")
    for _ in range(3):
        neue_instanz(client, "7.7.7.7")
    assert db.eins("SELECT COUNT(*) AS n FROM anlegen_grenze")["n"] == 3


def test_keine_oeffentliche_schnittstellen_doku(umgebung):
    client, _, _ = umgebung
    for pfad in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(pfad).status_code == 404


def test_regeln_werden_nach_ausfall_nachgeholt(umgebung, capsys, monkeypatch):
    client, hs, _ = umgebung
    leiter, _, kid = _kurs_mit_teilnehmer(client, hs, capsys)
    client.post(f"/api/v1/kurse/{kid}/status", json={"status": "laeuft"}, headers=auth(leiter["token"]))
    assert len(hs.regeln["acls"]) == 2
    # Headscale fällt aus: Pausieren meldet den Fehler, die alte Regel steht noch
    hs.kaputt = True
    r = client.post(f"/api/v1/kurse/{kid}/status", json={"status": "pausiert"}, headers=auth(leiter["token"]))
    assert r.status_code == 502 and len(hs.regeln["acls"]) == 2
    assert client.get("/health").json()["regeln_aktuell"] is False
    # Headscale wieder da: der nächste Abgleich schließt den Zugang
    hs.kaputt = False
    client.app.state.abgleichen()   # läuft sonst alle ABGLEICH_SEKUNDEN im Hintergrund
    assert len(hs.regeln["acls"]) == 1
    assert client.get("/health").json()["regeln_aktuell"] is True


def test_loeschfristen(umgebung, capsys):
    client, hs, lk = umgebung
    _, _, kid = _kurs_mit_teilnehmer(client, hs, capsys)
    db = client.app.state.db
    # Kurscode seit mehr als 7 Tagen abgelaufen: Der Kurs endet von selbst, Teilnahmen sind weg
    db.ausfuehren("UPDATE kurse SET code_gueltig_bis = ? WHERE id = ?", 1000, kid)
    client.app.state.aufraeumen()
    assert db.eins("SELECT status FROM kurse WHERE id = ?", kid)["status"] == "beendet"
    assert db.eins("SELECT COUNT(*) AS n FROM teilnahmen")["n"] == 0 and kid in lk.geloeschte_raeume
    # Beendete Kurse verschwinden nach 30 Tagen ganz
    client.app.state.aufraeumen()
    assert db.eins("SELECT 1 FROM kurse WHERE id = ?", kid) is not None
    db.ausfuehren("UPDATE kurse SET beendet = ? WHERE id = ?", 1000, kid)
    client.app.state.aufraeumen()
    assert db.eins("SELECT 1 FROM kurse WHERE id = ?", kid) is None
