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

api_key, success = await get_api_key_async(api_key_id=api_key_id)
if not success:
    ...  # no usable token, do not call the bol API
headers = {'Authorization': f'Bearer {api_key.api_bearer}'}
```

The sync entry point is identical:

```python
api_key, success = get_api_key_sync(api_key_id=api_key_id)
```

Both take `api_key_id` as a keyword-only argument (`str | UUID`) and return
`tuple[APIKey | None, bool]`.

### Interpreting the return value

| Result | Meaning |
| --- | --- |
| `(None, False)` | No API key with that id exists. |
| `(APIKey, False)` | The key exists, but the refresh failed. `api_bearer` is stale or empty and **will be rejected by bol**. Do not use it. |
| `(APIKey, True)` | The bearer is valid and usable. |

The middle case is the one that is easy to get wrong: a non-`None` `APIKey` is *not*
by itself a signal that you have a working token. Always check the boolean.

A failed refresh is not retried behind your back and nothing is written to the database,
so the next call repeats the full attempt sequence. See *Known limitations*.

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

### Database

Reads and writes the `api_key` table, using columns `id`, `api_bearer`,
`bearer_expires_at`, `oauth_refresh_token`, `oauth_refresh_token_expires_at`,
`oauth_type`, `use_oauth`, `key`, `secret`. `api_bearer`, `oauth_refresh_token`, `key` and
`secret` are stored encrypted and decrypted on read; only `api_bearer` and
`bearer_expires_at` are written back.

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
   On failure, nothing is written.

Correctness depends on the transaction running at `READ COMMITTED` (the PostgreSQL
default) so that step 2 observes the committed refresh.

## Known limitations

- **No backoff on persistent failure.** A key with revoked or expired credentials repeats
  the full five-attempt sequence on every call, holding the row lock throughout.
- **Refresh tokens are not rotated.** Only the bearer and its expiry are written back. This
  is deliberate: bol does not rotate refresh tokens on the refresh grant.
- **No lock timeout.** A slow refresh blocks every other caller of that key for its full
  duration.
- **`Retry-After` is assumed to be in seconds**, matching bol's behaviour, rather than the
  HTTP-date form the spec also permits.
