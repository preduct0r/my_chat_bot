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
- поддерживает второй вход через web-форму
- может делить память между web и Telegram через linking-код
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

### Web-сервер

```bash
uv run my-chat-bot-web \
  --context-size 15 \
  --summary-count 5 \
  --memory-budget 2000 \
  --memory-db-path data/bot_memory.sqlite3 \
  --host 127.0.0.1 \
  --port 8081
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

У web-сервера дополнительно есть:

- `--host` — адрес биндинга HTTP-сервера
- `--port` — локальный порт web-сервера
- `--static-dir` — директория со статикой React-страницы

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
uv run my-chat-bot-web --help
uv run python -m unittest discover -s tests -v
```

## Web + Telegram

В проекте теперь есть два transport-канала:

- Telegram-бот
- web-форма

Они используют одну и ту же модель памяти.

Как работает память:

- если пользователь просто открывает web-страницу, для него создается отдельный web-user со своей памятью
- если пользователь хочет общую память с Telegram, он пишет боту `/link`
- бот выдает одноразовый код на 10 минут
- этот код вводится в web-форме
- после этого web начинает использовать ту же память, что и соответствующий Telegram-пользователь

### Что добавлено

- web backend: [my_chat_bot/web_server.py](/Users/den/projects/pets/my_chat_bot/my_chat_bot/web_server.py)
- web entrypoint: [my_chat_bot/web_main.py](/Users/den/projects/pets/my_chat_bot/my_chat_bot/web_main.py)
- React-страница: [web/index.html](/Users/den/projects/pets/my_chat_bot/web/index.html)
- React-клиент: [web/app.js](/Users/den/projects/pets/my_chat_bot/web/app.js)

## Запуск web через launchd

Скрипты:

- [scripts/run_web_launchd.sh](/Users/den/projects/pets/my_chat_bot/scripts/run_web_launchd.sh)
- [scripts/install_web_launch_agent.sh](/Users/den/projects/pets/my_chat_bot/scripts/install_web_launch_agent.sh)
- [scripts/uninstall_web_launch_agent.sh](/Users/den/projects/pets/my_chat_bot/scripts/uninstall_web_launch_agent.sh)
- [launchd/com.den.my-chat-bot-web.plist.template](/Users/den/projects/pets/my_chat_bot/launchd/com.den.my-chat-bot-web.plist.template)

Установка:

```bash
chmod +x scripts/run_web_launchd.sh scripts/install_web_launch_agent.sh scripts/uninstall_web_launch_agent.sh
./scripts/install_web_launch_agent.sh
```

Проверка:

```bash
launchctl print gui/$(id -u)/com.den.my-chat-bot-web
tail -f logs/web.stdout.log
tail -f logs/web.stderr.log
```

## HTTPS для `thefem.ru`

Чтобы не было предупреждений в браузере, нужен настоящий TLS-сертификат. Для этого в репозитории подготовлен [Caddyfile](/Users/den/projects/pets/my_chat_bot/Caddyfile) под:

- домен: `thefem.ru`
- redirect: `www.thefem.ru` -> `thefem.ru`
- email для ACME: `preductor@gmail.com`

Локальный web backend слушает:

- `127.0.0.1:8081`

А `Caddy` должен принимать внешний HTTPS на 80/443 и проксировать трафик в локальный web backend.

### Важно для реального HTTPS

Нужно, чтобы:

- `thefem.ru` и `www.thefem.ru` указывали на ваш внешний IP
- на роутере были проброшены порты `80` и `443` на ваш Mac
- `Caddy` был установлен на macOS
- `Caddy` был запущен с правами, позволяющими слушать `80/443`

Запуск `Caddy`:

```bash
chmod +x scripts/run_caddy_https.sh
sudo ./scripts/run_caddy_https.sh
```

Файл запуска:

- [scripts/run_caddy_https.sh](/Users/den/projects/pets/my_chat_bot/scripts/run_caddy_https.sh)

Если DNS и порты настроены правильно, `Caddy` сам получит валидный сертификат через Let's Encrypt, и сайт будет открываться по `https://thefem.ru` без предупреждений.

## Автозапуск на macOS через launchd

Для локального запуска на MacBook самый простой вариант — `launchd + uv`.

Что это дает:

- бот стартует автоматически после логина пользователя
- `launchd` перезапускает процесс, если он завершился с ошибкой
- после пробуждения Mac процесс продолжает работать в рамках пользовательской сессии

Важно:

- во время sleep бот не работает
- после пробуждения он либо продолжит выполнение, либо будет перезапущен `launchd`, если процесс завершился

Файлы:

- скрипт запуска: [scripts/run_bot_launchd.sh](/Users/den/projects/pets/my_chat_bot/scripts/run_bot_launchd.sh)
- installer: [scripts/install_launch_agent.sh](/Users/den/projects/pets/my_chat_bot/scripts/install_launch_agent.sh)
- uninstaller: [scripts/uninstall_launch_agent.sh](/Users/den/projects/pets/my_chat_bot/scripts/uninstall_launch_agent.sh)
- шаблон LaunchAgent: [launchd/com.den.my-chat-bot.plist.template](/Users/den/projects/pets/my_chat_bot/launchd/com.den.my-chat-bot.plist.template)

Установка:

```bash
chmod +x scripts/run_bot_launchd.sh scripts/install_launch_agent.sh scripts/uninstall_launch_agent.sh
./scripts/install_launch_agent.sh
```

Проверка:

```bash
launchctl print gui/$(id -u)/com.den.my-chat-bot
tail -f logs/launchd.stdout.log
tail -f logs/launchd.stderr.log
```

Перезапуск агента:

```bash
launchctl kickstart -k gui/$(id -u)/com.den.my-chat-bot
```

Удаление:

```bash
./scripts/uninstall_launch_agent.sh
```

Если захотите поменять параметры запуска бота для `launchd`, отредактируйте блок `EnvironmentVariables` в [launchd/com.den.my-chat-bot.plist.template](/Users/den/projects/pets/my_chat_bot/launchd/com.den.my-chat-bot.plist.template) и снова выполните:

```bash
./scripts/install_launch_agent.sh
```
