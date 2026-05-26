from pathlib import Path

import httpx
import pytest
from asgi_lifespan import LifespanManager

from video_social_bot.config import get_settings
from video_social_bot.web import create_app


@pytest.mark.anyio
async def test_health_endpoint(tmp_path: Path) -> None:
    get_settings.cache_clear()
    settings = get_settings()
    settings.database_url = f"sqlite+aiosqlite:///{tmp_path / 'app.db'}"
    settings.storage_dir = tmp_path / "storage"
    app = create_app()

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "ok"
    assert payload["storage"] == "ok"
