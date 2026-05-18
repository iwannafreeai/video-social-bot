# Video Social Bot

MVP для Telegram-бота и лёгкого FastAPI-дэшборда:

- загрузка вертикальных shorts/reels/tiktok-видео до 100 МБ;
- FFmpeg-ремастеринг в 9:16 с компрессией;
- транскрибация аудио через OpenAI Whisper API;
- генерация подписи на русском или английском через OpenAI-compatible LLM API;
- админка и клиентский кабинет;
- SQLite без отдельной БД;
- локальное хранение файлов с автоудалением через 24 часа;
- debug-логирование и опциональный водяной знак/брендинг;
- SRT-субтитры и опциональное вшивание субтитров в видео.

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

В MVP тайминги SRT распределяются равномерно по длительности видео на основе текста транскрипта. Для более точных word-level таймингов нужен провайдер транскрибации с timestamps.

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

## Следующие этапы

1. Добавить бренд-шаблоны клиента.
2. Добавить точные word-level субтитры через провайдера с timestamps.
3. Добавить OAuth и официальную публикацию YouTube.
4. Добавить Instagram Graph API после подготовки Meta App.
5. Добавить TikTok Content Posting API после approval.
