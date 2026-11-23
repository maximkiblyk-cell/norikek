# NØRI v0.8.3 — безопасная инструкция внешней проверки

Инструкция подготовлена по исходникам, **не является результатом её выполнения**. Работать только на изолированной тестовой машине, в новой распакованной копии проекта и с заведомо тестовыми данными. Не использовать production token, production DB, чужой рабочий профиль или существующий volume. Не снимать проверку TLS. Все команды адаптировать к окружению, фиксируя результаты и версии без секретов.

## A. Windows workflow и DPAPI

1. В существующем приватном GitHub-репозитории, с разрешения владельца, разместить фактический исходный код v0.8.3 на согласованной ветке; не загружать `.env*` с секретами, сертификатные ключи, базы или данные пользователя. Включить Actions и workflow на default branch согласно настройкам GitHub. Код workflow: `.github/workflows/windows-core.yml`, поддерживает `workflow_dispatch`.
2. В Actions выбрать **Windows Core (development tests)** → **Run workflow** → нужная ветка → Run workflow. Зафиксировать URL и commit SHA. Изучить полный лог job и результаты Debug/Release CTest; успешная отправка задания не означает успех тестов.
3. Нужен изолированный Windows runner с локальными административными правами: последний шаг создаёт временного локального пользователя, пробует собственный DPAPI этого пользователя и проверяет, что он не расшифровывает доступный ему ciphertext владельца; удаление учётной записи и каталога выполняется в `finally`. На общей или production машине не запускать. При нехватке прав, запрете logon, отсутствии runtime DLL или других ошибках записать FAIL, а не PASS. При необходимости убрать созданный тестовый аккаунт вручную после проверки.
4. CTest содержит отдельные процессы `vault_write`, `vault_read`, `vault_corrupt`. Подтвердить их реальные результаты для Debug и Release. Дополнительно вручную проверить Windows host: pairing, завершение процесса и запуск под тем же профилем, отзыв устройства и истечение лицензии с настоящим DPAPI; автоматический DPAPI CI не доказывает полный Telegram flow.

## B. Настоящий Telegram pairing в изолированной среде

**Предпосылки:** Windows test host, изолированная чистая распакованная копия, Python + зависимости и OpenSSL, отдельный бот BotFather, тестовый Telegram-пользователь/owner и его числовой Telegram ID, локальный безопасный TLS. Требуется активная тестовая лицензия по тарифу с подходящей платформой и свободным слотом. UI Windows host и этот сценарий пока не проверены на Windows. Для невредоносного временного теста не открывать порты вовне и не запускать второй polling-процесс того же бота.

1. В новой копии проверьте, что нет чужого `.env`, существующей базы `nori-telegram-test.db` и файла `.env.telegram-test`; иначе остановитесь и выберите другую изолированную директорию. Создайте Python venv и установите `requirements-dev.txt`. Создайте `.env.telegram-test` из `.env.telegram-test.example` на следующем шаге; затем внесите локально `BOT_TOKEN` **отдельного test bot** и `OWNER_TELEGRAM_IDS` (числовой ID тестового owner). Оставьте отдельную SQLite БД, `AUTO_CREATE_SCHEMA=false`, пустыми `V2_APPROVED_EVENT_TYPES` и `V2_APPROVED_COMMAND_TYPES`. Не коммитить/прикладывать файл. `DEVICE_PAIRING_ENABLED` — флаг отключённого v1, v2-обработчики не зависят от него; не включать игровые типы.
2. Все следующие команды из корня этой копии, в PowerShell; файл переменных указан явно. Чтобы обеспечить CLI `dotenv`, при необходимости установите `python-dotenv[cli]` в тестовый venv. Миграция применяется **только к новой тестовой БД**:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install "python-dotenv[cli]>=1,<2"
Copy-Item .env.telegram-test.example .env.telegram-test
# Откройте .env.telegram-test в локальном редакторе, внесите test BOT_TOKEN и OWNER_TELEGRAM_IDS.
.\.venv\Scripts\python.exe -m dotenv -f .env.telegram-test run -- .\.venv\Scripts\python.exe -m alembic upgrade head
```

Убедитесь, что новая БД и ключи сертификата доступны только тестовому пользователю. В файле могут быть секреты; не показывайте его содержимое в логах. dotenv запускает дочерний процесс с переменными; Python и миграция должны использовать интерпретатор venv, активируйте его в каждом окне: `.\.venv\Scripts\Activate.ps1`.
3. Создайте одноразовый локальный сертификат только для test host в закрытом каталоге (не в Git, не передавайте private key):

```powershell
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost" -keyout test-tls-key.pem -out test-tls-cert.pem
```

Предварительно убедитесь, что файлы с этими именами отсутствуют, чтобы не перезаписать существующие. Держите ключ в каталоге с ограниченными ACL. В трёх отдельных окнах PowerShell из корня, с активированным venv, запустите два API-процесса над одной тестовой БД и бота; не включайте access-логи с кодами и секретами:

```powershell
python -m dotenv -f .env.telegram-test run -- python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
# окно 2: HTTPS только для тестового Core
python -m dotenv -f .env.telegram-test run -- python -m uvicorn app.main:app --host 127.0.0.1 --port 8443 --ssl-keyfile test-tls-key.pem --ssl-certfile test-tls-cert.pem --no-access-log
# окно 3: бот общается с локальным API по loopback
python -m dotenv -f .env.telegram-test run -- python -m app.bot.main
```

Проверить, что оба порта свободны до запуска, `/health` и `/ready` у локального API отвечают; сертификат доверять только через явный `--ca` host, не устанавливать его в системное хранилище и не отключать проверку hostname. `API_BASE_URL=http://127.0.0.1:8000` допустим только между процессами на одной доверенной машине. Для удалённого host потребуются отдельно настроенные HTTPS и защищённая инфраструктура; эта схема не production.
4. В личном чате тестового бота отправить `/start`. Владелец создаёт тариф, например `/plancreate Test 1 EUR 1 1 hassle`, подтверждает; в `/admin` → тарифы открыть созданный тариф и взять его UUID. `/grantplan TELEGRAM_ID UUID_ТАРИФА` и подтверждение выдают одноразовый **тестовый** ключ. Владелец передаёт его только соответствующему тестовому пользователю; тот активирует через «Активировать ключ». Сообщение с ключом бот пытается удалить, но Telegram может сохранять его. Оплата при этом не производится. Сверить активную лицензию, платформу и свободный слот.
5. Запустить собранный Windows development host, заменив путь к исполняемому файлу на фактический: `nori_dev_host.exe --backend https://localhost:8443 --ca ПОЛНЫЙ_ПУТЬ_К_test-tls-cert.pem`. Нажать Pair Hassle (или выбрать Radmir при подходящем тарифе). В течение срока кода в личном Telegram-чате: «Подключить игру» → та же платформа → «Ввести код устройства», отправить код, сверить имя, платформу и окончание ID, подтвердить только собственное устройство и нужную лицензию. В host нажать Confirmed. Ожидается Online с платформой и сроком после настоящего серверного access, без отображения credential. Никакая игра не подключается.
6. Закрыть и снова открыть host под тем же Windows-профилем; проверить повторную проверку. Затем в боте «Устройства» → нужное устройство → «Отключить» → подтвердить, нажать Refresh в host и проверить отказ/отзыв. Отдельно протестировать expiry, неверный код и отказ сети. При неоднозначном завершении claim сначала проверить/отозвать возможное устройство, затем начинать новую привязку.
7. Фиксируйте время, commit, итог и обезличенные ошибки. Не публикуйте тестовый токен, API credentials, pairing code, license key, приватный TLS key, базу и скриншоты с секретами. После теста остановите тестовые процессы; отключите/отзовите только тестового бота и учётные данные по согласованию. Не удаляйте чужие данные.

## C. Docker Compose и PostgreSQL — безопасный тест на полноценном Docker host

Использовать Docker host, где `docker info` реально работает и разрешены user mappings, отдельную копию и свободный локальный порт 8000. Убедиться, что в этой копии нет `.env.docker`; не перезаписывать его. Не использовать существующие project name или volume. Команды ниже для POSIX shell в корне копии:

```sh
cp .env.docker.example .env.docker
chmod 600 .env.docker
# В локальном редакторе замените ОБА REPLACE_WITH_RANDOM_HEX на одинаковый новый
# случайный hex-пароль; BOT_TOKEN оставить пустым для теста postgres/migrate/api.
# Не печатайте готовый env-файл и конфигурацию с секретами.
PROJECT="nori_v083_$(python3 -c 'import secrets;print(secrets.token_hex(6))')"
docker volume inspect "${PROJECT}_postgres_data" >/dev/null 2>&1 && { echo 'volume уже существует — остановка'; exit 1; }
docker compose -p "$PROJECT" --env-file .env.docker config -q
docker compose -p "$PROJECT" --env-file .env.docker build
docker compose -p "$PROJECT" --env-file .env.docker up -d postgres migrate api
docker compose -p "$PROJECT" --env-file .env.docker ps
docker compose -p "$PROJECT" --env-file .env.docker exec -T postgres pg_isready -U nori -d nori
docker compose -p "$PROJECT" --env-file .env.docker run --rm --no-deps migrate alembic current
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
```

Дождаться окончания migrate с exit 0 и статуса healthy API/PostgreSQL (проверить в `ps`), а не считать отсутствие ошибки `up -d` доказательством. Затем:

```sh
docker compose -p "$PROJECT" --env-file .env.docker stop postgres
# /ready должен вернуть HTTP 503; /health не проверяет БД.
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/ready
docker compose -p "$PROJECT" --env-file .env.docker start postgres
# После восстановления readiness PostgreSQL повторить до 200 и зафиксировать время.
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/ready
docker compose -p "$PROJECT" --env-file .env.docker restart api
# Дождаться healthy и повторить /ready.
docker compose -p "$PROJECT" --env-file .env.docker ps
```

Для сценария быстрого рестарта базы после прогрева пула: при готовом API запросить `/ready`, затем `restart postgres` и после готовности Postgres проверить первый последующий `/ready`; его результат записать отдельно. После проверки остановить **только этот project** командой `docker compose -p "$PROJECT" --env-file .env.docker stop`. Не применять `down -v`, `volume prune` или удалять volumes. Тест bot/worker требует отдельного токена и не следует из результата postgres/migrate/api. Логи перед передачей очистить от секретов и идентификаторов.
