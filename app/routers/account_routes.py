from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth import verify_token
from ..services.account_service import delete_accounts, get_account, import_accounts, list_accounts, update_account


router = APIRouter(dependencies=[Depends(verify_token)])


class ImportReq(BaseModel):
    raw_text: str


class DeleteReq(BaseModel):
    ids: list[int]


class UpdateReq(BaseModel):
    status: int | None = None
    remark: str | None = None


@router.get("/api/accounts")
def accounts(page: int = Query(1), page_size: int = Query(50), search: str | None = None, status: int | None = None):
    return list_accounts(page, page_size, search, status)


@router.post("/api/accounts/import")
def import_route(req: ImportReq):
    result = import_accounts(req.raw_text)
    return {"status": "success", **result.__dict__}


@router.delete("/api/accounts")
def delete_route(req: DeleteReq):
    return {"status": "success", "deleted": delete_accounts(req.ids)}


@router.get("/api/accounts/{account_id}")
def detail(account_id: int):
    account = get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return account


@router.patch("/api/accounts/{account_id}")
def patch(account_id: int, req: UpdateReq):
    if not update_account(account_id, req.status, req.remark):
        raise HTTPException(status_code=404, detail="account not found")
    return {"status": "success"}

