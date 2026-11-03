from __future__ import annotations

from fastapi import APIRouter, Depends

from banking_api.audit import verify_chain
from banking_api.auth import require_admin_token
from banking_api.errors import error_responses

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/verify", dependencies=[Depends(require_admin_token)], responses=error_responses(401))
def audit_verify() -> dict:
    return verify_chain()
