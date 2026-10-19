# SPDX-License-Identifier: GPL-3.0-or-later
"""Einstellungen der Zentrale. Alles kommt aus Umgebungsvariablen (zentrale.env)."""

import os


def _pflicht(name: str) -> str:
    wert = os.environ.get(name, "").strip()
    if not wert:
        raise RuntimeError(f"Umgebungsvariable {name} fehlt")
    return wert


def _zahl(name: str, standard: int) -> int:
    return int(os.environ.get(name, standard))


class Einstellungen:
    def __init__(self) -> None:
        # Name, der den Apps angezeigt wird
        self.server_name = os.environ.get("SERVER_NAME", "Bony-Netz")

        # Interne Adressen im Docker-Netz
        self.headscale_url = os.environ.get("HEADSCALE_URL", "http://headscale:8080")
        self.headscale_api_key = _pflicht("HEADSCALE_API_KEY")
        self.livekit_url = os.environ.get("LIVEKIT_URL", "http://livekit:7880")
        self.livekit_key = _pflicht("LIVEKIT_KEY")
        self.livekit_secret = _pflicht("LIVEKIT_SECRET")

        # Öffentliche Adressen, die die App benutzt
        self.vpn_public_url = _pflicht("VPN_PUBLIC_URL")          # https://vpn.example.de
        self.kurs_public_url = _pflicht("KURS_PUBLIC_URL")        # wss://kurs.example.de

        # Geheimnis zum Verschleiern von IP-Adressen (nur für Missbrauchsgrenzen)
        self.salz = _pflicht("ZENTRALE_SALZ")

        self.db_pfad = os.environ.get("DB_PFAD", "/data/zentrale.db")
        # Kurspakete der Kurse (.bonyspaket, hochgeladen vom Kursleiter, gelöscht beim Beenden)
        self.kurspaket_ordner = os.environ.get("KURSPAKET_ORDNER") or os.path.join(
            os.path.dirname(self.db_pfad) or ".", "kurspakete")

        # Grenzen gegen Missbrauch
        self.max_instanzen_pro_ip_tag = _zahl("MAX_INSTANZEN_PRO_IP_TAG", 3)
        self.max_geraete_pro_instanz = _zahl("MAX_GERAETE_PRO_INSTANZ", 10)
        self.max_aktive_kurse_pro_kursleiter = _zahl("MAX_AKTIVE_KURSE_PRO_KURSLEITER", 5)
        self.max_teilnehmer_pro_kurs = _zahl("MAX_TEILNEHMER_PRO_KURS", 49)
        self.kurscode_gueltig_tage_max = _zahl("KURSCODE_GUELTIG_TAGE_MAX", 60)
        self.max_kurspaket_mb = _zahl("MAX_KURSPAKET_MB", 25)

        # Laufzeiten
        self.geraeteschluessel_minuten = _zahl("GERAETESCHLUESSEL_MINUTEN", 60)
        self.eintrittskarte_stunden = _zahl("EINTRITTSKARTE_STUNDEN", 6)


_einstellungen: Einstellungen | None = None


def einstellungen() -> Einstellungen:
    global _einstellungen
    if _einstellungen is None:
        _einstellungen = Einstellungen()
    return _einstellungen
