> **Windows CI, 2026-11-23:** GitHub Actions на commit `2af2c6c5cd9b0d97a04472133fe54bbdfce8cced` прошёл Debug/Release CTest по 5/5 и изоляцию DPAPI между двумя профилями. Отчёт: `docs/GITHUB_WINDOWS_CI_VALIDATION.md` (из папки `docs` — `GITHUB_WINDOWS_CI_VALIDATION.md`). Предыдущие утверждения о непроверенном Windows ниже исторические. Telegram, Docker и game integration остаются непроверенными.

# NØRI v0.8.3 — отчёт о стабилизации

## Статус

**Частичный инкремент, не готов к production. Критерий финальной готовности не выполнен:** Windows/DPAPI и end-to-end Telegram не проверены; Docker-сборка не завершилась. Ни один игровой адаптер не подключён, игровые команды отключены. Изменения выполнены поверх фактического архива v0.8.2 (SHA-256 `be126829bb35defb61c82c2e6ecb90bf766d2a7c2559b874882dfcdd52f6ddec`). Все предыдущие файлы и тесты сохранены. Исходный аудит до изменений — `V083_AUDIT.md`; полный список файлов — `evidence/v083/file-diff.txt`.

## Изменения

1. AuthController: один сетевой worker и отсутствие параллельных refresh сохранены. Для временной недоступности backend автоматически повторяет попытки без прежнего лимита в три цикла; exponential backoff с equal jitter в диапазоне от половины до полного потолка, потолок растёт 1, 2, 4… до 60 секунд. После успешной проверки или ручного refresh backoff сбрасывается. Cancel прерывает сетевую операцию либо останавливает уже запланированный retry; ручной Refresh возобновляет его. UI сообщает о запланированном повторе. Случайность jitter используется только для распределения нагрузки, не для безопасности.
2. Сетевой клиент проверяет результаты установки libcurl options; при ошибке не выполняет небезопасный запрос. TLS-сертификат и hostname обязательны, HTTP отклоняется; секреты не добавляются в сообщения. Ограничения отмены и завершения определяются поведением libcurl и системного DNS: жёсткая гарантия времени остановки на всех ОС не заявляется.
3. Linux CMake по умолчанию ищет shared libcurl, не выбирая случайно `.a`; явная static libcurl использует transitive flags из соответствующего `libcurl.pc` (`pkg-config --static`). Пользователь должен обеспечить соответствие metadata архиву. Проверены `libcurl.a`, динамические OpenSSL и zlib; полностью статический бинарник не заявляется. На Windows сохранён путь vcpkg/CURL::libcurl.
4. Для PostgreSQL включён SQLAlchemy `pool_pre_ping`. Выявленная на локальном тестовом кластере первая ошибка после быстрого рестарта устранена: повторный тест возвращает 200 на первом запросе после восстановления. Изменения не меняют модель лицензий, API или данные БД.
5. Добавлены тесты backoff, длительного отключения и отмены, временного PostgreSQL и подготовлен Windows-тест изоляции DPAPI между профилями. Ранее существовавшие тесты сохранены.

## Reconnect и безопасность

Тест local HTTPS → настоящий процесс Backend v2: pairing, отсутствие доступа до подтверждения, перезапуск с **тестовым in-memory vault**, отключение и более трёх автоматических retry-циклов, восстановление, отмена во время ожидания, ручной повтор, expiry, продление, отмена in-flight, shutdown, отзыв и повреждённое тестовое хранилище. Подтверждение выполнялось напрямую тестовым клиентом, не Telegram. Доказательство: `evidence/v083/controller-integration.txt`.

Сетевая недоступность обнаруживается при следующем I/O, а не мгновенно при физическом обрыве. В online запланирована повторная проверка не позже 30 секунд или наступления deadline лицензии. Доступ к игровым командам **всегда закрыт** в текущем LicenseGate, в том числе при потере связи; состояние онлайн само по себе не означает право их выполнять. Сетевые ошибки не должны уничтожать credential; подтверждённый отказ 401/отзыв приводит к его удалению в существующем v2-потоке. Локальные тесты этого потока не подтверждают хранение через Windows DPAPI.

## Linux: сборка и тесты

- Debug и Release CMake сборки прошли; CTest по 2/2. Static-curl Release CTest 2/2; подтверждены TLS trusted/untrusted CA и hostname, запрет HTTP, отмена, локальный настоящий backend и v2-flow. `static-v2-flow.txt` использует тестовое хранилище и прямое тестовое подтверждение.
- X11/Cairo development host в Xvfb: переход на License, Insert закрывает и вновь открывает интерфейс. Это не игровой host. Linux secure vault намеренно недоступен: отсутствует plaintext fallback.
- Python backend: **101 passed, 9 xfailed, 3 warnings**, с локальным PostgreSQL; xfailed — ожидаемые неуспехи, не проходы. Предупреждения: Starlette/httpx deprecation и два предупреждения о `fork()` в многопоточном процессе. См. `evidence/v083/backend-pytest.txt`.
- Изолированный реальный PostgreSQL + uvicorn: `/ready` 200, после остановки 503, после запуска 200; после тихого restart первый запрос 200. Это локальная проверка, не Docker (`postgres-recovery.txt`).
- Один ранний запуск нового controller-теста упал из-за гонки параллельной сборки одного каталога; затем сборка последовательно повторена, и финальный интеграционный тест прошёл. При финальных проверках обнаружена ошибка команды `ctest` не в PATH; повторный запуск с явным путём прошёл, реальные результаты записаны отдельно.

### Воспроизведение Linux

Требуются CMake ≥3.20, C++20 compiler, OpenSSL, shared libcurl, pkg-config, Cairo/X11 для dev host и Python-зависимости проекта. Из корня:

```sh
python -m pip install -r requirements-dev.txt
cmake -S game-plugin-core -B build-debug -DCMAKE_BUILD_TYPE=Debug
cmake --build build-debug -j4
ctest --test-dir build-debug --output-on-failure
cmake -S game-plugin-core -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release -j4
ctest --test-dir build-release --output-on-failure
python game-plugin-core/tests/run_tls_integration.py build-release/nori_http_tests
python game-plugin-core/tests/run_v2_flow.py build-release/nori_v2_flow_tests
python game-plugin-core/tests/run_controller_flow.py build-release/nori_controller_flow_tests
python tests/postgres_recovery_integration.py
NORI_TEST_POSTGRES_URL='postgresql+psycopg://...test-only...' python -m pytest -q
```

`postgres_recovery_integration.py` требует `initdb` и `pg_ctl` в PATH и запускается не от root; использует только новую временную базу, не переданный production-кластер. Pytest URL должен указывать исключительно на отдельную тестовую PostgreSQL. Для статической libcurl доступны `-DNORI_CURL_STATIC_ARCHIVE=/absolute/path/libcurl.a` и `PKG_CONFIG_PATH` каталога matching `libcurl.pc`; это опциональный путь. В проверке использован исходный curl 8.10.1, архив SHA-256 `d15ebab765d793e2e96db090f0e172d127859d78ca6f6391d7eafecfd894bbc0`; OpenSSL и zlib оставались динамическими. Подробности зависимостей сохранены в `game-plugin-core/docs/DEPENDENCIES.md`.

## Windows и DPAPI — НЕ ПРОВЕРЕНО

Настоящий Windows runner, Windows build, DPAPI CurrentUser, чтение после рестарта, повреждение ciphertext, другой Windows-профиль, отзыв и срок лицензии в Windows не запускались. В `.github/workflows/windows-core.yml` подготовлены Debug/Release, CTest и отдельный `windows_profile_isolation.ps1`, но сам workflow не выполнялся. Скрипт создаёт и удаляет временного локального пользователя, поэтому запускать его **только на изолированной одноразовой машине/runner с правами локального администратора**. Возможные ограничения учётной записи, входа и наличия DLL на Windows требуют реальной проверки. Никакого plaintext fallback не добавлено; анализ кода не заменяет тест.

## Telegram — НЕ ПРОВЕРЕНО

Отдельный test Bot API token и тестовый пользователь не предоставлены; реальную доставку, ручное подтверждение в Telegram и показ лицензии в Windows host не запускали. Локальные тесты бота используют mocks/тестовые интерфейсы и не являются доказательством доставки Telegram. Нужны отдельный тестовый бот и тестовый аккаунт; production token не использовать. Секреты не помещать в архив или чат.

## Docker — ЧАСТИЧНО, запуск НЕ ПРОВЕРЕН

На ограниченном Linux создан отдельный rootless Docker daemon. `docker build` действительно запущен и скачал слои `python:3.12-slim`, но завершился ошибкой `failed to register layer ... lchown /etc/gshadow: invalid argument`: в данной среде недостаточно UID/GID mapping при распаковке образа. Полный вывод — `evidence/v083/docker-build-attempt.txt`. Compose `config -q` с тестовыми placeholder-настройками прошёл только проверку конфигурации. Контейнеры, PostgreSQL в контейнере, миграции, healthcheck, restart и восстановление backend-to-DB в Docker не проверены. Локальный PostgreSQL выше не является доказательством Docker.

## Следующие действия и блокеры

1. Запустить Windows CI на изолированном Windows runner с правами для временного второго профиля; сохранить реальные логи, устранить выявленные сбои. Проверить DPAPI между процессами и профилями, повреждение, отзыв и истечение через реальное хранилище.
2. Передать отдельный тестовый токен безопасным способом и выполнить Telegram → подтверждение → получение credential → UI end-to-end на тестовой системе. Без токена и участия тестового пользователя сценарий заблокирован.
3. На полноценном Docker host с рабочим UID/GID mapping выполнить `docker compose --env-file .env.docker up --build` на новом тестовом volume, проверить миграции/health/restart/восстановление БД; не удалять пользовательские volume.
4. Устранить или классифицировать 9 xfail и 3 предупреждения по мере работы; проверить сетевые таймауты на Windows и долговременные сбои за пределами локального сценария.
5. Игровые адаптеры остаются заблокированы отсутствием разрешённых SDK и подтверждённого механизма загрузки отдельно для Hassle RP 2.0 и Radmir CRMP. Нет внедрения DLL, обхода античита или чтения чужой памяти.
