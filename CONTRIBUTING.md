# Mitmachen beim Bony-Netz

Schön, dass du helfen willst!

## Beitragsvereinbarung (CLA) – bitte zuerst lesen

Das Bony-Netz steht unter der **GPL-3.0-or-later** und wird zusätzlich unter **kommerziellen
Lizenzen** angeboten (Doppel-Lizenz). Beiträge kann ich deshalb **nur annehmen, wenn du der
[Beitragsvereinbarung (CLA)](CLA.md) zustimmst**. Sie erlaubt mir, deinen Beitrag auch unter
einer kommerziellen Lizenz weiterzugeben; dein Urheberrecht behältst du, und angenommene
Beiträge bleiben immer auch unter der GPL frei verfügbar.

So stimmst du zu: Schreib in deinen ersten Pull Request den Satz aus Abschnitt 7 der
[CLA.md](CLA.md). Ohne diese Zustimmung kann ich den Pull Request leider nicht übernehmen.

Neue Python-Dateien beginnen mit der Zeile `# SPDX-License-Identifier: GPL-3.0-or-later`.

## Entwicklungsumgebung

```bash
git clone https://github.com/zappotex/bonys-netz
cd bonys-netz
python -m venv .venv && source .venv/bin/activate

# Zentrale
pip install -r server/zentrale/requirements.txt pytest
(cd server/zentrale && python -m pytest -q)

# Baustein (braucht nur die Standardbibliothek)
(cd baustein && python -m pytest -q)

# Installationsskript
shellcheck -S warning server/install.sh
```

## Regeln

- Der Baustein `bony_netz` bleibt bei der Python-Standardbibliothek – er wird in die
  Programmpakete von Bony's Agents und Bony's VPN eingebaut.
- Änderungen an der Schnittstelle der Zentrale immer auch in [API.md](API.md) und im Baustein
  nachziehen, und so, dass ältere App-Versionen weiter funktionieren.
- `install.sh` muss wiederholt laufen können, ohne Schlüssel oder Daten zu verlieren.
- Programme nur aus offiziellen Quellen installieren.
- Kein Code, der Daten ohne Zustimmung nach außen sendet.
- Meldungen für Nutzer auf Deutsch.
- Neue Funktionen bitte mit Tests.
