# YouTube upload setup

The app uses the official YouTube Data API OAuth flow and uploads processed MP4 files through a resumable upload session.

## 1. Create Google Cloud OAuth app

1. Open Google Cloud Console: <https://console.cloud.google.com/>
2. Create or select a project.
3. Enable **YouTube Data API v3**.
4. Configure **OAuth consent screen**.
5. Create OAuth credentials:
   - Application type: **Web application**
   - Authorized redirect URI:

```text
https://YOUR_DOMAIN/integrations/youtube/callback
```

For local development:

```text
http://127.0.0.1:8000/integrations/youtube/callback
```

## 2. Configure `.env`

Docker/VPS:

```env
APP_BASE_URL=https://YOUR_DOMAIN
YOUTUBE_CLIENT_ID=...
YOUTUBE_CLIENT_SECRET=...
YOUTUBE_REDIRECT_URI=https://YOUR_DOMAIN/integrations/youtube/callback
YOUTUBE_TOKEN_PATH=/app/data/youtube-token.json
YOUTUBE_DEFAULT_PRIVACY_STATUS=private
```

Local:

```env
APP_BASE_URL=http://127.0.0.1:8000
YOUTUBE_CLIENT_ID=...
YOUTUBE_CLIENT_SECRET=...
YOUTUBE_REDIRECT_URI=http://127.0.0.1:8000/integrations/youtube/callback
YOUTUBE_TOKEN_PATH=./data/youtube-token.json
YOUTUBE_DEFAULT_PRIVACY_STATUS=private
```

## 3. Connect account

1. Open the dashboard.
2. Log in as admin.
3. Click **Подключить YouTube**.
4. Approve the Google OAuth request.

The OAuth token is stored in `YOUTUBE_TOKEN_PATH`. In Docker production this should be inside the persistent `app-data` volume.

## 4. Upload a processed video

1. Upload and process a video.
2. Open the completed job.
3. Choose `private`, `unlisted`, or `public`.
4. Click **Загрузить в YouTube**.

The dashboard stores the returned YouTube video id and shows a link to the uploaded video.

## Notes

- Keep `YOUTUBE_DEFAULT_PRIVACY_STATUS=private` while testing.
- Google may restrict uploads for new or unaudited apps/projects.
- Do not commit real Google OAuth client secrets or token files.
