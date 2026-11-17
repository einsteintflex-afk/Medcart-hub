from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .db import Base, SessionLocal, engine
from .models import Language
from .routers import admin, auth, consultations, content, health, misc, payments, portal, providers

LANGS = [("en", "English", True, True), ("tw", "Twi", False, False), ("ha", "Hausa", False, False),
         ("fat", "Fante", False, False), ("fr", "Français", True, True), ("es", "Español", True, True)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)  # use Alembic migrations in production
    with SessionLocal() as db:
        for code, name, stt, tts in LANGS:
            if not db.get(Language, code):
                db.add(Language(code=code, name=name, stt_supported=stt, tts_supported=tts))
        db.commit()
    yield


app = FastAPI(title="MedCart API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
for r in (auth, providers, consultations, health, content, payments, admin, portal, misc):
    app.include_router(r.router, prefix="/api/v1")


@app.get("/healthz")
def healthz():
    return {"ok": True}
