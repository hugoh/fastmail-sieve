# Fastmail's private API: what we learned

Observed against a real account on 2026-11-22. None of this is documented by
Fastmail and any of it can change; `fastmail-sieve doctor` shows what works.

## Session and hosts

- The session document is at `https://api.fastmail.com/jmap/session`;
  `/.well-known/jmap` answers `302` to it.
- The `apiUrl` in the session is regional, for example
  `https://phl.api.fastmail.com/jmap/api/`, not `api.fastmail.com`. The host
  guard therefore allows `api.fastmail.com` and its subdomains. Pinning it to
  the bare host broke `doctor` once.
- The session `state` is account-wide (`cyrus-...;v-7;...`), not Sieve-specific.

## Sieve methods

- Capability URNs for `using`: `https://www.fastmail.com/dev/rules` and
  `https://www.fastmail.com/dev/user`.
- `SieveBlocks/get` with `ids: ["singleton"]` returns `accountId`, `list`,
  `notFound` and `state`. `state` is an empty string, so there is nothing to
  send as `ifInState` on `SieveBlocks/set`. Writes are protected by re-reading
  just before the write and verifying after it instead.
- The script is `sieveRequire`, `sieveAtStart`, `sieveForBlocked`,
  `sieveAtMiddle`, `sieveForRules` and `sieveAtEnd`; only start, middle and end
  are writable here.
- `Validate/sieve` answers `isValid` and `errorDescription` and has no
  `accountId`. Its parser is stricter than the Sieve spec (keywords must be
  lowercase).

## Credentials

- API tokens cannot read or write the script; a browser session token (`fma1-`)
  plus its cookie is required. It is a full web session.
- The login must reach Fastmail with the `Authorization` header and the
  `Cookie` header together. `requests` drops a hand-set `Cookie` header when it
  follows a redirect, and replaces `Authorization` with `~/.netrc` credentials
  unless an explicit `auth` is given.

## Errors worth handling

- Method-level errors arrive with HTTP 200 as `["error", {"type": ...}, id]`.
  `serverFail`, `serverUnavailable` and `rateLimit` are retried for reads and
  `rateLimit` for writes; `stateMismatch` on a write is reported as "changed
  while you were deciding". These names come from the JMAP spec, not from
  anything Fastmail was seen to return.
