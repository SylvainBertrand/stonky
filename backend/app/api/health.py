from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    try:
        result = await session.execute(text("SELECT 1"))
        ok = result.scalar_one() == 1
    except Exception as exc:
        return {"status": "error", "db": "disconnected", "detail": str(exc)}

    return {"status": "ok", "db": "connected" if ok else "error"}
