# Video Social Bot

MVP для Telegram-бота и лёгкого FastAPI-дэшборда:

- загрузка вертикальных shorts/reels/tiktok-видео до 100 МБ;
- FFmpeg-ремастеринг в 9:16 с компрессией;
- транскрибация аудио через OpenAI Whisper API;
- генерация подписи на русском или английском через OpenAI-compatible LLM API;
- админка и клиентский кабинет;
- SQLite без отдельной БД;
- локальное хранение файлов с автоудалением через 24 часа.

## Безопасная модель публикации

Этот MVP не автоматизирует обход антиспама и не пытается маскировать чужой контент. Пайплайн делает легитимный ремастеринг: нормализация 9:16, компрессия, лёгкая цветокоррекция и новая подпись. Для YouTube/TikTok/Instagram прямую публикацию лучше добавлять следующим этапом через официальные API после approvals.

## Требования

- Python 3.12+
- FFmpeg и FFprobe
- Telegram bot token
- OpenAI API key для Whisper
- LLM API key: OpenRouter по умолчанию или любой совместимый с OpenAI Chat Completions API

## Установка

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
```

Для OpenRouter:

```env
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openai/gpt-4o-mini
```

Для другого провайдера поменять `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.

## Инициализация

```bash
. .venv/bin/activate
python -m video_social_bot.cli
```

## Запуск дэшборда

```bash
. .venv/bin/activate
uvicorn video_social_bot.web:app --host 0.0.0.0 --port 8000
```

Открыть:

```text
http://SERVER_IP:8000
```

## Запуск Telegram-бота

В другом процессе:

```bash
. .venv/bin/activate
python -m video_social_bot.bot
```

## Как работает очередь

В MVP используется простой встроенный worker:

- в боте worker запускается вместе с polling;
- в веб-приложении worker запускается вместе с FastAPI;
- обрабатывается одно видео за раз, что подходит для VPS 1 vCPU / 4 GB RAM;
- просроченные файлы и задачи удаляются после `FILE_TTL_HOURS`.

На production лучше запускать только один активный worker, чтобы два процесса не взяли одну задачу одновременно. Простой вариант: использовать Telegram-бот как worker, а у веб-дашборда позже отключить worker флагом.

## Проверки

```bash
ruff check .
mypy src
pytest
```

## Следующие этапы

1. Добавить водяной знак/бренд-шаблоны клиента.
2. Добавить авто-субтитры через SRT/ASS.
3. Добавить OAuth и официальную публикацию YouTube.
4. Добавить Instagram Graph API после подготовки Meta App.
5. Добавить TikTok Content Posting API после approval.
