# SPDX-License-Identifier: GPL-3.0-or-later
"""Kompletter Ablauf gegen eine echte Zentrale mit echtem Headscale.

Läuft nur, wenn diese Umgebungsvariablen gesetzt sind (sonst übersprungen):
    BONY_NETZ_TESTSERVER   z. B. http://127.0.0.1:18000   (Test-Zentrale, NIE der echte Server)
    HS_BEFEHL              Befehl, um Headscale aufzurufen, z. B. "headscale -c /pfad/config.yaml"
                           (Variablen HEADSCALE_* nicht setzen: Headscale wertet sie selbst aus)
    ZENTRALE_ADMIN         Befehl für die Verwaltung der Zentrale, z. B. "python -m app.admin"
    ZENTRALE_ORDNER        Ordner, in dem ZENTRALE_ADMIN läuft

Headscale erzeugt dabei Test-Geräte ohne echten Tailscale-Client.
"""

import json
import os
import re
import secrets
import shlex
import string
import subprocess

import pytest

from bony_netz import Konto, Zentrale, ZentraleFehler

SERVER = os.environ.get("BONY_NETZ_TESTSERVER")
pytestmark = pytest.mark.skipif(not SERVER, reason="BONY_NETZ_TESTSERVER nicht gesetzt")


def headscale(*args) -> str:
    ergebnis = subprocess.run(shlex.split(os.environ["HS_BEFEHL"]) + list(args),
                              capture_output=True, text=True)
    if ergebnis.returncode != 0:
        raise RuntimeError(f"headscale {' '.join(args)}: {ergebnis.stdout} {ergebnis.stderr}")
    return re.sub(r"\x1b\[[0-9;]*m", "", ergebnis.stdout)


def geraet_anlegen(instanz_id: str, name: str) -> None:
    """Legt in Headscale ein Gerät für die Instanz an, als hätte sich ein Agenten-PC angemeldet."""
    schluessel = "hskey-authreq-" + "".join(secrets.choice(string.ascii_letters + string.digits)
                                             for _ in range(24))
    headscale("debug", "create-node", "--key", schluessel, "--user", instanz_id, "--name", name)
    headscale("auth", "register", "--auth-id", schluessel, "--user", instanz_id)


def kursleiter_code() -> str:
    ausgabe = subprocess.run(shlex.split(os.environ["ZENTRALE_ADMIN"]) + ["kursleiter-code", "Test"],
                             cwd=os.environ["ZENTRALE_ORDNER"], capture_output=True, text=True, check=True)
    return ausgabe.stdout.split("Code: ")[1].split()[0]


def regeln() -> dict:
    return json.loads(headscale("policy", "get"))


def neue_instanz(tmp_path, name) -> tuple[Konto, Zentrale]:
    os.environ["BONY_NETZ_ORDNER"] = str(tmp_path / name)
    konto = Konto.laden()
    konto.server_wechseln(SERVER)
    zentrale = Zentrale(konto.server)
    konto.uebernehmen(zentrale.instanz_registrieren())
    konto.speichern()
    return Konto.laden(), Zentrale(SERVER, Konto.laden().token)


def test_ganzer_ablauf(tmp_path):
    info = Zentrale(SERVER).info()
    assert info["login_server"].startswith("http")

    k_leiter, leiter = neue_instanz(tmp_path, "leiter")
    k_anna, anna = neue_instanz(tmp_path, "anna")
    k_ben, ben = neue_instanz(tmp_path, "ben")

    # Geräteschlüssel kommt von Headscale
    assert leiter.geraeteschluessel()["schluessel"].startswith("hskey-auth-")

    geraet_anlegen(k_leiter.instanz_id, "kursleiter-pc")
    geraet_anlegen(k_anna.instanz_id, "anna-pc1")
    geraet_anlegen(k_anna.instanz_id, "anna-pc2")
    geraet_anlegen(k_ben.instanz_id, "ben-pc1")

    anna_geraete = {g["name"]: g for g in anna.geraete()}
    assert set(anna_geraete) == {"anna-pc1", "anna-pc2"}
    ben_pc = ben.geraete()[0]

    # Ohne Freischaltung kein Kurs
    with pytest.raises(ZentraleFehler) as e:
        leiter.kurs_anlegen("Test", "Bony")
    assert e.value.status == 403

    leiter.kursleiter_freischalten(kursleiter_code())
    assert leiter.instanz()["ist_kursleiter"]

    kurs = leiter.kurs_anlegen("Einführung Hermes", "Bony")
    anna.kurs_beitreten(kurs["code"].lower(), anna_geraete["anna-pc1"]["geraet_id"], "Anna")
    ben.kurs_beitreten(kurs["code"], ben_pc["geraet_id"], "Ben")

    # Fremdes Gerät geht nicht
    with pytest.raises(ZentraleFehler) as e:
        anna.kurs_beitreten(kurs["code"], ben_pc["geraet_id"], "Anna")
    assert e.value.status == 404

    assert len(regeln()["acls"]) == 1
    leiter.kurs_starten(kurs["kurs_id"])
    zusatz = regeln()["acls"][1]
    assert zusatz["src"] == [f"{k_leiter.instanz_id}@"]
    assert sorted(zusatz["dst"]) == sorted([f"{anna_geraete['anna-pc1']['ip']}:*", f"{ben_pc['ip']}:*"])

    karte = anna.eintrittskarte(kurs["kurs_id"])
    assert karte["rolle"] == "teilnehmer" and karte["eintrittskarte"].count(".") == 2
    assert leiter.eintrittskarte(kurs["kurs_id"])["rolle"] == "kursleiter"

    leiter.teilnehmer_entfernen(kurs["kurs_id"], k_ben.instanz_id)
    assert regeln()["acls"][1]["dst"] == [f"{anna_geraete['anna-pc1']['ip']}:*"]

    leiter.kurs_pausieren(kurs["kurs_id"])
    assert len(regeln()["acls"]) == 1
    leiter.kurs_starten(kurs["kurs_id"])
    leiter.kurs_beenden(kurs["kurs_id"])
    assert len(regeln()["acls"]) == 1
    assert anna.teilnahmen() == []

    # Gerät entfernen und Instanz löschen
    anna.geraet_entfernen(anna_geraete["anna-pc2"]["geraet_id"])
    assert [g["name"] for g in anna.geraete()] == ["anna-pc1"]
    for z in (anna, ben, leiter):
        z.instanz_loeschen()
    with pytest.raises(ZentraleFehler) as e:
        anna.geraete()
    assert e.value.anmeldung_ungueltig
    assert k_anna.instanz_id not in headscale("users", "list")
