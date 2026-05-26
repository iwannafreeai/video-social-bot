import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from video_social_bot.config import Settings, get_settings
from video_social_bot.db import create_engine, create_schema, create_session_factory
from video_social_bot.enums import CaptionLanguage, JobStatus, UploadSource
from video_social_bot.logging_config import configure_logging
from video_social_bot.models import Client, VideoJob
from video_social_bot.repositories import (
    cancel_tiktok_upload,
    cancel_youtube_publish,
    create_video_job,
    get_client,
    get_job,
    list_clients,
    list_jobs,
    mark_tiktok_failed,
    mark_tiktok_uploaded,
    mark_youtube_published,
    retry_youtube_publish,
    schedule_tiktok_upload,
    schedule_youtube_publish,
    set_job_language,
    update_client_branding,
)
from video_social_bot.storage import ensure_storage_dirs, new_storage_path, save_upload_file
from video_social_bot.tiktok import (
    build_tiktok_auth_url,
    exchange_tiktok_code,
    fetch_tiktok_publish_status,
    save_tiktok_token,
    tiktok_configured,
    tiktok_connected,
    upload_tiktok_video_to_inbox,
)
from video_social_bot.worker import JobWorker
from video_social_bot.youtube import (
    build_youtube_auth_url,
    build_youtube_title,
    exchange_youtube_code,
    save_youtube_token,
    upload_youtube_video,
    youtube_configured,
    youtube_connected,
)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
logger = logging.getLogger(__name__)


class AppState:
    def __init__(self) -> None:
        self.settings: Settings | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None
        self.worker: JobWorker | None = None
        self.worker_task: asyncio.Task[None] | None = None


state = AppState()


def require_settings() -> Settings:
    if state.settings is None:
        raise RuntimeError("App settings are not initialized")
    return state.settings


def require_session_factory() -> async_sessionmaker[AsyncSession]:
    if state.session_factory is None:
        raise RuntimeError("Database is not initialized")
    return state.session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    session_factory = require_session_factory()
    async with session_factory() as session:
        yield session


def require_auth(request: Request) -> None:
    if not request.session.get("admin"):
        raise HTTPException(status_code=303, headers={"Location": "/login"})


def client_token_serializer() -> URLSafeSerializer:
    settings = require_settings()
    return URLSafeSerializer(settings.secret_key, salt="client-token")


def parse_client_token(token: str) -> int:
    try:
        payload = client_token_serializer().loads(token)
        return int(payload["client_id"])
    except (BadSignature, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=404) from None


def job_stats(jobs: list[VideoJob]) -> dict[str, int]:
    total = len(jobs)
    ready = sum(1 for job in jobs if job.status == JobStatus.READY)
    failed = sum(1 for job in jobs if job.status == JobStatus.FAILED)
    queued = sum(1 for job in jobs if job.status == JobStatus.QUEUED)
    processing = sum(1 for job in jobs if job.status == JobStatus.PROCESSING)
    youtube = sum(1 for job in jobs if job.youtube_video_id)
    tiktok = sum(1 for job in jobs if job.tiktok_publish_id)
    return {
        "total": total,
        "ready": ready,
        "failed": failed,
        "queued": queued,
        "processing": processing,
        "youtube": youtube,
        "tiktok": tiktok,
    }


def parse_optional_job_status(value: str) -> JobStatus | None:
    if not value:
        return None
    try:
        return JobStatus(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job status") from None


def parse_optional_upload_source(value: str) -> UploadSource | None:
    if not value:
        return None
    try:
        return UploadSource(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid upload source") from None


def parse_optional_client_id(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid client_id") from None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    logger.info("Starting web app")
    ensure_storage_dirs(settings)
    engine = create_engine(settings)
    await create_schema(engine)
    session_factory = create_session_factory(engine)
    state.settings = settings
    state.session_factory = session_factory
    if settings.web_worker_enabled:
        logger.info("Starting web worker")
        state.worker = JobWorker(settings, session_factory)
        state.worker_task = asyncio.create_task(state.worker.run_forever())
    yield
    if state.worker is not None:
        state.worker.stop()
    if state.worker_task is not None:
        state.worker_task.cancel()
    await engine.dispose()
    logger.info("Web app stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

    @app.get("/health")
    async def health(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
        settings = require_settings()
        await session.execute(text("SELECT 1"))
        storage_exists = settings.storage_dir.exists()
        data_path = Path(settings.database_url.removeprefix("sqlite+aiosqlite:///"))
        database_ready = not settings.database_url.startswith("sqlite+aiosqlite:///") or (
            data_path == Path(":memory:") or data_path.exists()
        )
        return {
            "status": "ok",
            "database": "ok" if database_ready else "missing",
            "storage": "ok" if storage_exists else "missing",
            "worker": "enabled" if settings.web_worker_enabled else "external",
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request,
        status: str = "",
        client_id: str = "",
        source: str = "",
        session: AsyncSession = Depends(get_session),
    ) -> HTMLResponse:
        require_auth(request)
        selected_status = parse_optional_job_status(status)
        selected_client_id = parse_optional_client_id(client_id)
        selected_source = parse_optional_upload_source(source)
        jobs = await list_jobs(
            session,
            status=selected_status,
            client_id=selected_client_id,
            source=selected_source,
        )
        all_jobs = await list_jobs(session)
        clients = await list_clients(session)
        client_names = {client.id: client.name for client in clients}
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "jobs": jobs,
                "clients": clients,
                "client_names": client_names,
                "stats": job_stats(all_jobs),
                "selected_status": selected_status,
                "selected_client_id": selected_client_id,
                "selected_source": selected_source,
                "job_statuses": list(JobStatus),
                "upload_sources": list(UploadSource),
                "settings": require_settings(),
                "youtube_connected": youtube_connected(require_settings()),
                "youtube_configured": youtube_configured(require_settings()),
                "tiktok_connected": tiktok_connected(require_settings()),
                "tiktok_configured": tiktok_configured(require_settings()),
            },
        )

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "login.html", {"error": ""})

    @app.post("/login", response_model=None)
    async def login(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ) -> RedirectResponse | HTMLResponse:
        settings = require_settings()
        if username == settings.admin_username and password == settings.admin_password:
            logger.info("Admin login succeeded")
            request.session["admin"] = True
            return RedirectResponse("/", status_code=303)
        logger.warning("Admin login failed: username=%s", username)
        return templates.TemplateResponse(request, "login.html", {"error": "Неверный логин/пароль"})

    @app.post("/logout")
    async def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.post("/jobs")
    async def create_dashboard_job(
        request: Request,
        file: UploadFile,
        language: CaptionLanguage = Form(...),
        session: AsyncSession = Depends(get_session),
    ) -> RedirectResponse:
        require_auth(request)
        settings = require_settings()
        logger.info(
            "Dashboard upload started: filename=%s",
            file.filename,
        )
        try:
            job = await create_uploaded_job(
                session=session,
                settings=settings,
                file=file,
                language=language,
                source=UploadSource.DASHBOARD,
                client_id=None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        await session.commit()
        logger.info("Dashboard job created: job_id=%s language=%s", job.id, language)
        return RedirectResponse("/", status_code=303)

    async def create_uploaded_job(
        session: AsyncSession,
        settings: Settings,
        file: UploadFile,
        language: CaptionLanguage,
        source: UploadSource,
        client_id: int | None,
    ) -> VideoJob:
        suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
        destination = new_storage_path(settings, "incoming", suffix)
        await save_upload_file(file, destination, settings.max_upload_mb * 1024 * 1024)
        job = await create_video_job(
            session=session,
            settings=settings,
            original_file_path=destination,
            source=source,
            client_id=client_id,
        )
        await set_job_language(session, job.id, language)
        return job

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    async def job_detail(
        request: Request,
        job_id: int,
        session: AsyncSession = Depends(get_session),
    ) -> HTMLResponse:
        require_auth(request)
        job = await get_job(session, job_id)
        if job is None:
            raise HTTPException(status_code=404)
        settings = require_settings()
        return templates.TemplateResponse(
            request,
            "job.html",
            {
                "job": job,
                "settings": settings,
                "youtube_connected": youtube_connected(settings),
                "youtube_configured": youtube_configured(settings),
                "tiktok_connected": tiktok_connected(settings),
                "tiktok_configured": tiktok_configured(settings),
            },
        )

    @app.get("/integrations/youtube/connect")
    async def connect_youtube(request: Request) -> RedirectResponse:
        require_auth(request)
        settings = require_settings()
        if not youtube_configured(settings):
            raise HTTPException(status_code=400, detail="YouTube OAuth is not configured")
        state_token = client_token_serializer().dumps({"integration": "youtube"})
        request.session["youtube_oauth_state"] = state_token
        return RedirectResponse(build_youtube_auth_url(settings, state_token), status_code=303)

    @app.get("/integrations/tiktok/connect")
    async def connect_tiktok(request: Request) -> RedirectResponse:
        require_auth(request)
        settings = require_settings()
        if not tiktok_configured(settings):
            raise HTTPException(status_code=400, detail="TikTok OAuth is not configured")
        state_token = client_token_serializer().dumps({"integration": "tiktok"})
        request.session["tiktok_oauth_state"] = state_token
        return RedirectResponse(build_tiktok_auth_url(settings, state_token), status_code=303)

    @app.get("/integrations/tiktok/callback")
    async def tiktok_callback(
        request: Request,
        code: str,
        state: str,
    ) -> RedirectResponse:
        require_auth(request)
        stored_state = request.session.get("tiktok_oauth_state")
        if not isinstance(stored_state, str) or state != stored_state:
            raise HTTPException(status_code=400, detail="Invalid TikTok OAuth state")
        settings = require_settings()
        if not tiktok_configured(settings):
            raise HTTPException(status_code=400, detail="TikTok OAuth is not configured")
        token = await exchange_tiktok_code(settings, code)
        save_tiktok_token(settings, token)
        request.session.pop("tiktok_oauth_state", None)
        logger.info("TikTok account connected")
        return RedirectResponse("/", status_code=303)

    @app.get("/integrations/youtube/callback")
    async def youtube_callback(
        request: Request,
        code: str,
        state: str,
    ) -> RedirectResponse:
        require_auth(request)
        stored_state = request.session.get("youtube_oauth_state")
        if not isinstance(stored_state, str) or state != stored_state:
            raise HTTPException(status_code=400, detail="Invalid YouTube OAuth state")
        settings = require_settings()
        token = await exchange_youtube_code(settings, code)
        save_youtube_token(settings, token)
        request.session.pop("youtube_oauth_state", None)
        logger.info("YouTube account connected")
        return RedirectResponse("/", status_code=303)

    @app.post("/jobs/{job_id}/youtube")
    async def publish_job_to_youtube(
        request: Request,
        job_id: int,
        privacy_status: str = Form(...),
        session: AsyncSession = Depends(get_session),
    ) -> RedirectResponse:
        require_auth(request)
        if privacy_status not in {"private", "unlisted", "public"}:
            raise HTTPException(status_code=400, detail="Invalid YouTube privacy status")
        settings = require_settings()
        if not youtube_configured(settings) or not youtube_connected(settings):
            raise HTTPException(status_code=400, detail="YouTube account is not connected")
        job = await get_job(session, job_id)
        if job is None or job.status != JobStatus.READY or not job.processed_file_path:
            raise HTTPException(status_code=404)
        video_id = await upload_youtube_video(
            settings=settings,
            video_path=Path(job.processed_file_path),
            title=build_youtube_title(job.id, job.caption),
            description=job.caption or "",
            privacy_status=privacy_status,
        )
        await mark_youtube_published(session, job, video_id)
        await session.commit()
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.post("/jobs/{job_id}/youtube/cancel")
    async def cancel_job_youtube_publish(
        request: Request,
        job_id: int,
        session: AsyncSession = Depends(get_session),
    ) -> RedirectResponse:
        require_auth(request)
        job = await get_job(session, job_id)
        if job is None or job.youtube_publish_status not in {"scheduled", "failed"}:
            raise HTTPException(status_code=404)
        await cancel_youtube_publish(session, job)
        await session.commit()
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.post("/jobs/{job_id}/youtube/retry")
    async def retry_job_youtube_publish(
        request: Request,
        job_id: int,
        session: AsyncSession = Depends(get_session),
    ) -> RedirectResponse:
        require_auth(request)
        job = await get_job(session, job_id)
        if job is None or job.youtube_publish_status != "failed":
            raise HTTPException(status_code=404)
        await retry_youtube_publish(session, job)
        await session.commit()
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.post("/jobs/{job_id}/tiktok")
    async def upload_job_to_tiktok(
        request: Request,
        job_id: int,
        session: AsyncSession = Depends(get_session),
    ) -> RedirectResponse:
        require_auth(request)
        settings = require_settings()
        if not tiktok_configured(settings) or not tiktok_connected(settings):
            raise HTTPException(status_code=400, detail="TikTok account is not connected")
        job = await get_job(session, job_id)
        if job is None or job.status != JobStatus.READY or not job.processed_file_path:
            raise HTTPException(status_code=404)
        try:
            result = await upload_tiktok_video_to_inbox(settings, Path(job.processed_file_path))
        except Exception as exc:
            await mark_tiktok_failed(session, job, str(exc))
            await session.commit()
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        await mark_tiktok_uploaded(session, job, result.publish_id)
        await session.commit()
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.post("/jobs/{job_id}/tiktok/schedule")
    async def schedule_job_to_tiktok(
        request: Request,
        job_id: int,
        scheduled_at: str = Form(...),
        session: AsyncSession = Depends(get_session),
    ) -> RedirectResponse:
        require_auth(request)
        settings = require_settings()
        if not tiktok_configured(settings) or not tiktok_connected(settings):
            raise HTTPException(status_code=400, detail="TikTok account is not connected")
        job = await get_job(session, job_id)
        if job is None or job.status != JobStatus.READY or not job.processed_file_path:
            raise HTTPException(status_code=404)
        try:
            parsed_scheduled_at = datetime.fromisoformat(scheduled_at)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid scheduled_at") from None
        if parsed_scheduled_at.tzinfo is None:
            parsed_scheduled_at = parsed_scheduled_at.replace(tzinfo=UTC)
        await schedule_tiktok_upload(session, job, parsed_scheduled_at)
        await session.commit()
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.post("/jobs/{job_id}/tiktok/cancel")
    async def cancel_job_tiktok_upload(
        request: Request,
        job_id: int,
        session: AsyncSession = Depends(get_session),
    ) -> RedirectResponse:
        require_auth(request)
        job = await get_job(session, job_id)
        if job is None or job.tiktok_publish_status not in {"scheduled", "failed"}:
            raise HTTPException(status_code=404)
        await cancel_tiktok_upload(session, job)
        await session.commit()
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.post("/jobs/{job_id}/tiktok/status")
    async def refresh_job_tiktok_status(
        request: Request,
        job_id: int,
        session: AsyncSession = Depends(get_session),
    ) -> RedirectResponse:
        require_auth(request)
        settings = require_settings()
        if not tiktok_configured(settings) or not tiktok_connected(settings):
            raise HTTPException(status_code=400, detail="TikTok account is not connected")
        job = await get_job(session, job_id)
        if job is None or not job.tiktok_publish_id:
            raise HTTPException(status_code=404)
        try:
            job.tiktok_publish_status = await fetch_tiktok_publish_status(
                settings,
                job.tiktok_publish_id,
            )
            job.tiktok_publish_error = None
        except Exception as exc:
            await mark_tiktok_failed(session, job, str(exc))
        await session.commit()
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.post("/jobs/{job_id}/youtube/schedule")
    async def schedule_job_to_youtube(
        request: Request,
        job_id: int,
        scheduled_at: str = Form(...),
        privacy_status: str = Form(...),
        session: AsyncSession = Depends(get_session),
    ) -> RedirectResponse:
        require_auth(request)
        if privacy_status not in {"private", "unlisted", "public"}:
            raise HTTPException(status_code=400, detail="Invalid YouTube privacy status")
        settings = require_settings()
        if not youtube_configured(settings) or not youtube_connected(settings):
            raise HTTPException(status_code=400, detail="YouTube account is not connected")
        job = await get_job(session, job_id)
        if job is None or job.status != JobStatus.READY or not job.processed_file_path:
            raise HTTPException(status_code=404)
        try:
            parsed_scheduled_at = datetime.fromisoformat(scheduled_at)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid scheduled_at") from None
        if parsed_scheduled_at.tzinfo is None:
            parsed_scheduled_at = parsed_scheduled_at.replace(tzinfo=UTC)
        await schedule_youtube_publish(session, job, parsed_scheduled_at, privacy_status)
        await session.commit()
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.get("/jobs/{job_id}/download")
    async def download_job(
        request: Request,
        job_id: int,
        session: AsyncSession = Depends(get_session),
    ) -> FileResponse:
        require_auth(request)
        job = await get_job(session, job_id)
        if job is None or job.status != JobStatus.READY or not job.processed_file_path:
            raise HTTPException(status_code=404)
        return FileResponse(job.processed_file_path, filename=f"processed-{job.id}.mp4")

    @app.get("/jobs/{job_id}/subtitles")
    async def download_subtitles(
        request: Request,
        job_id: int,
        session: AsyncSession = Depends(get_session),
    ) -> FileResponse:
        require_auth(request)
        job = await get_job(session, job_id)
        if job is None or job.status != JobStatus.READY or not job.subtitle_file_path:
            raise HTTPException(status_code=404)
        return FileResponse(job.subtitle_file_path, filename=f"subtitles-{job.id}.srt")

    @app.get("/clients", response_class=HTMLResponse)
    async def clients(
        request: Request,
        session: AsyncSession = Depends(get_session),
    ) -> HTMLResponse:
        require_auth(request)
        items = await list_clients(session)
        serializer = client_token_serializer()
        tokens = {client.id: serializer.dumps({"client_id": client.id}) for client in items}
        return templates.TemplateResponse(
            request,
            "clients.html",
            {"clients": items, "tokens": tokens},
        )

    @app.post("/clients")
    async def create_client(
        request: Request,
        name: str = Form(...),
        session: AsyncSession = Depends(get_session),
    ) -> RedirectResponse:
        require_auth(request)
        session.add(Client(name=name))
        await session.commit()
        return RedirectResponse("/clients", status_code=303)

    @app.post("/clients/{client_id}/branding")
    async def update_branding(
        request: Request,
        client_id: int,
        watermark_text: str = Form(""),
        watermark_position: str = Form("bottom-right"),
        watermark_opacity: int = Form(35),
        watermark_font_size: int = Form(42),
        session: AsyncSession = Depends(get_session),
    ) -> RedirectResponse:
        require_auth(request)
        if watermark_position not in {"top-left", "top-right", "bottom-left", "bottom-right"}:
            raise HTTPException(status_code=400)
        if watermark_opacity < 0 or watermark_opacity > 100:
            raise HTTPException(status_code=400)
        if watermark_font_size < 12 or watermark_font_size > 120:
            raise HTTPException(status_code=400)
        client = await update_client_branding(
            session=session,
            client_id=client_id,
            watermark_text=watermark_text,
            watermark_position=watermark_position,
            watermark_opacity=watermark_opacity,
            watermark_font_size=watermark_font_size,
        )
        if client is None:
            raise HTTPException(status_code=404)
        await session.commit()
        logger.info("Client branding updated: client_id=%s", client_id)
        return RedirectResponse("/clients", status_code=303)

    @app.get("/client/{token}", response_class=HTMLResponse)
    async def client_cabinet(
        request: Request,
        token: str,
        session: AsyncSession = Depends(get_session),
    ) -> HTMLResponse:
        client_id = parse_client_token(token)
        client = await get_client(session, client_id)
        if client is None:
            raise HTTPException(status_code=404)
        jobs = await list_jobs(session, client_id=client_id)
        return templates.TemplateResponse(
            request,
            "client.html",
            {
                "client": client,
                "jobs": jobs,
                "token": token,
                "settings": require_settings(),
                "stats": job_stats(jobs),
            },
        )

    @app.post("/client/{token}/jobs")
    async def create_client_job(
        request: Request,
        token: str,
        file: UploadFile,
        language: CaptionLanguage = Form(...),
        session: AsyncSession = Depends(get_session),
    ) -> RedirectResponse:
        client_id = parse_client_token(token)
        client = await get_client(session, client_id)
        if client is None:
            raise HTTPException(status_code=404)
        settings = require_settings()
        try:
            job = await create_uploaded_job(
                session=session,
                settings=settings,
                file=file,
                language=language,
                source=UploadSource.CLIENT_PORTAL,
                client_id=client.id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        await session.commit()
        logger.info("Client portal job created: client_id=%s job_id=%s", client.id, job.id)
        return RedirectResponse(f"/client/{token}", status_code=303)

    @app.get("/client/{token}/jobs/{job_id}/download")
    async def download_client_job(
        request: Request,
        token: str,
        job_id: int,
        session: AsyncSession = Depends(get_session),
    ) -> FileResponse:
        client_id = parse_client_token(token)
        job = await get_job(session, job_id)
        if (
            job is None
            or job.client_id != client_id
            or job.status != JobStatus.READY
            or not job.processed_file_path
        ):
            raise HTTPException(status_code=404)
        return FileResponse(job.processed_file_path, filename=f"processed-{job.id}.mp4")

    @app.get("/client/{token}/jobs/{job_id}/subtitles")
    async def download_client_subtitles(
        request: Request,
        token: str,
        job_id: int,
        session: AsyncSession = Depends(get_session),
    ) -> FileResponse:
        client_id = parse_client_token(token)
        job = await get_job(session, job_id)
        if (
            job is None
            or job.client_id != client_id
            or job.status != JobStatus.READY
            or not job.subtitle_file_path
        ):
            raise HTTPException(status_code=404)
        return FileResponse(job.subtitle_file_path, filename=f"subtitles-{job.id}.srt")

    return app


app = create_app()
