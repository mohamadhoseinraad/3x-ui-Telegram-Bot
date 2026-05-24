FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements-web.txt /app/requirements-web.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements-web.txt schedule

COPY . /app
RUN printf '%s\n' '#!/bin/sh' 'exec python /app/app.py "$@"' > /usr/local/bin/start-web \
    && printf '%s\n' '#!/bin/sh' 'exec python /app/bot.py "$@"' > /usr/local/bin/start-bot \
    && chmod +x /usr/local/bin/start-web /usr/local/bin/start-bot

CMD ["python", "app.py"]