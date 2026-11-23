# NØRI v0.8.0 — отчёт проверки и матрица требований

Разработческий инкремент; не production и не подтверждение готовности всего MASTER PROMPT. Окружение: Linux, Python 3.13, локальный PostgreSQL 15.19, SQLite, GCC 11.5, CMake, C++20. Дата прогона: 23.11.2026. Журналы без секретов находятся в `docs/evidence/`.

## Прогоны

- `NORI_TEST_POSTGRES_URL='postgresql+psycopg://nori_test@/postgres?host=/data/nori-v08-pgsock&port=55433' python -m pytest -q tests`: **93 passed, 9 xfailed, 3 warnings**. URL относится только к временной локальной тестовой БД. Для повторения настройте собственный временный PostgreSQL и укажите его URL; тесты создают и удаляют тестовые схемы и базы — не направляйте на production. Девять xfail — тесты преднамеренно отключённого старого v1 device API; это не успешная проверка обратной совместимости. Предупреждения: deprecated Starlette httpx и два предупреждения Python о fork в многопоточном процессе. Некоторые старые тесты используют test-only auth shim; новые v2 и отдельные RBAC/конкурентные PostgreSQL тесты используют настоящие сессии и авторизацию.
- Реальный `uvicorn` и клиент HTTP на loopback: start/preview/confirm/claim/access/revoke на мигрированной временной SQLite; отдельный тест выпускает user session доверенным тестовым кодом. Это не live Telegram и не production TLS.
- C++ Release: `cmake -S game-plugin-core -B build-core -DCMAKE_BUILD_TYPE=Release && cmake --build build-core -j2 && ctest --test-dir build-core --output-on-failure` — **1/1**. `python game-plugin-core/tests/run_tls_integration.py build-core/nori_http_tests` — локальный TLS-шлюз и backend: trusted CA, неверный CA, неверный hostname, отказ HTTP, анонимный v2 401 и отмена. Полный C++ pairing не проверялся.
- Тесты SQLite создают копию известной v0.6 базы и сохраняют оригинал. PostgreSQL тест создаёт отдельную тестовую v0.6 базу и копию через TEMPLATE, обновляет только копию, проверяет revision и исходную запись. Это не `pg_dump`/`pg_restore` production rehearsal и не проверка произвольных баз. Тесты миграции v0.4/v0.5 сохранены.
- Bot pairing и event worker проверены с тестовой подменой Telegram transport/API, не реальным Bot API.

## Матрица

| Требование | Статус | Подтверждение / предел |
|---|---|---|
| Канонический расчёт доступа v2 | ЧАСТИЧНО | Grant + snapshot + account/device, проверки срока и платформы; функции per-plan отсутствуют, старые неоднозначные права не восстановлены. |
| Pairing, отзыв, replay и лимит | ЛОКАЛЬНО ПРОВЕРЕНО | Одноразовая выдача, серверный ID, состояние и конкурентные проверки; live Telegram и Windows не проверены. |
| RBAC и изоляция | ЧАСТИЧНО | Интеграционные тесты действительных user/admin/owner сессий; production security-review отсутствует. |
| Очередь поддержки | СОХРАНЕНА | Существующий механизм и тесты сохранены, реальный Telegram не проверен. |
| Очередь игровых событий | ЧАСТИЧНО | Отдельные записи и worker, dedup и opt-in; transport в тесте подменён, реальных источников нет, payload открыт в БД. |
| Очередь удалённых команд | ЧАСТИЧНО | Идемпотентность, TTL, lease, ACK, retry, отмена и отказ. Нет фонового sweeper; EXECUTED возвращает 503, пока нет разрешённого проверяемого подтверждения. |
| Offline и reconnect | ЧАСТИЧНО | Core запрещает команды, сервер проверяет право заново; полный клиентский reconnect и перепроверка после него не реализованы/не проверены end-to-end. |
| Миграции SQLite и PostgreSQL | ЧАСТИЧНО | Аддитивный upgrade на тестовых копиях проверен; legacy backfill, карантин, shadow/cutover и production restore не завершены. Downgrade новой миграции запрещён. |
| Rate limit и защита | ЧАСТИЧНО | DB buckets на v2, валидация, авторизация, no-store; edge/IP proxy, полное покрытие v1, cleanup, нагрузка, независимый аудит не завершены. |
| Реальные Hassle / Radmir | BLOCKED | Для каждой игры нужны письменное разрешение, официальный SDK/loader, схемы событий и проверяемый результат исполнения, тестовая среда. |
| Реальная оплата | BLOCKED | Провайдер/контракт и проверенные webhook, валюта, возвраты не предоставлены; успех не имитируется. |
| Telegram / Windows / Docker | НЕ ПРОВЕРЕНО | Нужен отдельный тестовый токен и тестовый чат; Windows и Docker в доступной среде не проверялись. |

## Воспроизведение

Установить Python dependencies через `python -m pip install -r requirements-dev.txt`, настроить изолированную БД, запустить `python -m alembic upgrade head`, затем `python -m pytest -q tests`; для PostgreSQL задать `NORI_TEST_POSTGRES_URL` на специально выделенную тестовую БД с правом создавать и удалять временные БД. SQLite migration helper вызывается `python scripts/migrate_v06_sqlite_copy.py OLD.db NEW.db`; NEW не должен существовать. Сначала остановить записи и сохранить исходную БД и проверенную резервную копию. Полный порядок для PostgreSQL и несовместимости — `docs/V08_BACKEND.md`. Все команды выполняются из корня проекта; venv, CMake, компилятор, X11/Cairo и TLS dependencies нужны для соответствующих C++ тестов.

## Следующие задачи

1. Спроектировать и проверить reconciliation legacy прав, карантин, shadow-сравнение и cutover/restore.
2. Завершить per-plan feature entitlements и audit, системные лимиты, защиту payload и background sweeper; выполнить security/load review.
3. Подключить Core UI к pairing, credential storage и повторной проверке при reconnect; проверить DPAPI на Windows.
4. Проверить тестовый Telegram-бот и реальную доставку с отдельным токеном; проверить Docker в доступном окружении.
5. Отдельно получить разрешения и официальные API каждой игры; только после этого проектировать реальное исполнение и его подтверждение.
