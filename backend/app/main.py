import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1 import api_router
from app.core.config import settings
from app.core.logging_setup import configure_logging, get_logger
from app.core.middleware import RequestIdMiddleware
from app.core.rate_limit import limiter

configure_logging()
log = get_logger("app.main")

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup", extra={"env": settings.environment, "app": settings.app_name})
    # CORS is the one production setting that is wrong *silently*. A deployment
    # left on the shipped default boots, passes its healthcheck and serves the
    # API perfectly — and every browser request from the real domain is refused
    # by the browser, so the only evidence is in a console nobody on the shop
    # floor opens. Not fatal, because a same-origin deploy needs no origins at
    # all; loud, because the alternative is an afternoon of "the site is blank".
    if settings.environment.lower() not in ("development", "test", "ci"):
        local = [o for o in settings.cors_origins
                 if "localhost" in o or "127.0.0.1" in o]
        if local:
            log.warning(
                "CORS_ORIGINS still contains local addresses in a non-development "
                "environment — browser requests from the real domain will be "
                "refused unless the frontend is served from this same origin",
                extra={"cors_origins": settings.cors_origins},
            )
    yield
    log.info("shutdown")


# The interactive docs are a development tool. In production they publish the
# whole endpoint map — every path, every field name, every enum value — to
# anyone who asks, without a login. That is a map of the shop's operations
# handed to whoever finds the host, and nobody on the counter has ever needed
# it. Off outside development, and still one env var away for a deployment that
# genuinely wants them.
_docs_on = settings.environment.lower() in ("development", "test", "ci") or (
    os.getenv("EXPOSE_API_DOCS", "").strip().lower() in ("1", "true", "yes")
)

app = FastAPI(
    title=settings.app_name,
    version="0.5.0",
    debug=settings.debug,
    lifespan=lifespan,
    docs_url="/docs" if _docs_on else None,
    redoc_url="/redoc" if _docs_on else None,
    openapi_url="/openapi.json" if _docs_on else None,
)

# Rate limiting (slowapi)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Request-ID + JSON access log
app.add_middleware(RequestIdMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

app.mount("/static", StaticFiles(directory=str(UPLOAD_DIR)), name="static")


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name, "env": settings.environment}


app.include_router(api_router, prefix=settings.api_v1_prefix)
