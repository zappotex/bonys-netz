# SPDX-License-Identifier: GPL-3.0-or-later
"""SQLite-Datenbank der Zentrale.

Gespeichert wird nur das Nötigste: Instanzen (ohne Namen oder E-Mail),
Kursleiter-Codes (nur als Hash), Kurse und Kursteilnahmen, das Kurspaket eines Kurses (Angaben; die Datei liegt
daneben) und der Fortschritt darin (Lektion, geschafft / noch nicht).
"""

import hashlib
import sqlite3
import threading
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS instanzen (
    id              TEXT PRIMARY KEY,
    hs_user_id      TEXT NOT NULL,
    hs_user_name    TEXT NOT NULL UNIQUE,
    token_hash      TEXT NOT NULL UNIQUE,
    ist_kursleiter  INTEGER NOT NULL DEFAULT 0,
    ip_hash         TEXT NOT NULL,
    erstellt        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kursleiter_codes (
    code_hash       TEXT PRIMARY KEY,
    notiz           TEXT NOT NULL DEFAULT '',
    eingeloest_von  TEXT,
    erstellt        INTEGER NOT NULL,
    eingeloest      INTEGER
);

CREATE TABLE IF NOT EXISTS kurse (
    id              TEXT PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,
    kursleiter      TEXT NOT NULL REFERENCES instanzen(id) ON DELETE CASCADE,
    kursleiter_name TEXT NOT NULL,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL,          -- offen | laeuft | pausiert | beendet
    code_gueltig_bis INTEGER NOT NULL,
    erstellt        INTEGER NOT NULL,
    beendet         INTEGER
);

CREATE TABLE IF NOT EXISTS teilnahmen (
    kurs_id         TEXT NOT NULL REFERENCES kurse(id) ON DELETE CASCADE,
    instanz_id      TEXT NOT NULL REFERENCES instanzen(id) ON DELETE CASCADE,
    geraet_id       TEXT NOT NULL,
    geraet_name     TEXT NOT NULL,
    geraet_ip       TEXT NOT NULL,
    anzeigename     TEXT NOT NULL,
    beigetreten     INTEGER NOT NULL,
    PRIMARY KEY (kurs_id, instanz_id)
);

-- Kurspaket eines Kurses (die Datei liegt in KURSPAKET_ORDNER/<kurs_id>.bonyspaket); gelöscht beim Beenden
CREATE TABLE IF NOT EXISTS kurspakete (
    kurs_id         TEXT PRIMARY KEY REFERENCES kurse(id) ON DELETE CASCADE,
    paket_id        TEXT NOT NULL,
    name            TEXT NOT NULL,
    version         TEXT NOT NULL,
    lektionen       INTEGER NOT NULL,
    sha256          TEXT NOT NULL,
    groesse         INTEGER NOT NULL,
    hochgeladen     INTEGER NOT NULL
);

-- Fortschritt im Kurspaket: nur Lektion und „geschafft / noch nicht“ – keine Inhalte; gelöscht beim Beenden
CREATE TABLE IF NOT EXISTS fortschritt (
    kurs_id         TEXT NOT NULL,
    instanz_id      TEXT NOT NULL,
    lektion         INTEGER NOT NULL,
    geschafft       INTEGER,                -- 1 geschafft, 0 noch nicht, NULL keine Prüfaufgabe / nicht geprüft
    aktualisiert    INTEGER NOT NULL,
    PRIMARY KEY (kurs_id, instanz_id),
    FOREIGN KEY (kurs_id, instanz_id) REFERENCES teilnahmen(kurs_id, instanz_id) ON DELETE CASCADE
);
"""


def jetzt() -> int:
    return int(time.time())


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Datenbank:
    def __init__(self, pfad: str) -> None:
        self._verbindung = sqlite3.connect(pfad, check_same_thread=False, isolation_level=None)
        self._verbindung.row_factory = sqlite3.Row
        self._verbindung.execute("PRAGMA foreign_keys = ON")
        self._verbindung.execute("PRAGMA journal_mode = WAL")
        self._verbindung.executescript(SCHEMA)
        # Eine Sperre für alles: Die Zentrale hat wenig Last, so bleibt es einfach und sicher.
        self.sperre = threading.RLock()

    @contextmanager
    def transaktion(self):
        with self.sperre:
            self._verbindung.execute("BEGIN")
            try:
                yield self._verbindung
                self._verbindung.execute("COMMIT")
            except BaseException:
                self._verbindung.execute("ROLLBACK")
                raise

    def eins(self, sql: str, *werte) -> sqlite3.Row | None:
        with self.sperre:
            return self._verbindung.execute(sql, werte).fetchone()

    def alle(self, sql: str, *werte) -> list[sqlite3.Row]:
        with self.sperre:
            return self._verbindung.execute(sql, werte).fetchall()

    def ausfuehren(self, sql: str, *werte) -> int:
        with self.sperre:
            return self._verbindung.execute(sql, werte).rowcount
