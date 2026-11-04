<!-- Maintained by the `architecture-friction` agent skill. Humans welcome. -->

# Architecture friction

Places where this codebase's structure made a change harder than it should have
been, and the refactors that would relieve them.

This is **not** a bug tracker or a TODO list. Every entry answers one question:
*what would have made a change we actually made easy?*

- `## <a refactor direction>` — states a direction ("rework device locking so it
  can span threads"), not a specific design and not a place. Under it, one dated
  bullet per time that friction was felt.
- An occurrence may sit under several headings if any of those refactors would
  have relieved it. Its `(slug)` is identical in each, so all copies can be
  found and removed together when one lands.
- `## Unfiled` — raw notes captured mid-work, not yet sorted. An unsorted note
  still beats a forgotten one.
- `## Done` — refactors that landed, with dates, so the same friction doesn't
  get re-logged from scratch.

**Three bullets under one heading means the refactor is due.**

Adding an entry costs one line. Please add them.

## Separate the process-wide client registry from the client

- [2026-11-04] (lazy-service-cross-lock) `RPCServer.lazy_service_needed()`
  reaches into every registered client's lock via `has_calls_in_flight()`, and
  has to snapshot-then-iterate to avoid taking two clients' locks at once.
  Partially relieved by `ClientIO`: the lock it reaches now has one job, but the
  server still reaches through the client to ask.
- [2026-11-04] (dead-client-eviction) A disconnected client had to be evicted
  under every key it holds, from two places, because registry identity and
  connection liveness are the same object's business.

## Unfiled

- [2026-11-04] `RPCClient._build_locks` is keyed by `(address, local_server)`
  and never cleaned; one entry leaks per connection built.

## Done

- [2026-11-04] Gave the client's socket ownership a boundary of its own:
  `ClientIO` in `teleprox/client_io.py` owns the socket, the outbox, the wakeup
  pipe and the lazy-server claim. (was: 4 occurrences)
