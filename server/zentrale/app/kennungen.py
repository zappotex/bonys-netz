# SPDX-License-Identifier: GPL-3.0-or-later
"""Erzeugen von Kennungen, Tokens und gut lesbaren Codes."""

import secrets

# Ohne leicht verwechselbare Zeichen wie 0/O, 1/I/L
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def lesbarer_code(gruppen: int = 2, laenge: int = 4, praefix: str = "") -> str:
    teile = ["".join(secrets.choice(_ALPHABET) for _ in range(laenge)) for _ in range(gruppen)]
    code = "-".join(teile)
    return f"{praefix}-{code}" if praefix else code


def code_normalisieren(code: str) -> str:
    """Nimmt Eingaben wie 'ab12 cd34' oder 'AB12-CD34' gleich entgegen."""
    rein = "".join(z for z in code.upper() if z.isalnum())
    return rein


def instanz_id() -> str:
    return "i" + secrets.token_hex(8)


def kurs_id() -> str:
    return "k" + secrets.token_hex(8)


def zugangstoken() -> str:
    return "bz_" + secrets.token_urlsafe(32)
