# My Chat Bot

Простой Telegram-бот на Python с OpenAI API.

## Что умеет

- принимает текстовые сообщения из Telegram
- принимает фото
- принимает PDF
- принимает DOC и DOCX
- принимает XLSX
- принимает текстовые файлы, например `.txt`, `.md`, `.json`, `.csv`, `.py`
- отправляет их в OpenAI API
- хранит persistent memory между сессиями
- использует SQLite как централизованное хранилище памяти
- подает в текущий ответ только последние `N` реплик активной сессии
- суммаризирует завершенные диалоги после периода неактивности
- читает креды из `.env`
- пишет понятные логи для отладки

## Работа через uv

1. Создайте окружение и установите проект:

```bash
uv sync
```

2. Скопируйте `.env.example` в `.env`.
3. Заполните:
   - `TELEGRAM_BOT_TOKEN`
   - `OPENAI_API_KEY`
   - `OPENAI_MODEL`  
     Для работы с фото и PDF лучше использовать multimodal-модель, например `gpt-4o-mini`.
4. Запустите бота:

```bash
uv run my-chat-bot --context-size 10 --summary-count 3 --memory-budget 1200 --memory-db-path data/bot_memory.sqlite3
```

## Параметры запуска

- `--context-size` — сколько последних реплик активной сессии попадает в текущий ответ
- `--summary-count` — сколько последних суммаризаций прошлых диалогов можно включать в prompt
- `--memory-budget` — примерный токен-бюджет для блока `personal memory + summaries`
- `--session-timeout-seconds` — через сколько секунд неактивности диалог считается завершенным
- `--memory-db-path` — путь до SQLite-файла с persistent memory
- `--env-file` — путь до `.env`, по умолчанию `.env`
- `--poll-timeout` — таймаут long polling Telegram в секундах
- `--log-level` — уровень логирования

## Тесты

```bash
uv run python -m unittest discover -s tests -v
```

## Ограничения текущей версии

- вложения поддерживаются только в форматах: изображения, PDF, DOC, DOCX, XLSX и текстовые файлы
- SQLite рассчитан на один инстанс бота; для multi-instance сценария позже лучше перейти на Postgres
- long-term memory суммаризирует текстовую часть диалога и текстовые описания вложений, но не повторно анализирует сами старые файлы

## Полезные команды

```bash
uv run my-chat-bot --help
uv run python -m unittest discover -s tests -v
```
