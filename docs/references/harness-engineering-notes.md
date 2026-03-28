# Harness Engineering Notes

This file captures the repository-structure takeaways we are applying from OpenAI's `Harness engineering: leveraging Codex in an agent-first world`.

## Practical takeaways we are adopting

- `AGENTS.md` should stay compact and point deeper, instead of becoming a giant instruction dump.
- Architecture and execution plans should be versioned in the repository.
- Plans should be first-class artifacts, not temporary chat output.
- The repository should contain enough durable context that a coding agent can navigate it without hidden tribal knowledge.

## How this affects this repo

- Architecture maps live in markdown next to the code.
- The Yandex Cloud migration is tracked as an execution plan in-repo.
- Platform-specific constraints are documented where future changes can discover them.
