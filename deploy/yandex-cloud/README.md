# Yandex Cloud Function Deployment

This repository now supports an HTTPS-only serverless deployment path for Yandex Cloud Functions with YDB-backed memory.

## Runtime shape

- Entry point: `my_chat_bot.yandex_function.handler`
- Runtime: Python 3.11 or newer in Yandex Cloud Functions
- Persistence: Managed Service for YDB
- Canonical domain: `thefem.ru`
- Optional redirect domain: `www.thefem.ru`

## Files to upload

- repository source code
- [`deploy/yandex-cloud/requirements.txt`](/Users/den/projects/pets/my_chat_bot/deploy/yandex-cloud/requirements.txt)
- the `web/` directory, because the function serves `index.html` and `app.js`

## Required environment variables

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `YDB_ENDPOINT`
- `YDB_DATABASE`

## Optional environment variables

- `OPENAI_API_URL`
- `OPENAI_SYSTEM_PROMPT`
- `CONTEXT_SIZE`
- `SUMMARY_COUNT`
- `MEMORY_BUDGET`
- `SESSION_TIMEOUT_SECONDS`
- `LOG_LEVEL`
- `STATIC_DIR`

## Important platform notes

- Browser session identity is sent via `X-Session-Token`, not cookies.
- Attach a service account to the function so the YDB SDK can use metadata credentials.
- If the function needs private connectivity to YDB or other resources, place it in an appropriate VPC network according to Yandex Cloud networking guidance.

## Suggested infrastructure split

1. Cloud Function for HTTPS handling.
2. Managed Service for YDB in serverless mode for memory persistence.
3. API Gateway or custom domain mapping so `thefem.ru` is the public host.
4. Redirect `www.thefem.ru` to `thefem.ru` at the edge.
