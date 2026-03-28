# Architecture Map

This repository is moving from a mixed `Telegram + local HTTP server` shape to an `HTTPS-first serverless` shape for Yandex Cloud.

The goal of this document is to act as a short map, not an encyclopedia. Deeper design details live in [`docs/design-docs/index.md`](/Users/den/projects/pets/my_chat_bot/docs/design-docs/index.md), while active implementation work is tracked in [`docs/exec-plans/active/yandex-cloud-serverless-migration.md`](/Users/den/projects/pets/my_chat_bot/docs/exec-plans/active/yandex-cloud-serverless-migration.md).

## Repository Knowledge Layout

```text
AGENTS.md
ARCHITECTURE.md
docs/
├── design-docs/
│   ├── index.md
│   └── yandex-cloud-serverless.md
├── exec-plans/
│   └── active/
│       └── yandex-cloud-serverless-migration.md
├── product-specs/
│   └── index.md
└── references/
    └── harness-engineering-notes.md
```

## Current Domains

- `my_chat_bot/openai_client.py`: OpenAI Responses API integration.
- `my_chat_bot/memory.py`: session lifecycle, summarization, and memory orchestration.
- `my_chat_bot/web_server.py`: local HTTP transport used for development and backward compatibility.
- `web/`: browser UI for the HTTPS chat experience.

## Target Domains

- `my_chat_bot/yandex_function.py`: Yandex Cloud Functions HTTPS entrypoint.
- `my_chat_bot/web_transport.py`: transport-agnostic HTTP request/response handling for both local server and Cloud Functions.
- `my_chat_bot/ydb_repository.py`: persistent memory backend for serverless execution.

## Architectural Direction

- Keep transport thin and move HTTP semantics into a reusable handler layer.
- Keep memory orchestration deterministic and observable.
- Replace local SQLite persistence with YDB-backed persistence for serverless deployments.
- Avoid reliance on cookies because Yandex Cloud Functions strips the `Cookie` request header; browser session identity should travel via an explicit session token header.
- Treat tests and docs as first-class migration artifacts, not cleanup work after code lands.
