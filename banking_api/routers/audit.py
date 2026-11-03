from __future__ import annotations

from fastapi import APIRouter, Depends

from banking_api.audit import verify_chain
from banking_api.auth import require_admin_token

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/verify", dependencies=[Depends(require_admin_token)])
def audit_verify() -> dict:
    return verify_chain()
