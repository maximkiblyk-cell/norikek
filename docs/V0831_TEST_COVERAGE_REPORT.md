# NØRI v0.8.3.1 — покрытие тестами

Тестируемый код: `770010a85c97ffb7c96c2deba4824f95bf624972`, ветка `stabilization/v0.8.3.1`, база `stabilization/v0.8.3` (`5e44e25`). Backend и архитектура авторизации не изменены; игровые адаптеры и команды остаются отключены. Последующий коммит отчёта меняет только документацию и файлы доказательств.

## Сводка

| Среда | Сборка | Зарегистрировано CTest | Выполнено и успешно |
|---|---|---:|---:|
| Linux, Debug, GCC 11.5, Python 3.13 | успешно | 5 | 5 |
| Linux, Release, GCC 11.5, Python 3.13 | успешно | 5 | 5 |
| Windows Server 2022, MSVC, Debug, Python 3.12 | успешно | 8 | 8 |
| Windows Server 2022, MSVC, Release, Python 3.12 | успешно | 8 | 8 |

Windows: [фактический GitHub Actions run 45126054885](https://github.com/maximkiblyk-cell/norikek/actions/runs/45126054885), commit `770010a`. Отдельно прошла проверка изоляции DPAPI вторым Windows-профилем. Это не дополнительный CTest-тест. Первоначальный проверочный run `45124885971` также успешен, но относится к предыдущему коммиту `0952812`. Для всех результатов и конкретных сообщений см. `evidence/v0831/`; полный артефакт CI `windows-core-logs` хранится в GitHub Actions 14 дней.

## Результаты каждого зарегистрированного теста

| CTest / executable | Что проверяется | Linux Debug / Release | Windows Debug / Release |
|---|---|---|---|
| `core` / `nori_core_tests` | настройки и перезапуск, Insert/навигация, LicenseGate offline/expiry, отключённые адаптеры, журнал; Windows vault / Linux fail-closed | PASS / PASS | PASS / PASS |
| `http` / `nori_http_tests` | локальный HTTPS: проверка CA и hostname, отказ от HTTP, 401 без credentials, отмена запроса | PASS / PASS | PASS / PASS |
| `v2_flow` / `nori_v2_flow_tests` | клиент ↔ настоящий локальный Backend v2: pairing, доступ, 503, reconnect, окончание и продление лицензии, отзыв | PASS / PASS | PASS / PASS |
| `controller_flow` / `nori_controller_flow_tests` | просроченный pairing и 410, повторная привязка после отзыва, отказ параллельной привязки, отсутствие credentials, перезапуск, 503, >3 retry-циклов, reconnect, expiry, отмена и shutdown при запросе, отзыв и повреждённое хранилище | PASS / PASS | PASS / PASS |
| `backoff` / `nori_backoff_tests` | exponential backoff, jitter, предел, reset, отказ при null vault | PASS / PASS | PASS / PASS |
| `vault_write` / `nori_windows_vault_test` | запись Windows DPAPI CurrentUser, проверка отсутствия открытого тестового секрета в файле | не применимо | PASS / PASS |
| `vault_read` / `nori_windows_vault_test` | чтение созданного шифротекста отдельным процессом | не применимо | PASS / PASS |
| `vault_corrupt` / `nori_windows_vault_test` | отказ при повреждении и очистка test vault | не применимо | PASS / PASS |

CTest задаёт порядок `vault_write` → `vault_read` → `vault_corrupt`. Две Windows-конфигурации используют разные файлы. Дополнительный отдельный шаг создаёт временный Windows-профиль, проверяет работу его собственного DPAPI и невозможность расшифровки доступного для чтения шифротекста владельца. Ошибка доступа к файлу не засчитывается как успешная изоляция.

## Границы доказательств

- В `http`, `v2_flow`, `controller_flow` работают реальные локальные процессы FastAPI и C++ с локальным TLS и временной SQLite; используются самоподписанный тестовый сертификат и локальный шлюз. Отключение Backend в интеграционных сценариях моделируется ответом 503 и задержкой шлюза, а не физическим разрывом сети.
- Подтверждение pairing в v2/controller делается тестовым драйвером с тестовой сессией, не через реальный Telegram; в этих сценариях используется in-memory test vault. Истечение pairing создаётся изменением времени в изолированной SQLite и проверяется ответом 410. Это не доказательство реальной доставки Telegram или интеграции Core с DPAPI end-to-end.
- DPAPI тестируется отдельно на настоящем Windows runner, не Linux-моком. Проверки не подтверждают работу на всех версиях Windows и со всеми профилями.
- Реальные Telegram, Docker и игровые интеграции в рамках этого этапа не тестировались; SDK и разрешений для игр нет. Тесты не подтверждают готовность продукта в целом.
- Linux-сборка выдала ранее существовавшие предупреждения `-Wmisleading-indentation` в `src/network/http.cpp`; тесты и сборка при этом прошли. Данный этап не менял производственный код.
- GitHub предупредил о переходе JavaScript actions с Node 20 на Node 24; run завершился успешно. Необходимо следить за обновлениями actions.

## Повторение Linux

Из корня репозитория, с установленными CMake >= 3.20, C++20, OpenSSL CLI и dev-библиотеками OpenSSL/curl, Python, X11 и Cairo (если собирается dev host):

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
cmake -S game-plugin-core -B build-debug -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE="$(command -v python)"
cmake --build build-debug --parallel
ctest --test-dir build-debug -N
ctest --test-dir build-debug -V --no-tests=error
cmake -S game-plugin-core -B build-release -DCMAKE_BUILD_TYPE=Release -DPython3_EXECUTABLE="$(command -v python)"
cmake --build build-release --parallel
ctest --test-dir build-release -N
ctest --test-dir build-release -V --no-tests=error
```

## Повторение Windows

В терминале Visual Studio с vcpkg, Python и OpenSSL CLI, из корня репозитория:

```powershell
python -m pip install -r requirements-dev.txt
& "$env:VCPKG_INSTALLATION_ROOT/vcpkg.exe" install 'curl[core,openssl]:x64-windows' 'openssl:x64-windows'
cmake -S game-plugin-core -B build-win -DCMAKE_TOOLCHAIN_FILE="$env:VCPKG_INSTALLATION_ROOT/scripts/buildsystems/vcpkg.cmake" -DVCPKG_TARGET_TRIPLET=x64-windows -DNORI_BUILD_HOST=ON
cmake --build build-win --config Debug --parallel
cmake --build build-win --config Release --parallel
ctest --test-dir build-win -C Debug -N
ctest --test-dir build-win -C Debug -V --no-tests=error
ctest --test-dir build-win -C Release -N
ctest --test-dir build-win -C Release -V --no-tests=error
# На одноразовой машине с разрешением на создание локальных учётных записей:
./game-plugin-core/tests/windows_profile_isolation.ps1 -BinaryDir ./build-win/Release
```

Интеграционным тестам нужны Python зависимости, OpenSSL CLI и возможность открыть локальные порты и создавать временные файлы. CTest запускает эти сценарии последовательно и ограничивает каждый 180 секундами. Их временные БД не являются production-данными.
