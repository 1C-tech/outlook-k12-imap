from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..auth import verify_token
from ..services.log_service import get_log, query_logs, stats


router = APIRouter(dependencies=[Depends(verify_token)])


@router.get("/api/logs")
def logs(
    page: int = Query(1),
    page_size: int = Query(50),
    level: str | None = None,
    task_id: int | None = None,
    email: str | None = None,
    start: str | None = None,
    end: str | None = None,
):
    return query_logs(page, page_size, level, task_id, email, start, end)


@router.get("/api/logs/stats")
def log_stats(task_id: int | None = None):
    return stats(task_id)


@router.get("/api/logs/stream")
async def stream(task_id: int | None = None):
    async def generator():
        last_id = 0
        while True:
            data = query_logs(page=1, page_size=50, task_id=task_id)["data"]
            fresh = [item for item in reversed(data) if item["id"] > last_id]
            for item in fresh:
                last_id = max(last_id, item["id"])
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.get("/api/logs/{log_id}")
def detail(log_id: int):
    item = get_log(log_id)
    if not item:
        raise HTTPException(status_code=404, detail="log not found")
    return item

