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
- хранит в памяти только последние `N` реплик для каждого чата
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
uv run my-chat-bot --context-size 10
```

## Параметры запуска

- `--context-size` — сколько последних реплик хранить в контексте каждого чата
- `--env-file` — путь до `.env`, по умолчанию `.env`
- `--poll-timeout` — таймаут long polling Telegram в секундах
- `--log-level` — уровень логирования

## Тесты

```bash
uv run python -m unittest discover -s tests -v
```

## Ограничения текущей версии

- вложения поддерживаются только в форматах: изображения, PDF, DOC, DOCX, XLSX и текстовые файлы
- контекст хранится только в памяти процесса и не переживает перезапуск

## Полезные команды

```bash
uv run my-chat-bot --help
uv run python -m unittest discover -s tests -v
```
