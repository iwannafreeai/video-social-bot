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

Backup example:

```bash
mkdir -p backups
docker run --rm -v video-social-bot_app-data:/data -v "$PWD/backups:/backup" alpine tar czf /backup/app-data.tgz -C /data .
docker run --rm -v video-social-bot_app-storage:/storage -v "$PWD/backups:/backup" alpine tar czf /backup/app-storage.tgz -C /storage .
```

## 8. Reverse proxy

If you use Nginx/Caddy, proxy public HTTPS traffic to:

```text
http://127.0.0.1:8000
```

Keep the dashboard behind a strong `ADMIN_PASSWORD`.
