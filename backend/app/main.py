from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.health import router as health_router
from app.api.scanner import router as scanner_router
from app.api.watchlist import router as watchlist_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    from app.scheduler import create_scheduler
    scheduler = create_scheduler()
    scheduler.start()

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    from app.db.session import engine
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Stonky API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, prefix="/api")
    app.include_router(watchlist_router, prefix="/api")
    app.include_router(scanner_router, prefix="/api")

    return app


app = create_app()
