# NØRI v0.8.1 — отчёт стабилизации

**Статус: частично завершённый разработческий инкремент, не production и не выполнение всех критериев v0.8.1.** Исходный v0.8.0 сохранён; изменений игровой интеграции, обхода античита и инъекции нет. Дата: 23.11.2026. Исходный архив v0.8.0 SHA-256 `2a4cceb4946f49650e5cd847b3154cf71a64eb6f28783216a904cd38c9baebd9`.

## Результаты и границы

| Направление | Статус | Доказательство и ограничения |
|---|---|---|
| Миграция/shadow | ЧАСТИЧНО | Read-only classification/dry-run, shadow сравнение и повторный запуск проверены на тестовых SQLite/PostgreSQL копиях реальных схем v0.6; старые данные не изменялись. Переносов 0: legacy таблица не содержит доказанных условий. Автоматическое преобразование, quarantine, production restore и cutover отсутствуют. `V081_MIGRATION.md`. |
| C++ ↔ Backend | ЧАСТИЧНО | Введён `ClientSession`, реальный C++ TLS ↔ локальный FastAPI: серверный device ID, pre-confirm ожидание, claim, access, отказ сети через тестовый gateway, повторный refresh, истечение/восстановление, отзыв. Тестовый memory vault и подтверждение через локальную сессию; не Telegram и не Windows. GUI test-host ещё не подключён к `ClientSession`. |
| Windows/DPAPI | НЕ ПРОВЕРЕНО | DPAPI CurrentUser код существует; обновлена запись ciphertext через временный файл и ограниченное чтение, добавлены условные тесты restart/повреждения/plaintext. Windows toolchain и runtime недоступны, код и тесты этой ветки не компилировались/не выполнялись. Не утверждать безопасность или атомарность без проверки Windows. |
| Очереди | ЧАСТИЧНО | На SQLite/PostgreSQL выполнены тесты создания, доставки, lease/повтора, ACK, TTL, отмены, изоляции, отказов и идемпотентности. Test-only исполнитель вычисляет хеш локально после authorize: сервер намеренно отвечает 503 на EXECUTED и остаётся ACKNOWLEDGED. Подтверждаемого production-исполнения и фонового sweeper нет. |
| Telegram | НЕ ПРОВЕРЕНО LIVE | Файл `.env.telegram-test.example` для отдельного тестового бота; токен не предоставлен. Ошибки и повторы проверены с mock transport. |
| Docker | НЕ ПРОВЕРЕНО | В среде нет Docker/Podman; build, healthcheck и соединение с PostgreSQL не запускались. |
| Security review | ЧАСТИЧНО | Проверены RBAC, pairing/replay, rate buckets, чужие объекты, отказ и локальное логирование. Остаточные критические пробелы: payload событий в БД без шифрования/retention, edge/TLS, полные конкурентные сценарии, аудит; `V081_SECURITY.md`. |
| Игры и платежи | BLOCKED | Отдельные разрешения и SDK/loader, схемы и проверяемый результат для Hassle/Radmir; платежный провайдер. Игровые типы отключены по умолчанию; никаких вымышленных успехов. |

## Тесты и воспроизведение

Окружение: Linux, Python 3.13, PostgreSQL 15.19 (временный сервер и тестовые базы), SQLite, GCC 11.5, CMake. Команды из корня проекта:

```sh
python -m pip install -r requirements-dev.txt
# Использовать только отдельную временную PostgreSQL с правом создания тестовых БД.
export NORI_TEST_POSTGRES_URL='postgresql+psycopg://USER@HOST/TEST_ADMIN_DB'
python -m pytest -q tests
cmake -S game-plugin-core -B build-core -DCMAKE_BUILD_TYPE=Release
cmake --build build-core -j2
ctest --test-dir build-core --output-on-failure
python game-plugin-core/tests/run_v2_flow.py build-core/nori_v2_flow_tests
python game-plugin-core/tests/run_tls_integration.py build-core/nori_http_tests
```

Backend: **101 passed, 9 xfailed, 3 warnings**. Xfail — сохранённые тесты намеренно отключённого экспериментального v1 device API, а не доказанная совместимость. Старые отдельные тесты используют auth shim; новые v2/RBAC тесты — реальные зависимости сессий. Warnings: deprecated Starlette httpx и Python fork в многопоточном процессе. Локальный PostgreSQL участвовал; он не является production. C++ Release и Debug CTest по 1/1; локальные flow и TLS прошли. Журналы `docs/evidence/v081/`. C++ test-only executable и Python драйвер не включены в production Core как исполнитель, не общаются с играми и не доказывают игровое выполнение.

## Core ↔ Backend: контракт использования

`ClientSession::begin` возвращает одноразовый pairing code для показа пользователю, секрет остаётся в памяти; подтверждение выполняется авторизованным пользователем через Telegram, не самим устройством. `complete` повторно вызывается после подтверждения и сохраняет credential через переданный `Vault`; только надёжный ответ «ещё не подтверждено» допускает повтор. Потерянный/неопределённый claim-response требует отмены/отзыва и нового pairing. `refresh` при запуске и после восстановления связи получает актуальный access, при 401 очищает vault, при 403 отказывает и сохраняет credential для возможного продления, при 5xx/сетевой ошибке переходит offline. Команды запрещены `LicenseGate::permits` и не выполняются офлайн. Все методы с сетью синхронны и должны вызываться вызывающим приложением на рабочем потоке; автоматический reconnect и GUI-события не подключены. `Settings.device_id` — исторический локальный ID настроек, v2 его не отправляет: ID привязки назначает сервер.

## Оставшиеся задачи

1. Реализовать и протестировать доказуемый migration mapping/quarantine и reconciliation, протестировать production-like backup/restore и cutover на копии с реальными подтверждёнными условиями.
2. Подключить state machine к test-host UI и фоновой очереди вызовов, обработать потерю ответа, проверить настоящий отдельный Telegram бот и live delivery.
3. Собрать и проверить Windows, DPAPI после перезапуска, повреждение, ACL, отзыв и отсутствие утечек в диагностике.
4. Проверить Docker build/compose/healthcheck/DB и изолированные секреты.
5. До включения событий утвердить retention, encryption, удаление, доступ и защиту payload; завершить sweeper, abuse protection и независимое security-review.
6. После отдельного разрешения каждой игры спроектировать достоверный verifier исполнения. До этого EXECUTED отключён и вся игровая интеграция BLOCKED.
