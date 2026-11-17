import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .limits import BodyLimit
from .db import Base, SessionLocal, engine
from .models import Language
from .routers import admin, auth, consultations, content, files, health, language, misc, payments, portal, providers, realtime
from .services import reminders

log = logging.getLogger("medcart")
LANGS = [("en", "English", True, True), ("tw", "Twi", False, False), ("ha", "Hausa", False, False),
         ("fat", "Fante", False, False), ("fr", "Français", True, True), ("es", "Español", True, True)]


def production_guard() -> None:
    s = get_settings()
    if s.env != "production":
        return
    problems = []
    if s.jwt_secret.startswith("CHANGE-ME") or len(s.jwt_secret) < 32:
        problems.append("MEDCART_JWT_SECRET must be a random string of 32+ characters")
    if not s.data_encryption_keys:
        problems.append("MEDCART_DATA_ENCRYPTION_KEYS is required")
    if s.payment_mode != "live" or not s.paystack_secret_key:
        problems.append("MEDCART_PAYMENT_MODE=live and MEDCART_PAYSTACK_SECRET_KEY are required")
    if s.database_url.startswith("sqlite"):
        problems.append("use PostgreSQL in production")
    if any("localhost" in o for o in s.cors_origins):
        problems.append("MEDCART_CORS_ORIGINS must list only your real web origins")
    if problems:
        raise RuntimeError("Unsafe production configuration:\n - " + "\n - ".join(problems))


async def _scheduler():
    s = get_settings()
    while True:
        await asyncio.sleep(s.scheduler_interval_seconds)
        try:
            with SessionLocal() as db:
                log.info("scheduler: %s", await asyncio.to_thread(reminders.run_all, db))
        except Exception:  # noqa: BLE001
            log.exception("scheduler run failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    production_guard()
    if get_settings().env != "production":
        Base.metadata.create_all(engine)  # dev/test convenience; production schema is managed ONLY by `alembic upgrade head`
    with SessionLocal() as db:
        for code, name, stt, tts in LANGS:
            if not db.get(Language, code):
                db.add(Language(code=code, name=name, stt_supported=stt, tts_supported=tts))
        db.commit()
    task = asyncio.create_task(_scheduler()) if get_settings().scheduler_enabled else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="MedCart API", version="1.0.0", lifespan=lifespan, docs_url=None if get_settings().env == "production" else "/docs",
              redoc_url=None, openapi_url=None if get_settings().env == "production" else "/openapi.json")
app.add_middleware(BodyLimit)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   allow_headers=["Authorization", "Content-Type", "Idempotency-Key"], max_age=600)


from fastapi.responses import JSONResponse  # noqa: E402
from sqlalchemy.exc import DataError, IntegrityError  # noqa: E402


@app.exception_handler(DataError)
async def data_error(request: Request, exc: DataError):
    """Out-of-range numbers / NUL bytes etc. rejected by the database are the client's fault, not a server error."""
    log.warning("DataError on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Invalid value in request"}, status_code=422)


@app.exception_handler(OverflowError)
async def overflow_error(request: Request, exc: OverflowError):  # SQLite raises this where PostgreSQL raises DataError
    return JSONResponse({"detail": "Invalid value in request"}, status_code=422)


@app.exception_handler(IntegrityError)
async def integrity_error(request: Request, exc: IntegrityError):
    log.warning("IntegrityError on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Request conflicts with existing data"}, status_code=409)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                         "Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
                         "Permissions-Policy": "geolocation=(), camera=(), microphone=()"})
    if get_settings().env == "production":
        resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return resp


for r in (auth, providers, consultations, health, content, payments, admin, portal, misc, files, language, realtime):
    app.include_router(r.router, prefix="/api/v1")


@app.get("/healthz")
def healthz():
    return {"ok": True}
