from typing import Awaitable
from fastapi import HTTPException
from httpx import HTTPStatusError


async def handle_errors[T](call: Awaitable[T], info: str | None = None) -> T:
    result = await call
    if isinstance(result, HTTPStatusError):
        raise HTTPException(
            status_code=result.response.status_code,
            detail=result.response.text,
            headers={"X-Error-Info": info} if info else None,
        )
    elif isinstance(result, BaseException):
        raise result
    return result