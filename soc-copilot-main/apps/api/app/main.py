import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db
from app.routers import (
    admin,
    alerts,
    auth,
    chat,
    explain,
    health,
    integrations,
    kb,
    llm,
    mfa,
    recommend,
    reports,
    stats,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    poller: asyncio.Task | None = None
    # Optional Wazuh Indexer poller (pull mode). Off unless both the
    # indexer URL and a poll interval are configured.
    if settings.wazuh_pull_enabled and settings.wazuh_poll_interval_seconds > 0:
        from app.db import _SessionLocal
        from app.services.wazuh import poll_forever

        poller = asyncio.create_task(poll_forever(_SessionLocal))
    yield
    if poller is not None:
        poller.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await poller


# In production we hide Swagger/ReDoc + the OpenAPI schema. They leak the
# full API surface (auth flows, admin endpoints) and aren't needed by end
# users. Re-enable behind admin auth if/when needed.
_docs_url = None if settings.is_production else "/docs"
_redoc_url = None if settings.is_production else "/redoc"
_openapi_url = None if settings.is_production else "/openapi.json"

app = FastAPI(
    title="SOC Copilot API",
    description="AI Copilot for Junior SOC Analysts — Blue Team",
    version="0.2.0",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

# Credentialed CORS: never use "*", and enumerate allowed methods/headers
# explicitly. Browsers reject wildcards together with credentials anyway,
# but being explicit prevents a future config mistake from opening CSRF.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Requested-With",
        "Accept-Language",
    ],
    max_age=600,
)


@app.middleware("http")
async def security_headers(request, call_next):
    """Defense-in-depth headers applied to every API response."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
    )
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=63072000; includeSubDomains; preload",
        )
    return response

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(mfa.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(explain.router, prefix="/api")
app.include_router(recommend.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(kb.router, prefix="/api")
app.include_router(llm.router, prefix="/api")
app.include_router(integrations.router, prefix="/api")
app.include_router(reports.router, prefix="/api")


@app.get("/")
def root():
    payload = {"name": "soc-copilot-api", "version": app.version}
    if _docs_url:
        payload["docs"] = _docs_url
    return payload
