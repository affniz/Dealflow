"""Celery worker and scheduler.

Run both in one process during development:
    celery -A app.worker worker --beat --loglevel=info
"""

from celery import Celery
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.services.rotting import check_rotting

celery_app = Celery("dealflow", broker=settings.REDIS_URL)
celery_app.conf.update(
    timezone="UTC",
    task_ignore_result=True,
    beat_schedule={
        "check-rotting-deals": {
            "task": "dealflow.check_rotting",
            "schedule": settings.ROTTING_CHECK_INTERVAL_SECONDS,
        }
    },
)


@celery_app.task(name="dealflow.check_rotting")
def check_rotting_task() -> dict[str, int]:
    with Session(engine) as session:
        result = check_rotting(session)
    return {"flagged": result.flagged, "cleared": result.cleared}
