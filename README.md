# bolmate-api-controller

Centralised storage and refresh of bol.com API tokens.

Every Bolmate service that talks to the bol API gets its bearer token through this library
instead of refreshing on its own. Refreshes for a given API key are serialised **across
processes and across servers** using a database row lock, so concurrent callers cannot
race each other into duplicate refreshes and invalidate each other's tokens.

Requires Python 3.13+.

## Installation

The repository is private, so this is not installable directly from its URL. Build a wheel
and distribute that instead.

From a checkout of this repository, with the build tooling installed:

```
pip install -e '.[dev]'
python -m build
```

That writes `dist/bolmate_api_controller-<version>-py3-none-any.whl`. Install it in the
consuming service:

```
pip install bolmate_api_controller-<version>-py3-none-any.whl
```

Bump `version` in `pyproject.toml` before building, otherwise consumers cannot tell two
wheels apart and `pip install` will consider an already-installed copy up to date.

## Usage

```python
from bolmate_api_controller import get_api_key_async, get_api_key_sync

result = await get_api_key_async(api_key_id=api_key_id)
if not result.success:
    log.warning('No usable bol token: %s', result.error)
    return  # do not call the bol API
headers = {'Authorization': f'Bearer {result.api_key.api_bearer}'}
```

The sync entry point is identical:

```python
result = get_api_key_sync(api_key_id=api_key_id)
```

Both take `api_key_id` as a keyword-only argument (`str | UUID`) and return a `Result`.

### `Result`

| Field | Notes |
| --- | --- |
| `success` | The only field that decides whether you have a usable token. |
| `api_key` | The `APIKey`, or `None` when no row matched. Non-`None` whenever `success` is `True`, though the type is `APIKey \| None` — a type checker will still ask you to narrow it. |
| `error` | `ErrorCode` explaining the failure. `None` on success. |
| `exception` | The exception from the last attempt, when one was raised. `None` otherwise. |
| `response_status` | HTTP status of the last response from bol, when a request was made. |
| `response_text` | Body of the last *failing* response, for diagnostics. Always `None` on success — the token response body contains the bearer and is deliberately not retained. |
| `retryable` | Internal to the retry loop. Always `False` on a `Result` you receive; do not branch on it. Use `error` instead. |
| `is_json_response` | Property. Whether `response_text` looks like a JSON document. |

### Interpreting the return value

| `success` | `api_key` | Meaning |
| --- | --- | --- |
| `True` | `APIKey` | The bearer is valid and usable. |
| `False` | `APIKey` | The key exists, but the refresh failed. `api_bearer` is stale or empty and **will be rejected by bol**. Do not use it. |
| `False` | `None` | No API key with that id exists (`API_KEY_NOT_FOUND`). |

The middle case is the one that is easy to get wrong: a non-`None` `api_key` is *not*
by itself a signal that you have a working token. Always check `success`.

A failed refresh is not retried behind your back, so the next call repeats the full attempt
sequence. Nothing is written to the database except in the deactivation case below. See
*Known limitations*.

### `ErrorCode`

Permanent — retrying the same call will fail the same way until something changes outside
this library:

| Code | Cause |
| --- | --- |
| `API_KEY_NOT_FOUND` | No `api_key` row with that id. |
| `REFRESH_EXPIRED` | The OAuth refresh token is missing or past its expiry. The key must be re-authorised with bol. |
| `MISSING_LEGACY_CREDENTIALS` | `use_oauth` is `False` but `key` or `secret` is empty. |
| `API_KEY_DEACTIVATED` | Bol reports the account is no longer active, with no way to revive it. **This one has a side effect:** the row's `status` is set to `'error'` and its stored bearer and refresh credentials are cleared before the `Result` is returned. |
| `UNEXPECTED_RESPONSE` | Bol returned a 4xx that means none of the above. Check `response_status` and `response_text`. |
| `TOO_MANY_REQUESTS` | Bol returned 429 without a `Retry-After` header, so there is no indication of how long to wait. |

Transient — worth retrying later, after a delay:

| Code | Cause |
| --- | --- |
| `MAX_ATTEMPTS` | Every attempt failed with a retryable error (5xx, or 429 with `Retry-After`). `response_status` and `response_text` carry the last one. |
| `EXCEPTION_RAISED` | The last attempt raised — connection error, timeout, malformed response. `exception` holds it. |

`SERVER_ERROR` exists on `ErrorCode` but never reaches a caller: a 5xx is retried inside
the library, and exhausting the attempts surfaces as `MAX_ATTEMPTS` with the 5xx status
still in `response_status`. The same is true of a 429 that carried a `Retry-After`.

### `APIKey`

| Field | Notes |
| --- | --- |
| `api_key_id` | Primary key of the `api_key` row. |
| `api_bearer` | Decrypted bearer token. Send this to bol. |
| `bearer_expires_at` | When the bearer expires. |
| `refresh_token`, `refresh_token_expires_at` | OAuth refresh credentials. |
| `oauth_type` | `'INVOICES'` or `'DATA_INSIGHTS'`; selects which client credentials are used. |
| `use_oauth` | `False` selects the legacy client-credentials flow using `key`/`secret`. |
| `key`, `secret` | Legacy credentials, decrypted. `None` for OAuth keys. |
| `bearer_is_expired` | Property. True within `BEARER_REFRESH_MARGIN` (60s) of expiry. |

## What callers need to know

**This call blocks, and the worst case is long.** Refreshes are serialised per
`api_key_id` by `SELECT ... FOR UPDATE`, and the lock is held for the entire refresh —
including retries. If another server is mid-refresh when you call, you wait for it to
finish. With five attempts at a 30s HTTP timeout, plus any `Retry-After` bol asks for, the
upper bound is minutes, not seconds. Do not call this inside a request handler with a
short timeout without accounting for that.

**Do not cache the bearer yourself.** Call again instead. When the stored bearer is still
valid the call is one indexed `SELECT` and no HTTP request, which is cheap enough to do on
every outbound bol call. Caching past `bearer_expires_at` reintroduces exactly the
duplicate-refresh problem this library exists to prevent.

**Do not call `get_api_key_sync` from async code.** It blocks the event loop for the full
duration of the refresh, lock wait included.

**Concurrency is bounded per process, per flavour.** Each controller module holds its own
`Semaphore(5)`, and they are not shared. A process using both entry points can have ten
refreshes in flight, each holding a database connection.

**Rate limiting is process-local.** The limiters in `aio_bol_ratelimit` bound requests from
a single process only. They do not coordinate across servers. The cross-server guarantee
this library provides is per-key serialisation of refreshes — nothing more.

## Configuration

Settings are read from a `config.ini` in the **working directory of the calling service**,
via `pydantic-settings`. All keys are required:

```ini
# Encryption
bolmate_encrypt_secret=
bolmate_encryption_value=
bolmate_encryption_iterations=

# Bol OAuth - invoices
bol_oauth_client_id=
bol_oauth_client_secret=

# Bol OAuth - data insights
bol_oauth_insights_client_id=
bol_oauth_insights_client_secret=

# Bolmate database
bolmate_database_user=
bolmate_database_password=
bolmate_database_name=
bolmate_database_host=
bolmate_database_port=
```

Settings are cached after first load. `config.ini` is gitignored and must never be
committed.

### Explicit database configuration

Services that do not carry the controller's `config.ini` (the Bluemate MCP server keeps its
own configuration format) can set the database connection explicitly at startup instead:

```python
from bolmate_api_controller import configure_database

configure_database(dsn='postgresql://user:password@host:5432/bolmate')
```

`configure_database` accepts either a `dsn` or a prebuilt pg-orm `Credentials` object
(`credentials=`), takes precedence over the `bolmate_database_*` settings for every
subsequent `get_api_key_*` call in the process, and reverts to the settings when called
with no arguments. The remaining settings (encryption, bol OAuth clients) are still read
from `config.ini` or, like any `pydantic-settings` field, from environment variables.

### Database

Reads and writes the `api_key` table, using columns `id`, `api_bearer`,
`bearer_expires_at`, `oauth_refresh_token`, `oauth_refresh_token_expires_at`,
`oauth_type`, `use_oauth`, `key`, `secret`. `api_bearer`, `oauth_refresh_token`, `key` and
`secret` are stored encrypted and decrypted on read. A successful refresh writes back
`api_bearer` and `bearer_expires_at` only. A key bol reports as deactivated is instead
written with `status = 'error'` and its bearer and refresh columns cleared.

The connecting role needs `SELECT` and `UPDATE` on `api_key`, and each call takes an
isolated connection for the lifetime of the transaction.

## How it works

1. Open an isolated, non-autocommitting connection and
   `SELECT ... FROM api_key WHERE id = %s FOR UPDATE`. This blocks if another process —
   on any server — is already refreshing this key.
2. If the stored bearer is still valid, return it. A caller that was queued behind a
   refresh re-reads the row after the lock is released and takes this path, so it gets the
   token the winner just fetched rather than requesting a second one.
3. Otherwise refresh against `login.bol.com/token`, using the OAuth refresh-token flow or
   the legacy client-credentials flow depending on `use_oauth`.
4. On success, write the encrypted bearer and its expiry, then commit and release the lock.
   On failure nothing is written, except when bol reports the key as deactivated: that row
   is marked `status = 'error'` and its credentials cleared, so the next call short-circuits
   instead of repeating a refresh that cannot succeed.

Correctness depends on the transaction running at `READ COMMITTED` (the PostgreSQL
default) so that step 2 observes the committed refresh.

## Known limitations

- **No backoff on persistent failure.** A key that keeps hitting 5xx repeats the full
  five-attempt sequence on every call, holding the row lock throughout. Errors bol reports
  as final (`UNEXPECTED_RESPONSE`, `API_KEY_DEACTIVATED`) stop after the first attempt.
- **Refresh tokens are not rotated.** Only the bearer and its expiry are written back. This
  is deliberate: bol does not rotate refresh tokens on the refresh grant.
- **No lock timeout.** A slow refresh blocks every other caller of that key for its full
  duration.
- **`Retry-After` is assumed to be in seconds**, matching bol's behaviour, rather than the
  HTTP-date form the spec also permits.
