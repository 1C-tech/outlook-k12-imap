from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import verify_token
from ..config import reload_settings, save_config, settings


router = APIRouter(dependencies=[Depends(verify_token)])


@router.get("/api/settings")
def get_settings():
    return settings


@router.put("/api/settings")
def put_settings(req: dict):
    return {"status": "success", "data": save_config(req)}


@router.post("/api/settings/reload")
def reload_route():
    return {"status": "success", "data": reload_settings()}

