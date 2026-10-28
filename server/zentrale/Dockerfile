# SPDX-License-Identifier: GPL-3.0-or-later
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --system --uid 10001 zentrale && mkdir -p /data && chown zentrale /data
USER zentrale

EXPOSE 8000
# --no-access-log: keine Zeile je Aufruf (sonst stünden IP-Adressen mit Zeit und Pfad im Protokoll)
CMD ["uvicorn", "app.main:_app_fuer_uvicorn", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
