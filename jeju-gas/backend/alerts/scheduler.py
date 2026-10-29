"""APScheduler 로 check_alerts() 를 주기 실행한다."""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import Session

from alerts import service
from config import Settings, get_settings
from database import get_engine

logger = logging.getLogger(__name__)

JOB_ID = "check_alerts"
_scheduler: Optional[AsyncIOScheduler] = None


async def run_cycle(settings: Optional[Settings] = None) -> None:
    """한 사이클: 만료 정리 -> 알림 검사 -> 반납 요약 -> 오래된 이력 정리.

    예외는 로그만 남기고 삼킨다(다음 주기에 재시도).
    """
    settings = settings or get_settings()
    try:
        with Session(get_engine()) as session:
            report = await service.check_alerts(session, settings=settings)
            summaries = await service.send_return_summaries(session, settings=settings)
            service.prune_price_history(session)
        logger.info("알림 검사 완료: %s, 반납요약 %d건", report, summaries)
    except Exception:
        logger.exception("알림 검사 사이클 실패 — 다음 주기에 재시도합니다.")


def start_scheduler(settings: Optional[Settings] = None) -> AsyncIOScheduler:
    """스케줄러를 시작한다 (이벤트 루프 안에서 호출). 주기는 ALERT_CHECK_INTERVAL_MINUTES."""
    global _scheduler
    settings = settings or get_settings()
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        run_cycle, "interval", minutes=max(1, settings.alert_check_interval_minutes),
        id=JOB_ID, kwargs={"settings": settings}, max_instances=1, coalesce=True, replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("스케줄러 시작: %d분 주기", settings.alert_check_interval_minutes)
    return scheduler


def shutdown_scheduler() -> None:
    """스케줄러를 정상 종료한다."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("스케줄러 종료")
