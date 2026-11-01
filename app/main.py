"""FastAPI application factory: lifespan, errors, CORS and static dashboard."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import stream
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.db.init import init_database
from app.db.session import dispose_engine
from app.notifications.dispatcher import NotificationDispatcher
from app.providers.registry import build_providers
from app.scanner.runner import ScannerRunner
from app.services.events import EventHub

logger = get_logger(__name__)


async def _notification_loop(dispatcher: NotificationDispatcher) -> None:
    while True:
        try:
            await dispatcher.dispatch_pending()
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception:  # noqa: BLE001
            logger.exception("notification_loop_failed")
        await asyncio.sleep(20)


def _error_body(code: str, message: str, details: dict | None, request_id: str) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        }
    }


def create_app(*, start_scanner: bool = True) -> FastAPI:
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_database()
        providers = build_providers()
        hub = EventHub()
        dispatcher = NotificationDispatcher(providers.discord, hub)
        scanner = ScannerRunner(providers, hub, dispatcher)

        app.state.providers = providers
        app.state.hub = hub
        app.state.dispatcher = dispatcher
        app.state.scanner = scanner

        await scanner.startup()
        if start_scanner and scanner.enabled:
            await scanner.start()
        notify_task = asyncio.create_task(_notification_loop(dispatcher), name="notifications")
        logger.info("app_started", extra={"environment": settings.app_env})
        try:
            yield
        finally:
            notify_task.cancel()
            try:
                await notify_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            await scanner.stop()
            await providers.close()
            await dispose_engine()
            logger.info("app_stopped")

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description=(
            "Paper-only new-coin research lab for Solana and BNB Chain. "
            "No wallets, no private keys, no real orders."
        ),
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    origins = settings.cors_origin_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        if not request.url.path.startswith("/api"):
            # Static dashboard assets must revalidate so a deploy never serves a
            # stale module against a newer shell.
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.details, request_id),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        return JSONResponse(
            status_code=422,
            content=_error_body(
                "VALIDATION_ERROR",
                "Request validation failed.",
                {"errors": exc.errors()},
                request_id,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(code, str(exc.detail), {}, request_id),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        logger.exception("unhandled_error", extra={"request_id": request_id, "path": request.url.path})
        return JSONResponse(
            status_code=500,
            content=_error_body(
                "INTERNAL_ERROR", "Unexpected server error.", {"request_id": request_id}, request_id
            ),
        )

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(stream.router, prefix="/api/v1")

    @app.get("/api", include_in_schema=False)
    async def api_root() -> dict:
        return {
            "name": settings.app_name,
            "version": settings.version,
            "paper_only": True,
            "docs": "/api/docs",
            "api": "/api/v1",
        }

    frontend_dir = Path(settings.static_dir)
    if frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


app = create_app()
