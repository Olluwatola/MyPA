from fastapi import APIRouter

from .integrations_google import router as integrations_google_router
from .login import router as login_router
from .logout import router as logout_router
from .memory import router as memory_router
from .oauth_google import router as oauth_google_router
from .ready import router as ready_router
from .refresh import router as refresh_router
from .users import router as users_router
from .webhooks_google_calendar import router as webhooks_google_calendar_router

router = APIRouter(prefix="/v1")
router.include_router(ready_router)
router.include_router(login_router)
router.include_router(refresh_router)
router.include_router(logout_router)
router.include_router(oauth_google_router)
router.include_router(users_router)
router.include_router(memory_router)
router.include_router(integrations_google_router)
router.include_router(webhooks_google_calendar_router)
