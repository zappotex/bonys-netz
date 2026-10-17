# SPDX-License-Identifier: GPL-3.0-or-later
"""Baut die Headscale-Regeln aus dem Zustand der Datenbank.

Grundregel: Jede Instanz erreicht nur ihre eigenen Geräte.
Zusatz pro laufendem Kurs: Die Geräte des Kursleiters erreichen genau die
Agenten-PCs, die die Teilnehmer für diesen Kurs ausgewählt haben.
Teilnehmer untereinander erreichen sich nicht.
"""

import json

from .db import Datenbank


def regeln_bauen(db: Datenbank) -> str:
    acls: list[dict] = [
        {
            "action": "accept",
            "src": ["autogroup:member"],
            "dst": ["autogroup:self:*"],
        }
    ]

    kurse = db.alle(
        """
        SELECT k.id, i.hs_user_name AS kursleiter_user
        FROM kurse k JOIN instanzen i ON i.id = k.kursleiter
        WHERE k.status = 'laeuft'
        ORDER BY k.id
        """
    )
    for kurs in kurse:
        ziele = sorted(
            {
                f"{t['geraet_ip']}:*"
                for t in db.alle("SELECT geraet_ip FROM teilnahmen WHERE kurs_id = ?", kurs["id"])
            }
        )
        if ziele:
            acls.append(
                {
                    "action": "accept",
                    "src": [f"{kurs['kursleiter_user']}@"],
                    "dst": ziele,
                }
            )

    return json.dumps({"acls": acls}, indent=2)
