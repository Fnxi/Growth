import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel

from app.api import assistant, auth, campaigns, dashboard, distribution_events, experiment_results, experiments, metric_definitions, operational_intelligence, posts, snapshots, system, tracking
from app.config import Settings, get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


class HealthResponse(BaseModel):
    status: str


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = _content_security_policy(request.url.path, self.settings)
        if self.settings.security_hsts_enabled:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Growth Hacking Lab API", version="0.1.0", description="MVP de medicion externa para El Hilo MX.", docs_url="/docs" if settings.docs_enabled else None, redoc_url="/redoc" if settings.docs_enabled else None, openapi_url="/openapi.json" if settings.docs_enabled else None)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_allowed_origins), allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-System-Check-Token"])
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)

    @app.exception_handler(RequestValidationError)
    async def auth_validation_error(request: Request, _error: RequestValidationError) -> JSONResponse:
        if request.url.path == "/auth/refresh":
            return JSONResponse(status_code=401, content={"detail": "Invalid refresh token."})
        if request.url.path == "/auth/login":
            return JSONResponse(status_code=401, content={"detail": "Invalid credentials."})
        return JSONResponse(status_code=422, content=jsonable_encoder({"detail": _error.errors()}))

    for router in (auth.router, posts.router, campaigns.router, experiments.router, metric_definitions.router, snapshots.router, distribution_events.router, tracking.router, dashboard.router, experiment_results.router, system.router, assistant.router, operational_intelligence.router):
        app.include_router(router)

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health_check() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()


def _content_security_policy(path: str, settings: Settings) -> str:
    if settings.docs_enabled and path in {"/docs", "/redoc"}:
        return "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https:; font-src 'self' data: https://cdn.jsdelivr.net; connect-src 'self'"
    return "default-src 'none'; base-uri 'none'; frame-ancestors 'none'"
