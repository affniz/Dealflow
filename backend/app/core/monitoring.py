"""Error tracking with Sentry, when SENTRY_DSN is set.

The API and the worker each call init_sentry(). Crashed requests and failed jobs are
reported with their traceback, and so is anything logged at ERROR, which includes errors
reported by people's browsers (app.api.routes.client_errors). Nothing personal is sent:
no cookies, auth headers, IP addresses or request bodies (a sign-in form has a password).
"""

import logging
from typing import Literal

from app.core.config import settings

log = logging.getLogger(__name__)


def init_sentry(component: Literal["api", "worker"]) -> bool:
    if not settings.SENTRY_DSN:
        return False
    import sentry_sdk  # only needed when it's switched on

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        release=settings.RELEASE,
        server_name=component,
        send_default_pii=False,
        max_request_body_size="never",
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        # FastAPI, Starlette, Celery, SQLAlchemy and logging are picked up automatically
    )
    sentry_sdk.set_tag("component", component)
    log.info("Reporting errors to Sentry", extra={"component": component})
    return True
