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

## Phase 2

- **Admin token is a static shared secret** (`ADMIN_TOKEN`), compared
  directly, rather than a JWT with an `audit:admin` scope. `/audit/verify`
  (phase 4) is an internal operational endpoint, not part of the
  customer/agent delegation model this project demonstrates, so a second
  JWT-issuing path for it would add complexity without adding anything to
  show.
- **Token exchange grant (RFC 8693):** `POST /auth/token` supports three
  grants - `password` (full customer scopes), `client_credentials` (agent
  scopes) and `urn:ietf:params:oauth:grant-type:token-exchange` (narrows a
  customer's own token to their scopes minus `transfers:confirm`, stamping
  `azp=<agent_client_id>`). `make login` performs the password grant and
  then the exchange, so the token that ever reaches the MCP server/agent
  can never carry `transfers:confirm` - this is the concrete mechanism
  behind "a customer token without confirm scope" in section 6.
- **Masking test caught a real leak:** the seed data originally built each
  transaction's `reference` as `TXN-{account_number}-{n}`, which put the
  full 12-digit account number into every transaction response. The
  "no 12-digit sequence anywhere" test (section 9) failed against it
  immediately. Fixed by generating references from a random UUID instead
  of the account number. Worth calling out in the interview: this is
  exactly the kind of leak that's invisible until something **tests for the
  masking property itself**, not just for the masked fields' existence.

## Phase 3 (to be filled in as built)

## Phase 4 (to be filled in as built)
