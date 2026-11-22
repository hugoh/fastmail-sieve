# Decision: not adopting jmapc (yet)

Status: decided 2026-11-22, revisit on the triggers below.
Examined: [jmapc](https://github.com/smkent/jmapc) 0.4.1 (Python 3.11 to 3.14).

## Question

Could jmapc, a JMAP client library, replace the hand-written HTTP and JMAP code
in `src/fastmail_sieve/fastmail/jmap.py`?

## What jmapc offers

- A `Client` built on one `requests.Session`.
- The request envelope (`using`, `methodCalls`) and primary account lookup.
- A cached JMAP session that is dropped when `sessionState` changes.
- Typed models for standard methods (Mailbox, Email, Identity, Thread, ...) and
  typed method errors, with `raise_errors=True` to raise `ClientError`.
- Blob upload and download, server-sent events, Fastmail masked-email methods.

## What this project actually uses

- Three private methods, none of them modelled by jmapc: `SieveBlocks/get`,
  `SieveBlocks/set` and `Validate/sieve`.
- One standard call, `Mailbox/get`, read as plain dicts.
- Everything else in `jmap.py` is ours: bearer token plus cookie, a read/write
  retry policy, a host guard, redirect refusal, size cap, deadline, error text.

So jmapc would replace roughly 60 lines (envelope, account id, session cache,
`Mailbox/get` parsing) and none of the hard parts.

## Spike (2026-11-22, read-only against a real account)

Worked, without monkeypatching:

- `SieveBlocks/get` as a `CustomMethod` subclass returned the same script as our
  client. Method errors came back typed (`InvalidArguments`; `ClientError` with
  `raise_errors=True`).
- `Validate/sieve` worked on a valid script and on garbage.

Needed jmapc internals or workarounds:

1. `CustomMethod.__post_init__` resets the class-level `using` set on every
   instantiation, so our subclass must override it to set the capability URNs
   and the method name. `accountId` is not injected for custom methods; put it
   in `data`.
2. `CustomResponse.from_dict` does `kvs.pop("accountId")`, which raises
   `KeyError` for `Validate/sieve` (its answer has no `accountId`). The way
   round is a `Response` subclass with `method_namespace` and `method_type`,
   which registers itself globally through `__init_subclass__`.
3. The session comes from `/.well-known/jmap`, which answers `302` to
   `/jmap/session`, so jmapc depends on following redirects. We refuse them.
4. Auth is bearer or basic only. A hand-set `Cookie` header is dropped by
   `requests` on redirect (we got a `401`), so the cookie must go into
   `client.requests_session.cookies` with a domain and `Secure`.
5. `apiUrl` from the session is not validated, there is no retry, there is one
   session (so one retry policy) per client, and `raise_for_status()` discards
   Fastmail's problem details.

Not tested: `SieveBlocks/set` (a live write), mounting our retry adapter,
whether `stateMismatch` is a typed error, and jmapc's fixed request timeout.

## What adopting it would need

- Custom method and response classes for the three Sieve methods.
- A cookie-jar shim, a `User-Agent` header, and our `Retry` adapter on
  `requests_session`; two clients, one for reads and one for writes.
- An `HTTPAdapter` subclass whose `send()` checks https and the host on every
  hop, replacing `_check_url` and allowing the `.well-known` redirect safely.
- A wrapper mapping `ClientError`, typed errors and `requests` exceptions back
  to `MethodError` and our messages (401 hint, problem details, busy server).
- A narrow pin (`jmapc>=0.4,<0.5`), like sievelib, and a re-check on every
  upgrade.
- New dependencies: `dataclasses-json` (with `marshmallow` and
  `typing-inspect`), `python-dateutil`, `sseclient` and `brotli`.

## Decision

Do not adopt. The code would shrink very little: the hard parts stay ours and
would be attached to another library's session object through behaviour it does
not promise to keep. That is the internals-patching we want to avoid.

## Revisit when

- We start using standard JMAP methods (more `Mailbox`, `Email`, `Identity`,
  masked email), which jmapc already models.
- jmapc reaches 1.0, or documents its extension points: custom methods and
  responses, cookie or custom auth, session hooks, retry.
- Fastmail advertises the official Sieve capability (`urn:ietf:params:jmap:sieve`,
  RFC 9661, which `doctor` already reports). A library might then model Sieve
  properly, and the private methods could go.
- `jmap.py` grows enough that maintaining the envelope and session code is a
  burden.

## If we revisit

Keep the interface the rest of the code uses: `invoke(credentials, using,
method, arguments)`, `get_session(credentials)`, `MethodError` and its `type`.
Swap the transport on a branch, behind that interface. `tests/support.py` mocks
Fastmail at the HTTP level, so the existing tests are the specification; the
fake needs the `/.well-known/jmap` route and a redirect. Write failing tests
first for the host guard on every hop and for the cookie handling. Merge only if
the diff removes more than it adds in `jmap.py`, the tests pass unchanged, and
`doctor` and a read-only `lint` behave as before on a real account.

To rerun the spike, define the three methods as above and run them with
`uv run --with jmapc`, which leaves `pyproject.toml` and `uv.lock` untouched.
