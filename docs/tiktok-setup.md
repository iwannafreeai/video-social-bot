# TikTok Content Posting API setup

The app uses official TikTok APIs:

- Login Kit OAuth v2 for user authorization.
- Content Posting API `video.upload` inbox upload flow.

This flow uploads the processed MP4 to the TikTok user's inbox. The user must open TikTok and complete the final editing/posting step from the inbox notification.

## 1. Create TikTok developer app

1. Open TikTok for Developers: <https://developers.tiktok.com/>
2. Create or select an app.
3. Enable **Login Kit** and **Content Posting API**.
4. Request/enable the `video.upload` scope.
5. Register the redirect URI:

```text
https://YOUR_DOMAIN/integrations/tiktok/callback
```

TikTok web redirect URIs must be absolute HTTPS URLs and must exactly match the value configured in the app.

## 2. Configure `.env`

Docker/VPS:

```env
APP_BASE_URL=https://YOUR_DOMAIN
TIKTOK_CLIENT_KEY=...
TIKTOK_CLIENT_SECRET=...
TIKTOK_REDIRECT_URI=https://YOUR_DOMAIN/integrations/tiktok/callback
TIKTOK_SCOPES=video.upload
TIKTOK_TOKEN_PATH=/app/data/tiktok-token.json
```

## 3. Connect account

1. Open the dashboard.
2. Log in as admin.
3. Click **Подключить TikTok**.
4. Approve TikTok OAuth.

The OAuth token is stored in `TIKTOK_TOKEN_PATH`. In Docker production this should be inside the persistent `app-data` volume.

## 4. Upload a processed video

1. Upload and process a video.
2. Open the completed job.
3. Click **Отправить в TikTok Inbox**.
4. Open TikTok and complete the final post from the inbox notification.

The dashboard stores the returned TikTok `publish_id` and can refresh the API status.

## Notes

- This integration uses `video.upload`, not direct public posting.
- Direct public posting requires TikTok approval for `video.publish` and extra creator-info/UX requirements.
- TikTok limits API uploads and pending shares; see official Content Posting API limits.
- Do not commit real TikTok client secrets or token files.
