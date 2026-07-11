from app.web.routes.actions import router as actions_router
from app.web.routes.fragments import router as fragments_router
from app.web.routes.pages import router as pages_router

from fastapi import APIRouter

router = APIRouter(include_in_schema=False)
router.include_router(pages_router)
router.include_router(fragments_router)
router.include_router(actions_router)

__all__ = ["router"]
