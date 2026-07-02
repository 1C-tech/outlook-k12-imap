from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..auth import verify_token, verify_token_value
from ..services.log_service import clear_logs, get_log, query_logs, stats


router = APIRouter()


@router.get("/api/logs")
def logs(
    page: int = Query(1),
    page_size: int = Query(50),
    level: str | None = None,
    task_id: int | None = None,
    email: str | None = None,
    start: str | None = None,
    end: str | None = None,
    _token: str = Depends(verify_token),
):
    return query_logs(page, page_size, level, task_id, email, start, end)


@router.get("/api/logs/stats")
def log_stats(task_id: int | None = None, _token: str = Depends(verify_token)):
    return stats(task_id)


@router.delete("/api/logs")
def clear(_token: str = Depends(verify_token)):
    return {"status": "success", "deleted": clear_logs()}


@router.post("/api/logs/clear")
def clear_post(_token: str = Depends(verify_token)):
    return {"status": "success", "deleted": clear_logs()}


@router.get("/api/logs/stream")
async def stream(request: Request, token: str, task_id: int | None = None):
    verify_token_value(token)

    async def generator():
        last_id = 0
        while True:
            if await request.is_disconnected():
                break
            data = query_logs(page=1, page_size=50, task_id=task_id)["data"]
            fresh = [item for item in reversed(data) if item["id"] > last_id]
            for item in fresh:
                last_id = max(last_id, item["id"])
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.get("/api/logs/{log_id}")
def detail(log_id: int, _token: str = Depends(verify_token)):
    item = get_log(log_id)
    if not item:
        raise HTTPException(status_code=404, detail="log not found")
    return item
