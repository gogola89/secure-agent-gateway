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
- **A real concurrency bug surfaced only by running the live demo after the
  test suite passed, not by the test suite itself.** The hash chain used
  `SELECT ... ORDER BY id DESC LIMIT 1 FOR UPDATE` to serialise appends.
  That doesn't work: Postgres only re-checks the *locked row's own*
  current version when a `FOR UPDATE` wait releases - it does not re-run
  the `ORDER BY`/`LIMIT` to notice a brand-new row some other transaction
  just inserted. Two concurrent audit writes could both resolve the same
  "current tip", both compute a new row chained to it, and fork the chain.
  The concurrency *test* (`test_concurrent_identical_requests_create_
  exactly_one_transfer`) happened to pass regardless, because it only
  asserts on the transfer rows, not the audit chain underneath them -
  `/audit/verify` only caught it when checked by hand against the same
  dev database the test suite had just run against. Fixed with a
  transaction-scoped Postgres advisory lock (`pg_advisory_xact_lock`)
  around the whole read-tip-then-insert sequence, which does fully
  serialise it. Lesson worth repeating in the interview: green tests prove
  what they assert, not what they don't - a live run-through of the actual
  demo path is still part of "done".
- **The tamper-detection test corrupting a row it never restored** was the
  same kind of lesson from the other direction: a test that intentionally
  breaks invariants in a shared dev database must put them back, or every
  later run (including a live demo) inherits the damage.

## Phase 5

- **The MCP client is synchronous** (`httpx.Client`, not `AsyncClient`).
  `pybreaker`'s synchronous `CircuitBreaker.call()` and `tenacity`'s
  synchronous retry decorator compose simply with a sync client; FastMCP
  tools can be plain sync functions (it runs them off the event loop
  itself), so there's no async requirement being given up - just
  complexity that this project doesn't need.
- **The circuit breaker only "sees" infrastructure failures as failures.**
  `_raw_call` only raises for 5xx/transport errors; a 4xx is returned
  as an ordinary response and translated to `BankingAPIError` *outside*
  the breaker's tracked call. Otherwise a customer asking about a
  nonexistent account alias (a normal 404) would count toward tripping
  the circuit open - treating an everyday "no" from the API as if the
  whole banking service were down.
- **The token-exchange delegation is the actual code path that makes
  "the agent token never holds `transfers:confirm`" true**, not just a
  claim in the README: `make login` is what performs it, and
  `mcp_server/config.py`'s `CUSTOMER_TOKEN` is always the delegated
  token, never the full one from a raw password grant.
- **Admin token endpoint (`/audit/verify`) authentication tested in
  phase 4, MCP resilience tested here with `respx`** rather than against
  a live server - mocking at the transport level is what makes "GET
  retries 3 times" and "circuit breaker opens after 5 failures"
  deterministic and fast instead of dependent on real timing/network
  behaviour.

## Phase 6

- **Every endpoint declares its possible error status codes** via
  `errors.error_responses(...)` in its route decorator, not just its
  success response. Schemathesis checks "undocumented status code" as a
  real failure, and by default FastAPI only documents the happy path -
  this is what made `status_code_conformance` and
  `response_schema_conformance` pass 180/180 against a live Schemathesis
  run rather than being silently skipped.
- **One Schemathesis finding was a transport-layer artifact, not an API
  bug:** a single fuzzed request triggered `h11`/uvicorn's own
  "Invalid HTTP request received" (`text/plain`, 400) before the request
  ever reached the FastAPI app, so none of this project's exception
  handlers or documented content types apply to it. Verified by hand with
  `curl` that an equivalent request through the app returns the documented
  `application/json` error envelope. Noted rather than "fixed", since
  there's nothing in application code to fix.
- **Contract testing is two separate layers, deliberately:** (1) the CI
  OpenAPI drift check (`make openapi` regenerated vs. the committed file)
  catches any interface change that wasn't deliberately reviewed; (2) the
  `openapi-core`-based tests in `test_contract.py` catch a response that
  drifted from its own documented shape even though the code *compiles*
  and other tests pass on behaviour alone. Schemathesis in CI is a third
  layer: it doesn't know this API's business rules, so it finds things
  neither (1) nor (2) can - undocumented status codes and schema
  violations across inputs nobody wrote a test for by hand.
- **Consumer-driven contract testing (Pact) is the next step**, not
  something this project needed: Pact matters once separate teams own the
  consumer (here, the MCP server/agent) and the provider (the banking
  API) and want the provider's CI to fail if it breaks a contract the
  consumer actually depends on, without either team reading the other's
  code. For a one-person demo repo, schema-based contract testing already
  covers the same risk.
- **Schemathesis in CI (on a clean GitHub-hosted runner, not my laptop)
  found two real 500s and confirmed a third finding was not an app bug:**
  1. A NUL byte anywhere in a request body crashed the **audit write**,
     not the request logic - Postgres's JSONB type categorically rejects
     an embedded NUL byte in text. The real response (say, a clean 400 for
     a bad `grant_type`) was already computed, but `write_audit_row`
     raised afterward trying to store it, and that exception reached
     Starlette's top-level error handler instead of the client ever seeing
     the intended response. Fixed with a recursive sanitizer
     (`audit._sanitize`) stripping NUL bytes from every string field
     before it's ever handed to JSONB or a VARCHAR column - applied to
     `args_masked` *and* to `correlation_id`/`action`, since
     `X-Correlation-ID` is attacker-controlled too.
  2. `transfer_id` was a bare `str` path parameter, so a malformed value
     (a NUL byte, or any non-UUID string) reached the database raw and
     crashed with a DB-level `DataError` instead of a clean 4xx. Fixed by
     typing it as `uuid.UUID`, so FastAPI validates and rejects it with a
     422 before the handler runs - the kind of bug that's invisible until
     something sends genuinely malformed input, which is exactly what a
     fuzzer is for.
  3. One finding (`POST /transfers`, "Undocumented Content-Type", a raw
     `text/plain` "Invalid HTTP request received") was real, but not an
     application bug: an **undeclared** `Idempotency-Key` header let
     Schemathesis generate a value containing a raw control character,
     which is not legal inside an HTTP header line at all - h11/uvicorn
     correctly rejects the request at the protocol level, before it
     reaches the ASGI app. Confirmed by hand with a raw socket sending a
     header value containing `\x00`. The honest fix wasn't to catch
     anything in application code (there's no application code in that
     path) but to *declare* the constraint a real idempotency key always
     satisfies - printable ASCII, 8-128 characters - directly on the
     FastAPI `Header(...)` parameter, via `pattern=`. That both documents
     the real contract in the OpenAPI schema and stops Schemathesis (or
     any other caller) from generating a value that was never valid in
     the first place. All three findings are exactly what section 9's
     "Schemathesis... checks for 5xx errors, schema violations and
     undocumented status codes" is for - this is the step that caught bugs
     the unit test suite, written by the same person who wrote the code,
     structurally could not.
