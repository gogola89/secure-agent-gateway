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

## Phase 3

- **Business-rule rejections return 422**, not 400 or 403: amount and limit
  violations are a validation failure on the request given the account's
  current state, consistent with Pydantic's own 422s elsewhere in the API.
- **"Available balance" at initiate time subtracts this customer's other
  `pending_confirmation` transfers from that same account**, not just the
  stored `balance_cents`. Otherwise two transfers each individually within
  balance, initiated back to back before either is confirmed, could
  jointly overdraw the account once both are confirmed.
- **A flaky test found a second, more subtle masking bug:** transaction/
  transfer `reference` values were built from `uuid4().hex[:12]` - 12
  hex characters. Roughly 0.7% of the time, a random 12-hex-character
  string is all digits, which the "no 12-digit sequence anywhere" test
  (correctly) flags as indistinguishable from a leaked account number.
  Fixed by shortening these tokens to 10 characters, which makes a
  12-digit run structurally impossible rather than merely unlikely -
  the same category of fix as the phase 2 masking bug, worth keeping in
  mind for any future identifier: don't let a field incidentally reach the
  length of a sensitive one.
- **OTP expiry is checked against `transfer.created_at + OTP_TTL`** read
  from the transfer row itself (not only Redis key TTL), so confirming a
  transfer whose OTP already expired gives a precise `transfer_expired`
  error even if the Redis key happens to still be lingering, and tests can
  simulate expiry deterministically by backdating `created_at` instead of
  sleeping.

## Phase 4

- **`AppError` carries an `audit_reason` separate from the public `code`.**
  The clearest example: an account alias that belongs to another customer
  and one that doesn't exist at all both return the identical public 404,
  but `authz.py` queries (read-only, never changing the response) whether
  the alias exists for *someone else* and logs `not_owner` vs `not_found`
  internally. The audit trail is allowed to be more specific than the API
  response - that asymmetry is the whole point of section 5's anti-
  enumeration requirement.
- **FastAPI's exception handlers run *inside* `call_next`,** so an `AppError`
  raised by a route or dependency never reaches the audit middleware's own
  `try/except` - it's already been turned into a `JSONResponse` by the time
  `call_next` returns. The audit middleware instead reads a `deny_reason`
  that each exception handler stashes on `request.state` before returning
  its response. Worth knowing cold for the interview: middleware added via
  `app.middleware("http")` wraps the *entire* exception-handling stack, not
  just route handlers.
- **Hash-chain appends take a `SELECT ... FOR UPDATE` on the chain tip**
  (the latest row) before computing the new row's `prev_hash`, so concurrent
  requests append in series instead of two requests both reading the same
  tip and forking the chain. This is a real simplification: a
  high-throughput production system would want a dedicated single-writer
  (e.g. a queue consumer) rather than serialising on a row lock per web
  request, but it keeps the demo's hash chain actually correct under the
  concurrency tests in this same phase.
- **The admin token for `/audit/verify` is a separate static secret, not a
  JWT scope** - see the phase 2 note; this is where it's actually used.
- **Rate limiting and idempotency are two different controls and the tests
  must not conflate them.** The spec's idempotency test description uses
  10 concurrent requests; configured at 5 `transfers:initiate` calls/minute
  per agent:customer pair, a literal 10 would be partly testing the rate
  limiter. The test fires exactly `rate_limit_transfers_per_minute`
  concurrent identical requests instead - still proves exactly one transfer
  is created, without the two controls interfering with each other.
- **Tests flush Redis before every test** (`flush_rate_limits_and_otps`
  autouse fixture). Without it the rate limiter's real 60-second window
  would carry state between unrelated tests, since the suite runs against
  real Redis rather than a mock (intentional, per section 9) - this is the
  cost of that choice, paid once in conftest rather than in every test.
