> **v0.8.3:** бессрочный ограниченный backoff с jitter и отменой; Linux Debug/Release проверены, Windows и DPAPI не проверены. Инструкции сборки и точные результаты: `../docs/V083_REPORT.md`.

> **v0.8.2:** интерфейс авторизации подключён к `ClientSession` через один worker. Linux X11 host не имеет защищённого хранилища и fail-closed; Windows development host и CI подготовлены, но Windows/DPAPI не проверены. Полный отчёт — `../docs/V082_REPORT.md`.

> **v0.8.1:** `ClientSession` реализует v2 start/claim/refresh и fail-closed при offline/отказе. Локальный C++ HTTPS-тест использует настоящий backend, test-only memory vault и прямое тестовое подтверждение; GUI host не подключён к этой машине состояний. Windows DPAPI не проверен. `docs/V081_REPORT.md` в корне содержит границы.

> **v0.8 compatibility note:** The backend now provides a preliminary v2 API and assigns the Device ID at pairing start. The v0.7 client start request was adjusted to this breaking contract, but the test host still does not wire pairing/license flows, DPAPI is not tested here, and the gate still denies all commands. Older sections describing absent v2 are historical v0.7 observations. See `../docs/V08_BACKEND.md` for current status.

# NØRI v0.7.0 — independent game core (development build)

This is an incomplete development increment, not an in-game plugin or a product release. The existing v0.6.0 backend is preserved byte-for-byte. No game is connected, no events are fabricated, and no injection, proxy DLL, hooks or memory reading are used. The standalone host is **only a developer/test tool**, not a user application or sidecar.

## Layout

- `include/nori/core.hpp`: public C++ model, boundaries and interfaces.
- `src/core`, `ui`, `navigation`, `input`, `settings`, `network`, `authentication`, `licensing`, `notifications`, `logging`, `adapters`, `platform`.
- `host`: Linux X11/Cairo developer-only renderer. This is not the in-game renderer and does not establish compatibility with either game.
- `tests`: C++ model/HTTPS tests, Python TLS gateway to the existing backend, optional X11 test.
- `docs`: dependency, evidence and requirements reports.

## Build and run (Linux)

Requirements: CMake >=3.20, C++20 compiler, OpenSSL development headers/libcrypto, libcurl runtime/development library >=7.85, Cairo, X11 and pkg-config for the developer host. No browser or game required. CMake packages can be system-installed or provided in a virtual environment. Build each configuration separately:

```sh
cmake -S game-plugin-core -B build-core-debug -DCMAKE_BUILD_TYPE=Debug
cmake --build build-core-debug -j2
ctest --test-dir build-core-debug --output-on-failure
cmake -S game-plugin-core -B build-core-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-core-release -j2
ctest --test-dir build-core-release --output-on-failure
./build-core-release/nori_dev_host --settings /tmp/nori-settings.json
./build-core-release/nori_dev_host --settings /tmp/nori-settings.json --render /tmp/nori-preview.png
./build-core-release/nori_dev_host --settings /tmp/nori-settings.json --benchmark
```

In the host, Insert opens/closes the UI, the sidebar navigates, Settings changes the shortcut/scale/notifications/reduced motion and reset preserves the device ID. Optional `--backend https://HOST` performs a nonblocking `/health` request; optional `--ca FILE` uses a test CA. For normal systems omit `--ca` and rely on the system trust store. Status `BACKEND ONLINE` is only a health check, not authentication, entitlement or a connected game. `--render` renders a static PNG, `--benchmark` renders 300 frames into an image surface; neither requires X11.

## Integration tests

From project root, create a Python environment and install backend dev dependencies from `requirements.txt` and `requirements-dev.txt`; OpenSSL CLI must be installed. The script starts the actual v0.6 FastAPI on loopback behind a throwaway local TLS gateway and temporary SQLite DB, creates its own short-lived test certificate and removes it afterwards. It does not change the production environment:

```sh
python game-plugin-core/tests/run_tls_integration.py build-core-release/nori_http_tests
pytest -q
# Optional: Xvfb or X11 display and python-xlib installed in test environment
DISPLAY=:99 python game-plugin-core/tests/gui_x11_test.py build-core-release/nori_dev_host
```

The TLS integration tests `/health`, test CA acceptance, untrusted CA/hostname rejection, HTTP rejection, unauthenticated v2 rejection and cancellation. `/slow` is a synthetic test-only route, not a game event. PostgreSQL backend tests skip without their configured URL; consult backend documentation for those prerequisites.

## Windows and security boundaries

The core has a Windows DPAPI CurrentUser vault implementation, but this revision has **not been built or tested on Windows**. CMake excludes the X11 developer host there; an approved Windows development/test host, dependency toolchain, certificate tests and DPAPI isolation tests are still needed. On unsupported platforms the vault fails closed, no plaintext fallback. No downloadable DLL or game loader is supplied.

The v2 pairing client is a preliminary implementation of the Notion ADR interface; v0.6 lacks those server routes. It is not wired into the host and has not passed end-to-end testing. Device revocation, reconnect/refresh, secure secret lifetime, response binding and real pairing UI remain to do. v1 `/device/me` is only a compatibility read and cannot prove access. LicenseGate intentionally always denies commands: parsing a hypothetical v2 response must not be used for authorization or to assert a license is active. Actual per-operation authorization requires the server-side v2 entitlement implementation. Local UI/settings remain available offline. Do not use this build to protect or operate a live game.

Settings use a versioned JSON file with a random UUID, public preferences and a temporary-file rename; no credential is saved there. It is not a durable transaction or a Windows ACL policy; corrupted files are retained and startup fails. Network requests use verified TLS 1.2+, hostname validation, deadlines and limited retries for GET only; POST is not retried. Cancellation and timeout are bounded by underlying libcurl behavior; destroying a pending async handle may wait until it finishes. Renderer is currently synchronous; it is not validated against a game render thread or an FPS budget. UI state models/labels exist, but not all six states or all controls are implemented for each page.
