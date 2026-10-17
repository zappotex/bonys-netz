# SPDX-License-Identifier: GPL-3.0-or-later
"""Verwaltung der Zentrale über die Kommandozeile.

Aufruf auf dem Server, im Installationsordner:
    docker compose exec zentrale python -m app.admin <befehl>

Befehle:
    kursleiter-code [NOTIZ]          neuen Kursleiter-Code erzeugen
    kursleiter-codes                 alle Kursleiter-Codes anzeigen
    kursleiter-entziehen INSTANZ_ID  Kursleiter-Rechte wieder entziehen
    instanzen                        alle Instanzen anzeigen
    kurse                            alle aktiven Kurse anzeigen
    regeln-neu                       Netzregeln neu nach Headscale schreiben
"""

import argparse
import sys
from datetime import datetime

from .config import einstellungen
from .db import Datenbank, jetzt, sha256
from .headscale import Headscale
from .kennungen import code_normalisieren, lesbarer_code
from .regeln import regeln_bauen


def _zeit(sekunden: int | None) -> str:
    if not sekunden:
        return "-"
    return datetime.fromtimestamp(sekunden).strftime("%d.%m.%Y %H:%M")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="admin", description="Verwaltung der Bony-Netz-Zentrale")
    befehle = parser.add_subparsers(dest="befehl", required=True)
    neu = befehle.add_parser("kursleiter-code", help="neuen Kursleiter-Code erzeugen")
    neu.add_argument("notiz", nargs="*", help="z. B. für wen der Code ist")
    befehle.add_parser("kursleiter-codes", help="Kursleiter-Codes anzeigen")
    entziehen = befehle.add_parser("kursleiter-entziehen", help="Kursleiter-Rechte entziehen")
    entziehen.add_argument("instanz_id")
    befehle.add_parser("instanzen", help="Instanzen anzeigen")
    befehle.add_parser("kurse", help="aktive Kurse anzeigen")
    befehle.add_parser("regeln-neu", help="Netzregeln neu setzen")
    args = parser.parse_args(argv)

    eins = einstellungen()
    db = Datenbank(eins.db_pfad)

    if args.befehl == "kursleiter-code":
        code = lesbarer_code(gruppen=3, laenge=4, praefix="KL")
        db.ausfuehren(
            "INSERT INTO kursleiter_codes (code_hash, notiz, erstellt) VALUES (?, ?, ?)",
            sha256(code_normalisieren(code)), " ".join(args.notiz), jetzt(),
        )
        print(f"Neuer Kursleiter-Code: {code}")
        print("Der Code ist einmal verwendbar und wird nur jetzt angezeigt.")

    elif args.befehl == "kursleiter-codes":
        zeilen = db.alle("SELECT * FROM kursleiter_codes ORDER BY erstellt")
        if not zeilen:
            print("Noch keine Kursleiter-Codes.")
        for z in zeilen:
            zustand = f"eingelöst von {z['eingeloest_von']} am {_zeit(z['eingeloest'])}" \
                if z["eingeloest_von"] else "noch nicht eingelöst"
            print(f"{_zeit(z['erstellt'])}  {z['notiz'] or '(ohne Notiz)'}  –  {zustand}")

    elif args.befehl == "kursleiter-entziehen":
        if db.ausfuehren("UPDATE instanzen SET ist_kursleiter = 0 WHERE id = ?", args.instanz_id):
            print(f"Kursleiter-Rechte von {args.instanz_id} entzogen.")
            print("Bestehende Kurse dieser Instanz laufen weiter, bis sie beendet werden.")
        else:
            print("Instanz nicht gefunden.")
            return 1

    elif args.befehl == "instanzen":
        zeilen = db.alle("SELECT * FROM instanzen ORDER BY erstellt")
        print(f"{len(zeilen)} Instanzen")
        for z in zeilen:
            rolle = "Kursleiter" if z["ist_kursleiter"] else ""
            print(f"{z['id']}  {_zeit(z['erstellt'])}  {rolle}")

    elif args.befehl == "kurse":
        zeilen = db.alle(
            "SELECT k.*, (SELECT COUNT(*) FROM teilnahmen t WHERE t.kurs_id = k.id) AS anzahl "
            "FROM kurse k WHERE status != 'beendet' ORDER BY erstellt"
        )
        if not zeilen:
            print("Keine aktiven Kurse.")
        for z in zeilen:
            print(f"{z['id']}  {z['status']:<9} {z['anzahl']:>3} Teilnehmer  "
                  f"{z['name']}  (Kursleiter: {z['kursleiter_name']})")

    elif args.befehl == "regeln-neu":
        Headscale(eins.headscale_url, eins.headscale_api_key).regeln_setzen(regeln_bauen(db))
        print("Netzregeln neu gesetzt.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
