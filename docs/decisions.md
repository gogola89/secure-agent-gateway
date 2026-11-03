# Decisions

Notes on ambiguous points in the build spec, and the (more secure / simpler)
choice made, per the ground rules in the spec.

## Phase 1

- **Config loading:** plain `os.environ` reads in a frozen dataclass
  (`banking_api/config.py`), not `pydantic-settings` or `python-dotenv`.
  Neither package is in the approved stack (section 3), and the project is
  small enough that explicit env reads are easy to audit. `.env` is loaded
  by Docker Compose's `env_file:` for containers, and by the Makefile
  (`include .env` / `export`) for local commands.
- **DB driver:** `psycopg[binary]` (psycopg 3) with a synchronous SQLAlchemy
  engine. FastAPI endpoints are synchronous too. This keeps the whole API
  in one concurrency model, which is easier to reason about for a project
  this size; nothing here is latency-critical enough to need async DB I/O.
- **UUID/JSON portability:** models use small `TypeDecorator`s (`GUID`,
  `JSONVariant`) so the same models run against Postgres (native `UUID`,
  `JSONB`) and SQLite (`CHAR(36)`, `JSON`) for fast unit tests, per the
  spec's "SQLite allowed for unit tests only".
- **Mock IdP passwords:** a single shared demo password
  (`DEMO_CUSTOMER_PASSWORD`, env-configurable) is used for every seeded
  customer, compared directly with no hashing library. This is explicitly
  a stand-in for Authorization Code + PKCE, never meant to be a real
  authentication mechanism, so adding `passlib`/`bcrypt` for one fixed
  demo string would be unjustified complexity rather than security.
- **docker-compose includes RabbitMQ from phase 1,** even though the outbox
  relay (phase 7) is optional, because the CI workflow (section 9) expects
  Postgres, Redis and RabbitMQ to always be available as services. The
  containers being up costs nothing if phase 7 is skipped.

## Phase 2 (to be filled in as built)

## Phase 3 (to be filled in as built)

## Phase 4 (to be filled in as built)
