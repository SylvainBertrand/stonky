import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.backtests import router as backtests_router
from app.api.forecasts import router as forecasts_router
from app.api.health import router as health_router
from app.api.market import router as market_router
from app.api.patterns import router as patterns_router
from app.api.pipeline import router as pipeline_router
from app.api.scanner import router as scanner_router
from app.api.stocks import router as stocks_router
from app.api.synthesis import router as synthesis_router
from app.api.watchlist import router as watchlist_router
from app.config import settings
from app.paper_trader.router import router as paper_trader_router


def _configure_logging() -> None:
    """Route app.* logs through uvicorn handlers so INFO diagnostics are visible."""
    level = logging.DEBUG if settings.debug else logging.INFO

    uvicorn_error = logging.getLogger("uvicorn.error")
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)

    if uvicorn_error.handlers:
        app_logger.handlers = uvicorn_error.handlers
        app_logger.propagate = False
    elif not app_logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(levelname)s: %(name)s: %(message)s")
        handler.setFormatter(formatter)
        app_logger.addHandler(handler)
        app_logger.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    _configure_logging()
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

    app.include_router(backtests_router, prefix="/api")
    app.include_router(health_router, prefix="/api")
    app.include_router(market_router, prefix="/api")
    app.include_router(watchlist_router, prefix="/api")
    app.include_router(scanner_router, prefix="/api")
    app.include_router(patterns_router, prefix="/api")
    app.include_router(stocks_router, prefix="/api")
    app.include_router(forecasts_router, prefix="/api")
    app.include_router(synthesis_router, prefix="/api")
    app.include_router(pipeline_router, prefix="/api")
    app.include_router(paper_trader_router, prefix="/api")

    return app


app = create_app()
