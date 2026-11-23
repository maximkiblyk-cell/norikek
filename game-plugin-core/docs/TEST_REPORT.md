# Test report — v0.7.0 development increment

Date: 2026-11-23. Input: `NORI-v0.6.0-source.zip`, SHA-256 `968be2af7c3a514aec2cb13595262d5419bfd1f7eff1092aabb4735e1514ee7e`. Compared all 63 files in the original archive with output: 0 different or missing (new files are in game-plugin-core). This is not the missing full historical repository. Scope below is local development only, not release verification.

Environment: Amazon Linux 2023 x86_64, GCC 11.5, CMake 3.31.6, Python 3.13, libcurl 8.21 runtime, Cairo/X11; no real Windows, game, Docker or Telegram token.

| Test | Result and scope |
|---|---|
| CMake Debug and Release / CTest | PASS: core CTest 1/1 each; a test executable contains multiple assertions. Model checks include lifecycle, navigation, shortcut repeat, config save/load/reset/corruption, vault fail-closed on Linux, v2 parser and simulated expired response, logging allowlist and disabled game adapters. Test doubles are not game events. |
| Linux HTTPS integration | PASS Debug/Release: actual unchanged FastAPI `/health` behind local TLS gateway, test CA accepted, untrusted certificate and hostname mismatch rejected, plaintext HTTP rejected, expected v2 404 and cancellation of test-only `/slow`. The gateway terminates TLS locally; production TLS, pairing and entitlement are not tested. |
| X11 UI | PASS: isolated Xvfb and actual development host; Insert closed/reopened, click navigated to Settings, click changed hotkey, separate host process restarted and F8 persistence/close verified. Does not prove game interaction, cross-platform UI or all state transitions. |
| Backend regression | PASS with skips: 66 passed, 5 PostgreSQL tests skipped (no configured PostgreSQL URL), 1 deprecation warning; `pytest -q` from supplied backend with isolated environment. Some legacy regression tests use auth shim and do not prove production auth. |
| ASan + UBSan | PASS: Debug core CTest 1/1 with address/undefined sanitizers and detect_leaks=1, on these executed cases only; not proof of absence of leaks in host, game or long-running usage. |
| Windows | NOT RUN: no Windows runtime/toolchain here. DPAPI source and core portability not verified. |
| Live v2 pairing/license, Telegram, Docker, game | NOT RUN: v2 backend absent, no Telegram test token, Docker runtime and game permissions/SDK unavailable. |

## Reproduction

See `../README.md` for build, CTest, TLS and X11 commands. Original regression: `pytest -q` with isolated test dependencies. Sanitizer example (toolchain must support it):

```sh
cmake -S game-plugin-core -B build-core-asan -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer' -DCMAKE_EXE_LINKER_FLAGS='-fsanitize=address,undefined'
cmake --build build-core-asan -j2
ASAN_OPTIONS=detect_leaks=1 ctest --test-dir build-core-asan --output-on-failure
```

## Single-run performance observation

Release host, Linux image surface 1080×700, 300 synchronous draws without a game: initialization 0.070 ms, total draw 107.271 ms, mean draw 0.358 ms, process peak RSS 18,952 KiB, process cumulative CPU 118.019 ms. Measured by `nori_dev_host --settings /tmp/nori-perf-settings.json --benchmark`. These numbers depend on warmed settings, host and libraries; CPU time is not CPU percentage. This benchmark is not a frame pacing or gameplay FPS measurement, no p95/p99, no absolute budget validation, no Windows claim.

## Known limitations

C++ compiler emits `-Wmisleading-indentation` warnings in network/http.cpp; behavior is covered by listed tests but source should be reformatted and audited. No end-to-end v2 authorization/revocation/reconnect, no full UI state suite, no per-action entitlement, no validated in-game runtime, no performance budget, no load/fault-injection/security audit. Some `std::future` destruction can wait for a request timeout. Settings durability under crashes/concurrent writers is not proven. Passing synthetic license JSON proves parser behavior only and cannot prove a live active entitlement.
