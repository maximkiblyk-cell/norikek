# NØRI v0.8.2 — UI Authentication Integration

## Результат и границы

Частичный инкремент поверх фактического архива v0.8.1 (SHA-256 `db0cc70d7722614756e6d68f24a0e90e8f0cf870846a6d536b7ad67d6ee86453`). Backend не переписывался. C++ `ClientSession` подключена к Core и development host через `AuthController`: единственный worker владеет session/gate/vault, сетевые операции не выполняются в render thread, очередь на одно действие, snapshot защищён mutex. Сетевое закрытие при остановке отменяется; ожидание ограничивается таймаутами libcurl (DNS/платформенный resolver может влиять). Windows-host — только инструмент разработки, не отдельный продукт и не загрузчик в игру.

## Функции

- `Unpaired`, `WaitingConfirmation`, `Connecting`, `Online`, `Offline`, `Denied`, `Revoked`, `Error`; кнопки Pair Hassle/Radmir, Confirmed, Refresh, Cancel. Показаны код и срок до подтверждения в Telegram; код — не credential. Сервер назначает device ID. Claim выполняется вручную после подтверждения, проверка «ещё не подтверждено» не уничтожает код.
- Успешная проверка access показывает платформу, срок и server device ID. Проверка по HTTPS с верификацией цепочки/hostname. Единовременный refresh и повторные соединения 1/2/4 секунды, максимум 3 после offline; периодическая перепроверка через 30 секунд или по deadline лицензии. Показ Online прекращается при достижении локального монотонного deadline. Физический разрыв обнаруживается при следующем запросе, не мгновенно сам по себе; сразу после обнаружения статус fail-closed. Игровые и удалённые команды всегда запрещены `LicenseGate::permits()`.
- Временная ошибка не удаляет credential; серверный 401 удаляет. 403/истечение сохраняет credential, но закрывает доступ. Неоднозначно отменённый claim требует отозвать возможное устройство в Telegram и выполнить pairing заново.
- Windows: DPAPI CurrentUser (без `CRYPTPROTECT_LOCAL_MACHINE`), file хранит шифртекст; нет plaintext fallback. Ошибка и повреждение — Error. Linux production development host намеренно не поддерживает secure vault и не допускает pairing. Тестовый memory vault не включён в реальные host-бинарники.
- Windows Win32 development host: отдельный минимальный экран auth, Insert, кнопки; он не является полным аналогом Linux X11 UI. Windows CI в `.github/workflows/windows-core.yml` собирает Debug/Release и выполняет тесты, включая межпроцессные DPAPI write/read/corrupt. CI не запускался в этой среде и версии vcpkg на runner не закреплены; это не воспроизводимая фиксация зависимостей.

## Проверки (Linux, 23 ноября 2026)

| Проверка | Результат / ограничения |
| --- | --- |
| GCC C++20 Debug, CTest | сборка прошла; 1/1 тест Core |
| GCC C++20 Release, CTest | сборка прошла; 1/1 тест Core |
| Controller + HTTPS + действительный FastAPI v2 | PASS в Debug и Release: начало pairing, ранний claim, подтверждение, restart контроллера с тем же test-only memory vault, 503, автоматический reconnect, expiry, renewal, конкурентный refresh, отмена, shutdown, 401 revoke, повреждённый test vault. Подтверждение выполнялось напрямую через test session, не реальным Telegram; 503 подменялся тестовым шлюзом. Тест — отдельный исполняемый файл, не CTest. |
| Существующий C++ ClientSession + HTTPS v2 | PASS: локальный настоящий Backend, TLS и тестовое подтверждение; память вместо DPAPI. |
| X11/Xvfb host | Окно открыто; License navigation и Insert изменили реальное изображение. Существующий тест проверил настройки и F8 после перезапуска. Linux vault недоступен: сквозной UI pairing не проверен. |
| Backend pytest c PostgreSQL 15 | 101 passed, 9 xfailed, 3 warnings; xfail — исторический отключённый v1. Некоторые старые тесты используют test-only auth shim. Подробный вывод `docs/evidence/v082/backend-pytest-postgres.txt`. |
| Windows + DPAPI + Windows-host | НЕ ЗАПУЩЕНЫ: Windows и MSVC отсутствуют. Межпроцессные тесты и CI добавлены, но CI сам по себе не доказательство. Другой пользователь Windows/другая машина, повреждение в контроллере c реальным DPAPI и отзыв при реальном DPAPI не проверены. |
| Telegram, Docker, игровые SDK | НЕ ПРОВЕРЕНО: отдельный тестовый токен, Docker runtime и разрешённые SDK/loader не предоставлены. Реальная доставка, внутриигровые события и FPS не подтверждены. |

## Сборка и запуск

```bash
cmake -S game-plugin-core -B build-debug -DCMAKE_BUILD_TYPE=Debug
cmake --build build-debug -j4
ctest --test-dir build-debug --output-on-failure
cmake -S game-plugin-core -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release -j4
ctest --test-dir build-release --output-on-failure
python game-plugin-core/tests/run_controller_flow.py build-debug/nori_controller_flow_tests
python game-plugin-core/tests/run_v2_flow.py build-debug/nori_v2_flow_tests
./build-debug/nori_dev_host --settings /tmp/nori-settings.json --backend https://SERVER --ca /path/to/test-ca.pem
```

Последние два интеграционных скрипта требуют зависимости Python backend, Alembic, OpenSSL CLI и разрешение на локальный сервер. `--ca` предназначен для явно доверенного тестового CA; HTTP запрещён. В Linux host авторизация закрыта без DPAPI. X11 smoke: `python3 game-plugin-core/tests/run_x11_smoke.py build-debug/nori_dev_host /path/to/Xvfb /path/to/xvfb-libs /tmp/nori-ui` при свободном дисплее :93 и наличии Pillow/ImageMagick/XTEST. Установка Xvfb в этой среде требовала специально подготовленного бинарника и xkbcomp; это не часть проекта.

Windows (Visual Studio 2022, установленный vcpkg, x64-windows): workflow содержит точные шаги; включён `NORI_BUILD_HOST=ON`, используются curl/OpenSSL и библиотека Crypt32. Запуск предполагаемого dev host: `nori_dev_host.exe --backend https://SERVER` (при тестовом CA `--ca PATH`). Учётные данные сохраняются в `%LOCALAPPDATA%\\NORI-dev-host\\credential.dpapi`. Никогда не подставлять production-токен при тестах. Данные DPAPI не переносимы между Windows-пользователями по умолчанию.

## Нерешённое и следующий этап

1. Запустить Windows CI, исправить возможные ошибки сборки/линковки; вручную проверить Win32 UI, Windows DPAPI CurrentUser, другой Windows-профиль, повторный запуск настоящего host, повреждённый vault и 401/отзыв. Не считать эти сценарии проверенными только по коду CI.
2. Пройти реальный полный UI → Telegram → HTTPS Backend → DPAPI → restart → revoke с отдельным тестовым Bot API token, test user, TLS CA и Windows. Никаких production секретов.
3. Проверить поведение при 30-секундной перепроверке и отзывах под нагрузкой; UI не является доказательством выполнения команд.
4. Восстановление legacy-прав, production cutover, Docker и платежи остаются отдельными незакрытыми задачами v0.8.1.
5. Каждая игра отдельно BLOCKED до письменного разрешения, официального SDK/loader, UI/input API и тестовой среды. Нет DLL injection, чтения памяти или фиктивных игровых событий.

## Матрица требований v0.8.2

| Требование | Статус и доказательства |
| --- | --- |
| Session в lifecycle Core / UI, сетевой worker, единичный refresh | Реализовано; local controller flow и Linux UI smoke. Windows UI не проверен. |
| Все 8 состояний; code/expiry; отображение entitlement | Реализовано; контроллер проверен интеграционным тестом. Полный GUI-сценарий с DPAPI не проверен. |
| Reconnect, cancellation, shutdown, запрет команд offline | Реализовано; проверено контроллером и Core. Физический разрыв обнаруживается при очередном запросе, а не мгновенно по факту. Серверные команды всегда отключены. |
| Сохранение credential при сети и очистка при 401 | Проверено через test-only memory vault. С реальным DPAPI не проверено. |
| Повреждение и ошибки vault без plaintext fallback | Проверено с test-only vault и unsupported Linux. Windows DPAPI tests только подготовлены. |
| Версия, CMake, документация, исходники | Выполнено для инкремента; версии предыдущих исторических отчётов сохранены. |
| Windows CI / DPAPI CurrentUser | CI, Win32 development host и межпроцессные тесты подготовлены; Windows сборка и исполнение НЕ ПРОВЕРЕНЫ. |
| Игры и команды | Адаптеры и команды отключены; реальная интеграция BLOCKED. |
