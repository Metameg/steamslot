from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.packs import router as packs_router
from app.api.v1.wallet import router as wallet_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(wallet_router)
router.include_router(packs_router)

__all__ = ["router"]
