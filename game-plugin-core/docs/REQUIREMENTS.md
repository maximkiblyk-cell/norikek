# v0.7.0 requirements matrix

VERIFIED = only the described local test, PARTIAL = code exists but requested acceptance is unmet, BLOCKED = missing external dependency/environment, PLANNED = not implemented. No status means game integration or release is complete.

| Requirement | Status | Evidence / gap |
|---|---|---|
| Preserve backend | VERIFIED for supplied archive | 63 source files from v0.6 archive byte-identical; historical repository not supplied |
| C++20/CMake modular build | VERIFIED Linux | Debug/Release build and CTest. Windows not built |
| UI/pages/navigation | PARTIAL | Linux test-only Cairo host and eight screens; full component framework, all per-page states, fields, dialogs, motion and accessibility/focus remain |
| Insert and configured keys | PARTIAL | Key model tested; actual X11 host interaction described in TEST_REPORT; game input blocked |
| Settings | PARTIAL | Versioned JSON, validation, rename, reset and no plaintext credential; recovery/migration, robust locking/fsync and comprehensive error cases remain |
| Network | PARTIAL | HTTPS verified CA/hostname, deadlines, GET retry and cancel; bounded shutdown, timeouts/reconnect, production endpoint and concurrency tests incomplete |
| Pairing/auth | PARTIAL/BLOCKED | v2 client calls implemented provisionally; v0.6 lacks v2 server, UI flow, complete response/platform binding checks and complete state machine; DPAPI is Windows-only untested |
| License/entitlement | PARTIAL/BLOCKED | Parser and fail-closed gate; denies all commands even after hypothetical active response, v2 server and fresh per-action checks missing; expiry tests use synthetic inputs |
| Device revocation | PLANNED | Only documented for authorized user/admin; no client UI/server v2 end-to-end |
| Offline | PARTIAL | local navigation/settings; offline denies actions, but no command system or reconnect workflow exists |
| Adapters Hassle / Radmir | BLOCKED | distinct disabled named boundaries only; no confirmed event/command API; no fabricated events |
| Logging/notifications | PARTIAL | event allowlist and in-memory bounded notifications; renderer integration, rotation, error taxonomy/correlation not complete |
| Unit and integration tests | PARTIAL | See TEST_REPORT; no Windows, production, provider, or game tests |
| Performance | PARTIAL | Linux synthetic CPU image renderer; not real game FPS or sustained CPU/leak proof |
| Notion documentation | VERIFIED | Current increment and evidence added; production/gaming statuses remain open |

## Next stage, ordered

1. Implement approved server v2 pairing, single entitlement source, migrations and revocation; preserve v0.6 compatibility and test PostgreSQL concurrency/replay.
2. Bind every v2 response to expected device/platform and implement per-action fresh authorization; reconcile exact schemas with backend.
3. Add complete pairing/revoke/credential lifecycle and real UI flows; test DPAPI CurrentUser on two Windows users and secure storage failures.
4. Finish lifecycle/shutdown, async dispatch, cancellation, reconnect and offline transitions; prove no UI thread blocking.
5. Finish reusable input, dialogs, stateful UI, focus/accessibility and error taxonomy; test every page/state.
6. Build/test Windows Debug and Release using pinned, licensed dependencies and Windows test host (developer-only), plus sanitizer/long-run tests.
7. Expand TLS, retries, deadlines, secret-redaction and settings migration tests; run backend PostgreSQL suite.
8. Request independently for each game written permission, supported loader/SDK, versioned UI/input/events/command API and test environment.
9. Only after permission, implement each real adapter separately, command ACK and real end-to-end tests.
10. Measure FPS/frametime against agreed budgets in each authorized game and perform security/release review.
