from typing import Awaitable
from fastapi import HTTPException
from httpx import HTTPStatusError


async def handle_errors[T](call: Awaitable[T], info: str | None = None) -> T:
    try:
        return await call
    except HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=e.response.text,
            headers={"X-Error-Info": info} if info else None,
        )
    except Exception as e:
        raise e