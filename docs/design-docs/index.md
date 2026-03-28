# Design Docs

This directory contains durable design decisions that the code should reflect.

## Active docs

- [`yandex-cloud-serverless.md`](/Users/den/projects/pets/my_chat_bot/docs/design-docs/yandex-cloud-serverless.md): target runtime model for HTTPS-only deployment on Yandex Cloud Functions with YDB persistence.

## Design rules for this migration

- Prefer explicit request/response boundaries over hidden process state.
- Persist memory outside the function filesystem.
- Make session identity observable and testable.
- Document operational constraints discovered from platform docs inside the repository.
