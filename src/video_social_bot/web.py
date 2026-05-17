import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from video_social_bot.config import Settings, get_settings
from video_social_bot.db import create_engine, create_schema, create_session_factory
from video_social_bot.enums import CaptionLanguage, JobStatus, UploadSource
from video_social_bot.logging_config import configure_logging
from video_social_bot.models import Client
from video_social_bot.repositories import (
    create_video_job,
    get_client,
    get_job,
    list_clients,
    list_jobs,
    set_job_language,
    update_client_branding,
)
from video_social_bot.storage import ensure_storage_dirs, new_storage_path, save_upload_file
from video_social_bot.worker import JobWorker

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

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request,
        session: AsyncSession = Depends(get_session),
    ) -> HTMLResponse:
        require_auth(request)
        jobs = await list_jobs(session)
        clients = await list_clients(session)
        return templates.TemplateResponse(
            request,
            "index.html",
            {"jobs": jobs, "clients": clients, "settings": require_settings()},
        )

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "login.html", {"error": ""})

    @app.post("/login")
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
        suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
        destination = new_storage_path(settings, "incoming", suffix)
        logger.info(
            "Dashboard upload started: filename=%s destination=%s",
            file.filename,
            destination,
        )
        await save_upload_file(file, destination, settings.max_upload_mb * 1024 * 1024)
        job = await create_video_job(
            session=session,
            settings=settings,
            original_file_path=destination,
            source=UploadSource.DASHBOARD,
        )
        await set_job_language(session, job.id, language)
        await session.commit()
        logger.info("Dashboard job created: job_id=%s language=%s", job.id, language)
        return RedirectResponse("/", status_code=303)

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
        return templates.TemplateResponse(request, "job.html", {"job": job})

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
        try:
            payload = client_token_serializer().loads(token)
            client_id = int(payload["client_id"])
        except (BadSignature, KeyError, TypeError, ValueError):
            raise HTTPException(status_code=404) from None
        client = await get_client(session, client_id)
        if client is None:
            raise HTTPException(status_code=404)
        jobs = await list_jobs(session, client_id=client_id)
        return templates.TemplateResponse(request, "client.html", {"client": client, "jobs": jobs})

    return app


app = create_app()
