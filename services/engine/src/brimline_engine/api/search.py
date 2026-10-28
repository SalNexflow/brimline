"""Search routes (M8). The rules live in brimline_engine.search; these only translate.

POST /search reads a question (with the model); POST /search/run runs a filter as it is (chips),
with no model call. Both scope the result to what the signed-in person may see."""

from fastapi import APIRouter, HTTPException

from brimline_engine.ai.clients import client_for
from brimline_engine.ai.config import models_config
from brimline_engine.api.deps import Conn, CurrentSettings, CurrentUser, Now
from brimline_engine.api.planning import Config, Tz
from brimline_engine.demo import check_storage
from brimline_engine.search import service
from brimline_engine.search.filters import Filter
from brimline_engine.search.reading import PURPOSE

router = APIRouter(tags=["search"])


@router.post("/search")
def search(
    body: service.QuestionIn,
    conn: Conn,
    user: CurrentUser,
    now: Now,
    settings: CurrentSettings,
    cfg: Config,
    tz: Tz,
) -> service.SearchOut:
    check_storage(conn, "ai_calls")  # demo mode only (config/demo.toml)
    model = models_config().task(PURPOSE).model
    try:
        return service.search(
            conn,
            user.actor,
            body,
            now,
            tz,
            cfg.shifts.weekdays,
            client=client_for(settings.ai_mode, model),
            mode=settings.ai_mode,
        )
    except service.ForbiddenError:
        raise HTTPException(403, "not allowed") from None


@router.post("/search/run")
def run_filter(body: Filter, conn: Conn, user: CurrentUser, now: Now, tz: Tz) -> service.SearchOut:
    """Run an edited filter (the chips). No model is called."""
    try:
        return service.run_filter(conn, user.actor, body, now, tz)
    except service.ForbiddenError:
        raise HTTPException(403, "not allowed") from None
    except service.InvalidError as e:
        raise HTTPException(422, str(e)) from None
