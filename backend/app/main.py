from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, documents, health, me
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="RAG Service Backend")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.backend_cors_origin_list,
        allow_methods=["DELETE", "GET", "OPTIONS", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
    return app


app = create_app()
