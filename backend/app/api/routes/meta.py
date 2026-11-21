from fastapi import APIRouter

from app.core.config import settings
from app.demo_data import PASSWORD, USERS
from app.models import AppConfig, DemoAccount

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=AppConfig)
def read_config() -> AppConfig:
    """Public: whether this is the demo, and the demo accounts to sign in with."""
    if not settings.DEMO_MODE:
        return AppConfig(demo=False)
    return AppConfig(
        demo=True,
        demo_password=PASSWORD,
        demo_accounts=[DemoAccount(email=e, full_name=n, role=r) for e, n, r in USERS],
    )
