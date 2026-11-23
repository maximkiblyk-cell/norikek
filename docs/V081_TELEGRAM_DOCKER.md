# v0.8.1 — Telegram и Docker

## Отдельная тестовая конфигурация

`.env.telegram-test.example` задаёт отдельную SQLite-базу и отключает игровые типы; скопируйте в `.env.telegram-test`, заполните **локально** токен отдельного тестового бота и отдельный owner ID. Не используйте production token, не помещайте секреты в ZIP или чат. На Linux после подготовки venv можно явно загрузить тестовый файл в переменные окружения и в трёх процессах выполнить `python -m alembic upgrade head`, `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`, `python -m app.bot.main`, `python -m app.worker`. Не публиковать HTTP наружу; остановить экземпляры старой среды и проверять правильную БД. Проверьте pairing через Telegram и доставку в отдельном тестовом чате, включая retry/отказ; зафиксируйте время, version и журнал без секретов.

Реальный токен не предоставлен, live Bot API и доставка не запускались. Тесты используют test-only session/API и mock transport; retry event worker проверен с искусственной ошибкой и последующей имитацией успешной доставки. Это не Telegram acceptance. Реальный C++ ↔ Backend тест подтверждал pairing через доверенного тестового пользователя напрямую, а не через Telegram.

## Docker

Docker/Podman в доступной среде отсутствуют: build, compose healthcheck и соединение контейнеров с PostgreSQL не запускались. `compose.yaml` и `Dockerfile` сохранены; конфигурация только для теста, не production. При наличии Docker создать отдельный `.env.docker` из примера без production-паролей и токенов, затем проверить `docker compose --env-file .env.docker build` и `docker compose --env-file .env.docker up`; дождаться migrate/API healthy и отдельно подтвердить `pg_isready`, `/health`, `/ready`, бот и очереди, затем остановить тестовую среду. `docker compose down -v` уничтожает том с данными — выполнять только на заведомо одноразовой тестовой среде. Network mode bot и прочие предположения требуют реального запуска.
