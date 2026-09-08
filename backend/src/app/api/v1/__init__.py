from fastapi import APIRouter

from .login import router as login_router
from .logout import router as logout_router
from .oauth_google import router as oauth_google_router
from .ready import router as ready_router
from .refresh import router as refresh_router
from .users import router as users_router

router = APIRouter(prefix="/v1")
router.include_router(ready_router)
router.include_router(login_router)
router.include_router(refresh_router)
router.include_router(logout_router)
router.include_router(oauth_google_router)
router.include_router(users_router)
