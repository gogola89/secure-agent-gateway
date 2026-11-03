# secure-agent-gateway

A prototype of how AI agents can safely access banking systems: narrow
tools, delegated identity, human confirmation, idempotency and
tamper-evident audit. All data is invented; no real bank is involved.

This repo is being built in phases (see `docs/decisions.md` for the design
log). Architecture, security write-up and demo instructions land as the
corresponding phases complete.

## Quick start

```bash
cp .env.example .env
make up      # Postgres, Redis, RabbitMQ + runs migrations
make seed    # idempotent mock customers/accounts/transactions
make test
```

## Status

- [x] Phase 1 - scaffold, Compose, models, migrations, seed, health checks
- [ ] Phase 2 - tokens, scopes, ownership, accounts/transactions, masking
- [ ] Phase 3 - transfers, idempotency, OTP confirmation
- [ ] Phase 4 - audit log hash chain, rate limiting
- [ ] Phase 5 - MCP server
- [ ] Phase 6 - CI, contract testing, docs
- [ ] Phase 7 (optional) - outbox + RabbitMQ relay
- [ ] Phase 8 (optional) - RAG over product documents
