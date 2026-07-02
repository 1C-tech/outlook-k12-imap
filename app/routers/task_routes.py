from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth import verify_token
from ..services.state_machine import create_tasks, get_task, list_tasks, run_task, update_task_status


router = APIRouter(dependencies=[Depends(verify_token)])


def _run_task_sync(task_id: int) -> None:
    asyncio.run(run_task(task_id))


class CreateTaskReq(BaseModel):
    account_ids: list[int]
    username: str | None = None
    age: int | None = None


class VerifyReq(BaseModel):
    code: str


class ProfileReq(BaseModel):
    username: str
    age: int


@router.get("/api/tasks")
def tasks(page: int = Query(1), page_size: int = Query(50), status: str | None = None, email: str | None = None):
    return list_tasks(page, page_size, status, email)


@router.post("/api/tasks")
def create(req: CreateTaskReq):
    return {"status": "success", "task_ids": create_tasks(req.account_ids, req.username, req.age)}


@router.get("/api/tasks/{task_id}")
def detail(task_id: int):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.post("/api/tasks/{task_id}/start")
def start(task_id: int, background: BackgroundTasks):
    if not get_task(task_id):
        raise HTTPException(status_code=404, detail="task not found")
    background.add_task(_run_task_sync, task_id)
    return {"status": "success"}


@router.post("/api/tasks/{task_id}/retry")
def retry(task_id: int, background: BackgroundTasks):
    update_task_status(task_id, "pending", error_message=None)
    background.add_task(_run_task_sync, task_id)
    return {"status": "success"}


@router.post("/api/tasks/{task_id}/stop")
def stop(task_id: int):
    update_task_status(task_id, "stopped")
    return {"status": "success"}


@router.post("/api/tasks/{task_id}/verify_code")
def verify_code(task_id: int, req: VerifyReq):
    update_task_status(task_id, "code_received", verification_code=req.code)
    return {"status": "success"}


@router.post("/api/tasks/{task_id}/profile")
def profile(task_id: int, req: ProfileReq):
    update_task_status(task_id, "submitting_profile", username=req.username, age=req.age)
    return {"status": "success"}


@router.post("/api/tasks/{task_id}/k12_invite")
def k12_invite(task_id: int):
    update_task_status(task_id, "k12_inviting")
    return {"status": "success"}
