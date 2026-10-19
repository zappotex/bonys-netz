#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# =============================================================================
#  Bony-Netz-Server – Installation und Aktualisierung
#
#  Richtet auf einem Debian- oder Ubuntu-Server alles ein, was Bony's Agents
#  für das Bony-Netz und die Kursräume braucht:
#    Headscale (Netz), LiveKit (Kursräume), Zentrale (Anmeldedienst), Caddy (HTTPS)
#
#  Aufruf:   sudo ./install.sh
#
#  Das Skript kann beliebig oft laufen. Vorhandene Schlüssel, Datenbanken und
#  Einstellungen bleiben erhalten; nur fehlende Teile werden ergänzt und die
#  Programmteile aktualisiert.
# =============================================================================
set -euo pipefail

HEADSCALE_VERSION="${HEADSCALE_VERSION:-0.29.5}"
LIVEKIT_VERSION="${LIVEKIT_VERSION:-latest}"
ZIEL="${ZIEL:-/opt/bonynet}"
QUELLE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

gruen() { printf '\033[32m%s\033[0m\n' "$*"; }
gelb()  { printf '\033[33m%s\033[0m\n' "$*"; }
rot()   { printf '\033[31m%s\033[0m\n' "$*" >&2; }
schritt() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
abbruch() { rot "Fehler: $*"; exit 1; }

# -----------------------------------------------------------------------------
schritt "Voraussetzungen prüfen"
# -----------------------------------------------------------------------------
[ "$(id -u)" -eq 0 ] || abbruch "Bitte mit sudo starten: sudo ./install.sh"
. /etc/os-release
case "${ID:-}" in
  debian|ubuntu) gruen "System: $PRETTY_NAME" ;;
  *) abbruch "Unterstützt werden Debian und Ubuntu. Gefunden: ${PRETTY_NAME:-unbekannt}" ;;
esac

for befehl in curl openssl; do
  command -v "$befehl" >/dev/null || { apt-get update -qq && apt-get install -y -qq curl openssl ca-certificates; break; }
done

if ss -tlnp 2>/dev/null | grep -E ':(80|443) ' | grep -vq docker-proxy; then
  rot "Die Ports 80 oder 443 sind schon von einem anderen Programm belegt:"
  ss -tlnp | grep -E ':(80|443) ' >&2
  abbruch "Bitte dieses Programm zuerst entfernen (zum Beispiel Apache oder Plesk)."
fi

# -----------------------------------------------------------------------------
schritt "Docker"
# -----------------------------------------------------------------------------
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  gelb "Docker fehlt. Installiere Docker aus der offiziellen Docker-Paketquelle ..."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/${ID}/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/${ID}
Suites: ${VERSION_CODENAME}
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    usermod -aG docker "$SUDO_USER"
    gelb "Benutzer $SUDO_USER darf jetzt Docker nutzen (nach erneutem Anmelden)."
  fi
fi
gruen "$(docker --version)"

# -----------------------------------------------------------------------------
schritt "Einstellungen"
# -----------------------------------------------------------------------------
mkdir -p "$ZIEL"
EINSTELLUNGEN="$ZIEL/bonynet.env"
# shellcheck disable=SC1090
[ -f "$EINSTELLUNGEN" ] && . "$EINSTELLUNGEN"

ip_erkennen() {
  ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") print $(i+1)}'
}

frage() {  # frage VARIABLE "Text" "Vorschlag"
  local var="$1" text="$2" vorschlag="$3" antwort
  if [ -n "${!var:-}" ]; then vorschlag="${!var}"; fi
  if [ "${OHNE_FRAGEN:-0}" = "1" ]; then
    antwort="$vorschlag"
  else
    read -r -p "$text [$vorschlag]: " antwort </dev/tty || true
    antwort="${antwort:-$vorschlag}"
  fi
  [ -n "$antwort" ] || abbruch "$text darf nicht leer sein."
  case "$antwort" in *"'"*|*'"'*|*' '*) abbruch "$text darf keine Leerzeichen oder Anführungszeichen enthalten." ;; esac
  printf -v "$var" '%s' "$antwort"
}

echo "Drei Namen müssen per DNS-A-Eintrag auf diesen Server zeigen."
frage VPN_DOMAIN       "Adresse des Netzes (Headscale)"      "vpn.example.de"
BASIS="${VPN_DOMAIN#*.}"
frage KURS_DOMAIN      "Adresse der Kursräume (LiveKit)"     "kurs.$BASIS"
frage ZENTRALE_DOMAIN  "Adresse der Zentrale"                "zentrale.$BASIS"
frage NETZ_DOMAIN      "Interner Namensraum der Geräte"      "netz.$BASIS"
frage OEFFENTLICHE_IP  "Öffentliche IPv4-Adresse des Servers" "$(ip_erkennen)"
frage SERVER_NAME      "Anzeigename des Servers (ohne Leerzeichen)" "Bony-Netz"

[ "$NETZ_DOMAIN" != "$BASIS" ] || abbruch "Der interne Namensraum darf nicht $BASIS selbst sein."
case "$VPN_DOMAIN" in *".$NETZ_DOMAIN"|"$NETZ_DOMAIN") abbruch "Die Netz-Adresse darf nicht im internen Namensraum liegen." ;; esac

cat > "$EINSTELLUNGEN" <<EOF
# Antworten aus install.sh – werden beim nächsten Lauf als Vorschlag benutzt.
VPN_DOMAIN='$VPN_DOMAIN'
KURS_DOMAIN='$KURS_DOMAIN'
ZENTRALE_DOMAIN='$ZENTRALE_DOMAIN'
NETZ_DOMAIN='$NETZ_DOMAIN'
OEFFENTLICHE_IP='$OEFFENTLICHE_IP'
SERVER_NAME='$SERVER_NAME'
EOF
chmod 600 "$EINSTELLUNGEN"

for name in "$VPN_DOMAIN" "$KURS_DOMAIN" "$ZENTRALE_DOMAIN"; do
  aufgeloest="$(getent ahostsv4 "$name" | awk 'NR==1{print $1}')"
  if [ "$aufgeloest" = "$OEFFENTLICHE_IP" ]; then
    gruen "DNS ok: $name -> $aufgeloest"
  else
    gelb "Achtung: $name zeigt auf '${aufgeloest:-nichts}', nicht auf $OEFFENTLICHE_IP."
    gelb "         Ohne richtigen DNS-Eintrag bekommt Caddy kein Zertifikat."
  fi
done

# -----------------------------------------------------------------------------
schritt "Dateien anlegen"
# -----------------------------------------------------------------------------
cd "$ZIEL"
mkdir -p headscale/config headscale/data caddy/data caddy/config livekit zentrale-daten

ersetzen() {  # ersetzen VORLAGE ZIEL
  sed -e "s|@@VPN_DOMAIN@@|$VPN_DOMAIN|g" \
      -e "s|@@KURS_DOMAIN@@|$KURS_DOMAIN|g" \
      -e "s|@@ZENTRALE_DOMAIN@@|$ZENTRALE_DOMAIN|g" \
      -e "s|@@NETZ_DOMAIN@@|$NETZ_DOMAIN|g" \
      -e "s|@@OEFFENTLICHE_IP@@|$OEFFENTLICHE_IP|g" \
      -e "s|@@HEADSCALE_VERSION@@|$HEADSCALE_VERSION|g" \
      -e "s|@@LIVEKIT_VERSION@@|$LIVEKIT_VERSION|g" \
      -e "s|@@LIVEKIT_KEY@@|${LIVEKIT_KEY:-}|g" \
      -e "s|@@LIVEKIT_SECRET@@|${LIVEKIT_SECRET:-}|g" \
      "$QUELLE/vorlagen/$1" > "$2"
}

# Headscale-Konfiguration: nur beim ersten Mal (enthält nichts Geheimes, aber
# eigene Anpassungen sollen erhalten bleiben).
if [ ! -f headscale/config/config.yaml ]; then
  ersetzen headscale-config.yaml.vorlage headscale/config/config.yaml
  gruen "Headscale-Konfiguration angelegt"
else
  gelb "Headscale-Konfiguration vorhanden – bleibt unverändert"
fi

# LiveKit-Zugang: nur beim ersten Mal erzeugen
if [ ! -f livekit/zugang.env ]; then
  printf 'LIVEKIT_KEY=bony%s\nLIVEKIT_SECRET=%s\n' "$(openssl rand -hex 6)" "$(openssl rand -hex 32)" > livekit/zugang.env
  gruen "LiveKit-Zugang erzeugt"
fi
chmod 600 livekit/zugang.env
# shellcheck disable=SC1091
. livekit/zugang.env
if [ ! -f livekit/livekit.yaml ]; then
  ersetzen livekit.yaml.vorlage livekit/livekit.yaml
  gruen "LiveKit-Konfiguration angelegt"
else
  gelb "LiveKit-Konfiguration vorhanden – bleibt unverändert"
fi

# Geheimnisse der Zentrale: nur beim ersten Mal
if [ ! -f zentrale-geheim.env ]; then
  printf 'ZENTRALE_SALZ=%s\n' "$(openssl rand -hex 32)" > zentrale-geheim.env
fi
chmod 600 zentrale-geheim.env

# Grenzen gegen Missbrauch: nur beim ersten Mal, danach frei anpassbar
if [ ! -f zentrale-grenzen.env ]; then
  cat > zentrale-grenzen.env <<EOF
# Grenzen gegen Missbrauch. Nach einer Änderung: docker compose up -d zentrale
MAX_INSTANZEN_PRO_IP_TAG=3
MAX_GERAETE_PRO_INSTANZ=10
MAX_AKTIVE_KURSE_PRO_KURSLEITER=5
MAX_TEILNEHMER_PRO_KURS=49
KURSCODE_GUELTIG_TAGE_MAX=60
MAX_KURSPAKET_MB=25
EOF
fi

# Öffentliche Einstellungen der Zentrale: jedes Mal neu
cat > zentrale-oeffentlich.env <<EOF
SERVER_NAME=$SERVER_NAME
VPN_PUBLIC_URL=https://$VPN_DOMAIN
KURS_PUBLIC_URL=wss://$KURS_DOMAIN
EOF

# Programmteile: jedes Mal aktualisieren
ersetzen Caddyfile.vorlage caddy/Caddyfile
ersetzen docker-compose.yml.vorlage docker-compose.yml
rm -rf zentrale
cp -r "$QUELLE/zentrale" zentrale
rm -rf zentrale/tests zentrale/__pycache__ zentrale/app/__pycache__
chown -R 10001:10001 zentrale-daten
# Konfiguration gehört dem Benutzer, der sudo aufgerufen hat, damit er
# docker compose ohne sudo benutzen kann. Die Datenordner bleiben bei Docker.
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
  chown "$SUDO_USER": "$ZIEL" bonynet.env docker-compose.yml caddy caddy/Caddyfile \
    headscale headscale/config livekit zentrale-geheim.env zentrale-oeffentlich.env \
    zentrale-grenzen.env
  chown -R "$SUDO_USER": headscale/config livekit zentrale
fi
gruen "Dateien aktuell"

# -----------------------------------------------------------------------------
schritt "System anpassen"
# -----------------------------------------------------------------------------
# Größere UDP-Puffer für Bild und Ton in den Kursräumen
printf 'net.core.rmem_max = 5000000\nnet.core.wmem_max = 5000000\n' > /etc/sysctl.d/90-livekit.conf
sysctl -q --system >/dev/null 2>&1 || true

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp   comment 'Caddy HTTP'      >/dev/null
  ufw allow 443/tcp  comment 'Caddy HTTPS'     >/dev/null
  ufw allow 3478/udp comment 'Headscale STUN'  >/dev/null
  ufw allow 7881/tcp comment 'LiveKit TCP'     >/dev/null
  ufw allow 7882/udp comment 'LiveKit UDP'     >/dev/null
  gruen "Firewall (ufw) ergänzt"
fi

# -----------------------------------------------------------------------------
schritt "Dienste starten"
# -----------------------------------------------------------------------------
docker compose pull -q headscale caddy livekit
docker compose up -d headscale caddy livekit

echo -n "Warte auf Headscale "
for _ in $(seq 1 30); do
  if docker exec headscale headscale users list >/dev/null 2>&1; then echo; break; fi
  echo -n "."; sleep 2
done
docker exec headscale headscale users list >/dev/null 2>&1 || abbruch "Headscale startet nicht. Logs: docker compose logs headscale"

if ! grep -q '^HEADSCALE_API_KEY=' zentrale-geheim.env; then
  schluessel="$(docker exec headscale headscale apikeys create --expiration 3650d | tail -n 1 | tr -d '\r')"
  case "$schluessel" in
    hskey-api-*) printf 'HEADSCALE_API_KEY=%s\n' "$schluessel" >> zentrale-geheim.env ;;
    *) abbruch "Headscale-API-Schlüssel konnte nicht erzeugt werden: $schluessel" ;;
  esac
  gruen "Zugang der Zentrale zu Headscale eingerichtet"
fi

docker compose up -d --build zentrale
docker compose restart caddy >/dev/null

echo -n "Warte auf die Zentrale "
for _ in $(seq 1 45); do
  if curl -fsS "https://$ZENTRALE_DOMAIN/health" >/dev/null 2>&1; then echo; break; fi
  echo -n "."; sleep 2
done

# -----------------------------------------------------------------------------
schritt "Ergebnis"
# -----------------------------------------------------------------------------
pruefen() {  # pruefen NAME URL
  if curl -fsS --max-time 10 "$2" >/dev/null 2>&1; then gruen "  ok      $1  ($2)"; else rot "  FEHLER  $1  ($2)"; fi
}
pruefen "Netz (Headscale)"    "https://$VPN_DOMAIN/health"
pruefen "Kursräume (LiveKit)" "https://$KURS_DOMAIN"
pruefen "Zentrale"            "https://$ZENTRALE_DOMAIN/health"

cat <<EOF

In Bony's Agents trägst du als Server ein:
    https://$ZENTRALE_DOMAIN

Kursleiter-Code erzeugen:
    cd $ZIEL && docker compose exec zentrale python -m app.admin kursleiter-code "Notiz"

Weitere Verwaltungsbefehle:
    cd $ZIEL && docker compose exec zentrale python -m app.admin --help

Bei einem Fehler oben helfen die Logs weiter:
    cd $ZIEL && docker compose logs --tail 50

Bitte in der Firewall deines Anbieters diese Ports freigeben:
    80/tcp, 443/tcp, 3478/udp, 7881/tcp, 7882/udp
EOF
