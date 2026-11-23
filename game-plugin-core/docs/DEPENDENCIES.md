# Dependencies and licenses

| Component | Use | License and verification | Status |
|---|---|---|---|
| C++20 / CMake >=3.20 | language / build | Compiler/tool licenses apply separately | GCC 11.5/CMake 3.31.6 tested on Linux |
| libcurl | HTTPS | curl license, compatible with MIT-like terms: https://curl.se/docs/copyright.html ; headers 8.10.1 and LICENSE included | Tested with libcurl 8.21 runtime; TLS and hostname validation required; distribution must include proper notices |
| nlohmann/json 3.11.3 | JSON | MIT; included `third_party/json/LICENSE.MIT`; https://github.com/nlohmann/json/blob/v3.11.3/LICENSE.MIT | Vendored single header |
| OpenSSL | CSPRNG/libcrypto | Apache-2.0 for OpenSSL 3.x; https://www.openssl.org/source/license.html | System dependency; verify actual distributed version and transitive terms |
| Cairo | development renderer only | LGPL-2.1 or MPL-1.1: https://www.cairographics.org/ | System shared library; choose and satisfy distribution obligations |
| X11/libX11 | development host only | MIT/X11 terms; https://gitlab.freedesktop.org/xorg/lib/libx11/-/blob/master/COPYING | System library on Linux, no game host ABI implied |
| Python, FastAPI, pytest and dependencies | existing backend/integration testing | See preserved v0.6 requirements and each distribution's own license | Backend dependencies not vendored by this increment |
| python-xlib | optional GUI smoke test | LGPL-2.1-or-later; https://github.com/python-xlib/python-xlib/blob/master/COPYING | Test-only; installed separately |

Dear ImGui's MIT license was considered (https://github.com/ocornut/imgui/blob/master/LICENSE.txt) but it is not included: selecting an in-game renderer/backend before each game's approved SDK and graphics API is known would imply unverified compatibility. Cairo is confined to the Linux test host. No third-party game/plugin code copied. Licenses of platform-provided/binary transitive dependencies, static/dynamic-link obligations, notices, SBOM, exact Windows libcurl/OpenSSL versions, and production security updates require independent release review. No license assessment establishes game permission.
