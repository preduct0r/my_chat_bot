# Yandex Cloud Serverless Design

## Why we are changing the architecture

The current implementation assumes:

- a long-lived process for `ThreadingHTTPServer`
- opportunistic maintenance inside a process loop
- SQLite on a local filesystem
- browser session identity stored in cookies

That shape is not a clean fit for Yandex Cloud Functions.

According to Yandex Cloud documentation:

- HTTPS requests arrive in the function as an `event` JSON object with fields such as `httpMethod`, `path`, `headers`, `queryStringParameters`, `body`, and `isBase64Encoded` on invoke.
- The function must return a JSON object with `statusCode`, `headers`, `body`, and `isBase64Encoded`.
- The `Cookie` request header is removed before the function receives the request.
- A common pattern for YDB access from Cloud Functions is using the `ydb` Python SDK plus `MetadataUrlCredentials()` attached to the function service account.

Sources:

- [OpenAI Harness Engineering article](https://openai.com/index/harness-engineering/)
- [Yandex Cloud Functions invoke format](https://yandex.cloud/en/docs/functions/concepts/function-invoke)
- [Yandex Cloud Functions to YDB in Python](https://yandex.cloud/en/docs/tutorials/serverless/connect-from-cf)

## Deployment target

The service will run as an HTTPS-only function behind a custom domain.

- Canonical host: `thefem.ru`
- Optional redirect host: `www.thefem.ru`
- Runtime model: request-scoped execution with warm-start reuse when available
- Persistent state: YDB

## Request model

We will introduce a transport-agnostic request handler with this shape:

1. Parse `method`, `path`, headers, and JSON body from the transport.
2. Resolve or mint a browser session token.
3. Load active memory state from the persistence layer.
4. Process the chat action.
5. Persist the updated state and return JSON.

The local development server and Yandex Cloud Function handler will both call the same application-level handler.

## Session identity model

Because Cloud Functions strips the incoming `Cookie` header, the browser will store the session token in `localStorage` and send it via `X-Session-Token`.

Server behavior:

- If the header is absent, create a new web identity.
- Return the current `sessionToken` in JSON payloads so the browser can persist it.
- Keep session token generation server-side.

## Persistence model

YDB becomes the source of truth for:

- users
- sessions
- messages
- personal memory
- session summaries
- web client identities
- link codes

SQLite remains useful only for local development and tests.

## Maintenance model

There is no always-on process in Cloud Functions, so maintenance must become request-driven or scheduled.

This migration implements request-driven summarization:

- stale session summarization still happens before processing a new user message
- opportunistic expired-session summarization can run at request boundaries

If traffic becomes high or latency-sensitive, the next step is a scheduled cleanup function.

## Test strategy

The migration is not done until the following are covered:

- request translation from Yandex HTTPS `event` to internal request objects
- session token propagation without cookies
- local server compatibility with the new request handler
- repository selection and YDB adapter behavior at the unit level
- regression coverage for existing memory and web flows
