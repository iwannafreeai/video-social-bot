# VPS deployment

## 1. Install Docker

Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

## 2. Clone and configure

```bash
git clone https://github.com/iwannafreeai/video-social-bot.git
cd video-social-bot
cp .env.production.example .env
nano .env
```

Required values:

- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`
- `LLM_API_KEY`
- `ADMIN_PASSWORD`
- `SECRET_KEY`
- `APP_BASE_URL`

Generate a secret key:

```bash
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

## 3. Start

```bash
docker compose up -d --build
```

Open:

```text
http://SERVER_IP:8000
```

Healthcheck:

```bash
curl -fsS http://127.0.0.1:8000/health
docker compose ps
```

The `web` service has a Docker healthcheck. The `bot` service waits until `web` is healthy before starting.

## 4. Logs

```bash
docker compose logs -f web
docker compose logs -f bot
```

For verbose logs, set this in `.env` and restart:

```env
LOG_LEVEL=DEBUG
```

```bash
docker compose up -d
```

## 5. Update

```bash
git pull --ff-only
docker compose up -d --build
```

## 6. Stop

```bash
docker compose down
```

Do not run `docker compose down -v` unless you intentionally want to delete SQLite data and stored videos.

## 7. Backups

Docker volumes:

- `video-social-bot_app-data` — SQLite database
- `video-social-bot_app-storage` — uploaded and processed files

Set a stable Compose project name in `.env` so volume names stay predictable:

```env
COMPOSE_PROJECT_NAME=video-social-bot
```

Create a backup:

```bash
./scripts/backup.sh
```

This creates:

```text
backups/video-social-bot-YYYYMMDDTHHMMSSZ/
├── app-data.tgz
├── app-storage.tgz
└── manifest.txt
```

Restore a backup:

```bash
docker compose down
./scripts/restore.sh backups/video-social-bot-YYYYMMDDTHHMMSSZ
docker compose up -d
```

Automated daily backup example:

```cron
15 3 * * * cd /opt/video-social-bot && ./scripts/backup.sh >> /var/log/video-social-bot-backup.log 2>&1
```

Copy backups off the VPS regularly, for example with `rsync` or your hosting provider snapshots.

## 8. Reverse proxy

If you use Nginx/Caddy, proxy public HTTPS traffic to:

```text
http://127.0.0.1:8000
```

Keep the dashboard behind a strong `ADMIN_PASSWORD`.
