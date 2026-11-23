# Аудит v0.8.2 до изменений v0.8.3

Источник: NORI-v0.8.2-source.zip SHA-256 be126829bb35defb61c82c2e6ecb90bf766d2a7c2559b874882dfcdd52f6ddec. Список составлен до изменений кода.

1. AuthController: автоматические retry прекращаются после 3 (1, 2, 4 секунды), jitter и потолка нет; ручная отмена не останавливает уже запланированный retry в offline. Следствие: длительный сбой требует ручного refresh. Mutex и один worker уже запрещают параллельный refresh; их следует сохранить.
2. ClientSession/V2Api: отдельные v2 start/claim/access; 401 очищает Vault, сетевые ошибки нет; claim при неоднозначном ответе необходимо отзывать и повторять. TLS и hostname проверяются; libcurl setopt return values не проверяются. Нельзя заменять backend API.
3. LicenseGate: при отказе fail-closed, `permits()` всегда false. Просроченный кеш не разрешает команды; повторная серверная проверка обязательна. Онлайн-маркер сам по себе не доказывает доступ к командам.
4. DPAPI: `CryptProtectData` с user scope, бинарный файл и атомарный replace; plaintext fallback нет. Межпроцессные тесты подготовлены, но реальная Windows/другой пользователь/отзыв через DPAPI не проверены. На Linux доступ к настоящему Vault отсутствует.
5. Windows development host и CI подготовлены, но нет фактической Windows-сборки/результата CI. Другой Windows-профиль и полный Telegram UI-flow не тестируются существующим CI.
6. CMake Unix `find_library(curl)` может выбрать `/usr/local/lib/libcurl.a` без transitives (например zlib, SSL и др.); комплектные заголовки не доказывают корректную линковку. В текущей среде присутствует shared `/usr/lib64/libcurl.so.4`, pkg-config metadata libcurl отсутствует, Cairo 1.18.0 доступен. Требуется воспроизводимый shared путь и отдельная корректная поддержка static metadata, не отключая TLS.
7. Telegram: бот осуществляет v2 preview/confirm после ввода кода и выбора лицензии. Прямой тестовый API-driver — не реальный Telegram. Отдельный тестовый token не предоставлен; отправка/подтверждение и UI end-to-end не доказаны.
8. Docker: compose содержит PostgreSQL healthcheck, миграции, api, bot и worker. Docker/Podman CLI и сокет недоступны; build, healthcheck, рестарт и восстановление соединения не доказаны.
9. Старый test-suite нужно сохранить; добавить интеграционный длительный offline >3 retries, ограничения delay/jitter, отмену ожидания, TLS и сборку, а не заменять их результатами mock.
10. PostgreSQL pool: до исправления локальный uvicorn `/ready` на отдельном тестовом кластере вернул 200 до остановки, затем после быстрого рестарта базы первый запрос 503, второй 200. `app/db.py` создаёт engine без `pool_pre_ping`. Обоснованное минимальное изменение: pre-ping для PostgreSQL, не новая архитектура и не замена БД. Нужно повторить тест на временном кластере и регрессии.
