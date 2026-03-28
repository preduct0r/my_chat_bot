# Yandex Cloud Serverless Migration Plan

## Goal

Move the HTTPS chat experience to Yandex Cloud Functions with YDB-backed memory, while keeping the transport layer thin and preserving tested memory behavior.

## Constraints

- Telegram is not part of the target runtime path.
- Cloud Functions do not preserve local disk state between invocations in a way suitable for memory storage.
- Yandex Cloud Functions strips the `Cookie` request header.
- The project must remain test-covered during the migration.

## Plan

1. Create repository-local architecture docs and an execution plan.
2. Refactor the web transport into a reusable request/response handler.
3. Replace browser cookie session handling with explicit session token headers.
4. Add a YDB-backed memory repository compatible with `MemoryService`.
5. Add a Yandex Cloud Functions `handler(event, context)` entrypoint.
6. Update local web serving so it reuses the same handler abstraction.
7. Extend automated tests for request routing, session handling, and serverless integration seams.
8. Update README and deployment instructions for Yandex Cloud.

## Risks

- YDB adapter correctness without live integration tests.
- Latency increase if opportunistic summarization runs too often.
- Hidden coupling to SQLite row semantics in the current memory service.

## Definition of done

- HTTPS flow works through a serverless handler.
- Persistent memory no longer depends on SQLite in the serverless path.
- Session identity works without cookies.
- New behavior has automated tests.
- Repository docs explain the target runtime and tradeoffs.
