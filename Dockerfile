FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY my_chat_bot /app/my_chat_bot
COPY web /app/web

RUN python -m pip install --no-cache-dir --upgrade pip \
 && python -m pip install --no-cache-dir .

RUN mkdir -p /app/data

EXPOSE 8081
