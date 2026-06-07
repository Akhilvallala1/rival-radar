import json
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from rival_radar.database import SessionLocal, init_db
from rival_radar.models import Competitor
from rival_radar.state import MonitorState

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def run_competitor(comp: Competitor) -> None:
    from rival_radar.graph import app  # imported here to avoid circular import at module load
    from rival_radar.tracing import build_run_config

    urls: list[str] = json.loads(comp.urls)
    state = MonitorState(
        competitors=[{"competitor_id": comp.id, "name": comp.name, "urls": urls}],
        diffs={},
        analyses=[],
        brief="",
        run_id=0,
    )
    run_config = build_run_config(run_name=f"rival-radar:{comp.name}")
    logger.info("Running pipeline for competitor: %s", comp.name)
    app.invoke(state, config=run_config)
    logger.info("Pipeline complete for competitor: %s", comp.name)


def run_all_competitors() -> None:
    init_db()
    with SessionLocal() as db:
        competitors = db.query(Competitor).all()

    for comp in competitors:
        try:
            run_competitor(comp)
        except Exception:
            logger.exception("Pipeline failed for competitor: %s", comp.name)


@scheduler.scheduled_job("cron", day_of_week="mon", hour=9, minute=0, id="weekly_run")
def weekly_job() -> None:
    logger.info("Weekly scheduled run starting.")
    run_all_competitors()


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started — weekly run every Monday at 09:00.")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
