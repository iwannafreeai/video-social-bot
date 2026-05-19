# Video Social Bot

MVP для Telegram-бота и лёгкого FastAPI-дэшборда:

- загрузка вертикальных shorts/reels/tiktok-видео до 100 МБ;
- FFmpeg-ремастеринг в 9:16 с компрессией;
- транскрибация аудио через OpenAI Whisper API;
- более точные SRT-субтитры по Whisper segment timestamps;
- генерация подписи на русском или английском через OpenAI-compatible LLM API;
- админка и клиентский кабинет;
- SQLite без отдельной БД;
- локальное хранение файлов с автоудалением через 24 часа;
- debug-логирование и опциональный водяной знак/брендинг;
- SRT-субтитры и опциональное вшивание субтитров в видео;
- ручная и отложенная публикация готовых видео в YouTube Shorts через официальный YouTube Data API;
- отправка готовых видео в TikTok Inbox через официальный Content Posting API.

## Безопасная модель публикации

Этот MVP не автоматизирует обход антиспама и не пытается маскировать чужой контент. Пайплайн делает легитимный ремастеринг: нормализация 9:16, компрессия, лёгкая цветокоррекция и новая подпись. Для YouTube/TikTok/Instagram прямую публикацию лучше добавлять следующим этапом через официальные API после approvals.

## Требования

Для Docker-запуска:

- Docker
- Docker Compose v2

Для ручного запуска:

- Python 3.12+
- FFmpeg и FFprobe

Для работы приложения:

- Telegram bot token
- OpenAI API key для Whisper
- LLM API key: OpenRouter по умолчанию или любой совместимый с OpenAI Chat Completions API

## Быстрый запуск через Docker

```bash
git clone https://github.com/iwannafreeai/video-social-bot.git
cd video-social-bot
cp .env.example .env
```

Заполнить `.env`:

```env
TELEGRAM_BOT_TOKEN=...
OPENAI_API_KEY=...
LLM_API_KEY=...
ADMIN_USERNAME=admin
ADMIN_PASSWORD=strong-password
SECRET_KEY=random-long-secret
LOG_LEVEL=INFO
DATABASE_URL=sqlite+aiosqlite:////app/data/app.db
STORAGE_DIR=/app/storage
WEB_WORKER_ENABLED=false
WATERMARK_TEXT=@your_brand
WATERMARK_POSITION=bottom-right
SUBTITLES_ENABLED=true
BURN_SUBTITLES=false
OUTPUT_WIDTH=1080
OUTPUT_HEIGHT=1920
AUDIO_NORMALIZE=true
```

Собрать и запустить:

```bash
docker compose up -d --build
```

Открыть дэшборд:

```text
http://SERVER_IP:8000
```

Логи:

```bash
docker compose logs -f web
docker compose logs -f bot
```

Остановить:

```bash
docker compose down
```

Данные SQLite и видео хранятся в Docker volumes `app-data` и `app-storage`.

Для YouTube-загрузки используй инструкцию: [`docs/youtube-setup.md`](docs/youtube-setup.md).

Для TikTok-загрузки используй инструкцию: [`docs/tiktok-setup.md`](docs/tiktok-setup.md).

Для VPS/production используй отдельную инструкцию: [`docs/vps-deploy.md`](docs/vps-deploy.md).

## Админка и клиентский кабинет

В админке доступны:

- загрузка видео от имени администратора;
- статистика по задачам, ошибкам и публикациям;
- фильтры по статусу, клиенту и источнику загрузки;
- карточка задачи с MP4/SRT, подписью, транскриптом и публикациями;
- управление клиентами и персональным watermark-брендингом.

Клиентский кабинет открывается по ссылке из `/clients`. Клиент может сам загрузить видео, выбрать язык подписи, смотреть статусы своих задач и скачать готовый MP4/SRT. Публикации в YouTube/TikTok остаются под контролем администратора.

## Ручная установка без Docker

```bash
cd /home/ubuntu/video-social-bot
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Заполнить `.env`:

```env
TELEGRAM_BOT_TOKEN=...
OPENAI_API_KEY=...
LLM_API_KEY=...
ADMIN_USERNAME=admin
ADMIN_PASSWORD=strong-password
SECRET_KEY=random-long-secret
LOG_LEVEL=INFO
```

Для OpenRouter:

```env
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openai/gpt-4o-mini
```

Для другого провайдера поменять `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.

## Логирование и отладка

Уровень логов задаётся через `.env`:

```env
LOG_LEVEL=INFO
```

Для подробной отладки:

```env
LOG_LEVEL=DEBUG
```

Что логируется:

- старт/остановка web и bot;
- вход в админку;
- загрузка видео из Telegram и дэшборда;
- создание и обработка задач;
- FFmpeg/FFprobe команды;
- этапы Whisper и генерации подписи;
- ошибки worker-а и удаление просроченных задач.

Docker-логи:

```bash
docker compose logs -f web
docker compose logs -f bot
```

## Водяной знак / брендинг

Водяной знак выключен по умолчанию. Чтобы включить:

```env
WATERMARK_TEXT=@your_brand
WATERMARK_FONT_SIZE=42
WATERMARK_OPACITY=0.35
WATERMARK_POSITION=bottom-right
```

Доступные позиции:

- `top-left`
- `top-right`
- `bottom-left`
- `bottom-right`

Можно переопределить бренд-шаблон для конкретного клиента в админке `/clients`:

- текст водяного знака;
- позиция;
- прозрачность в процентах;
- размер шрифта.

Если у клиента задан свой текст водяного знака, он используется вместо глобального `WATERMARK_TEXT`. Если бренд клиента пустой, используется глобальная настройка из `.env`.

## Субтитры

После Whisper-транскрибации приложение может создать `.srt` файл. По умолчанию SRT включён, но не вшивается в видео:

```env
SUBTITLES_ENABLED=true
BURN_SUBTITLES=false
SUBTITLE_MAX_CHARS=42
SUBTITLE_FONT_SIZE=44
```

Режимы:

- `SUBTITLES_ENABLED=true`, `BURN_SUBTITLES=false` — готовое видео без субтитров + отдельный `.srt` файл.
- `SUBTITLES_ENABLED=true`, `BURN_SUBTITLES=true` — `.srt` файл + субтитры вшиваются в видео через FFmpeg.
- `SUBTITLES_ENABLED=false` — субтитры не создаются.

Whisper вызывается в `verbose_json` с segment timestamps, поэтому SRT строится по фактическим сегментам речи. Если провайдер не вернул сегменты, приложение использует fallback: равномерно распределяет текст по длительности видео.

## Качество видео и звук

Основные параметры FFmpeg:

```env
OUTPUT_WIDTH=1080
OUTPUT_HEIGHT=1920
OUTPUT_CRF=28
OUTPUT_AUDIO_BITRATE=96k
AUDIO_NORMALIZE=true
```

`OUTPUT_WIDTH`/`OUTPUT_HEIGHT` должны быть чётными. Для слабого VPS можно снизить до `720x1280`, чтобы ускорить обработку и уменьшить размер файла. `AUDIO_NORMALIZE=true` нормализует аудио при извлечении дорожки для Whisper.

## YouTube Shorts

После обработки видео админ может загрузить готовый MP4 в YouTube через официальный YouTube Data API сразу или запланировать публикацию по UTC-времени. Worker выполнит публикацию и сделает retry при временной ошибке. В карточке задачи можно отменить расписание, повторить failed-публикацию или сбросить ошибку.

Минимальные настройки:

```env
APP_BASE_URL=https://YOUR_DOMAIN
YOUTUBE_CLIENT_ID=...
YOUTUBE_CLIENT_SECRET=...
YOUTUBE_REDIRECT_URI=https://YOUR_DOMAIN/integrations/youtube/callback
YOUTUBE_TOKEN_PATH=/app/data/youtube-token.json
YOUTUBE_DEFAULT_PRIVACY_STATUS=private
YOUTUBE_PUBLISH_RETRY_LIMIT=3
YOUTUBE_PUBLISH_RETRY_DELAY_SECONDS=300
```

Полная инструкция: [`docs/youtube-setup.md`](docs/youtube-setup.md).

## TikTok

После обработки видео админ может отправить готовый MP4 в TikTok Inbox через официальный Content Posting API `video.upload` сразу или по расписанию. Загрузка идёт чанками, чтобы не держать весь видеофайл в памяти VPS. Финальный шаг публикации пользователь завершает в приложении TikTok.

Минимальные настройки:

```env
APP_BASE_URL=https://YOUR_DOMAIN
TIKTOK_CLIENT_KEY=...
TIKTOK_CLIENT_SECRET=...
TIKTOK_REDIRECT_URI=https://YOUR_DOMAIN/integrations/tiktok/callback
TIKTOK_SCOPES=video.upload
TIKTOK_TOKEN_PATH=/app/data/tiktok-token.json
```

Полная инструкция: [`docs/tiktok-setup.md`](docs/tiktok-setup.md).

## Ручная инициализация

```bash
. .venv/bin/activate
python -m video_social_bot.cli
```

## Ручной запуск дэшборда

```bash
. .venv/bin/activate
uvicorn video_social_bot.web:app --host 0.0.0.0 --port 8000
```

Открыть:

```text
http://SERVER_IP:8000
```

## Ручной запуск Telegram-бота

В другом процессе:

```bash
. .venv/bin/activate
python -m video_social_bot.bot
```

## Как работает очередь

В MVP используется простой встроенный worker:

- в боте worker запускается вместе с polling;
- в веб-приложении worker запускается вместе с FastAPI только при `WEB_WORKER_ENABLED=true`;
- обрабатывается одно видео за раз, что подходит для VPS 1 vCPU / 4 GB RAM;
- просроченные файлы и задачи удаляются после `FILE_TTL_HOURS`.

На production лучше запускать только один активный worker, чтобы два процесса не взяли одну задачу одновременно. В Docker Compose worker работает в сервисе `bot`, а дэшборд только создаёт задачи.

## Проверки

```bash
ruff check .
mypy src
pytest
```

GitHub Actions автоматически запускает эти проверки и Docker build для pull request-ов и push в `main`.

## Следующие этапы

1. Добавить бренд-шаблоны клиента.
2. Добавить точные word-level субтитры через провайдера с timestamps.
3. Добавить Instagram Graph API после подготовки Meta App.
4. Добавить TikTok direct post через `video.publish` после approval.
