from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import login_with_password, revoke_token, verify_token


router = APIRouter()


class LoginReq(BaseModel):
    password: str


@router.post("/api/auth/login")
def login(req: LoginReq):
    return {"status": "success", "token": login_with_password(req.password)}


@router.post("/api/auth/logout")
def logout(token: str = Depends(verify_token)):
    revoke_token(token)
    return {"status": "success"}

