"""제주 렌터카 주유 최저가 도우미 - FastAPI 앱."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from alerts import service
from alerts.models import AlertRule, AlertRuleCreate, AlertRuleUpdate, PushSubscribeRequest
from alerts.notifier import build_notifier
from alerts.scheduler import shutdown_scheduler, start_scheduler
from config import get_settings
from database import get_engine, get_session, init_db
from stations import mock
from stations.finder import find_gas_stations
from stations.prices import get_prices
from stations.recommender import DEFAULT_LITERS, DEFAULT_TIME_VALUE, recommend
from stations.schemas import FUEL_TYPES, UpstreamError
from stations.travel import get_travel_time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("jeju-gas")

MAX_RECOMMEND_CANDIDATES = 20  # 길찾기 API 호출 수를 제한하기 위해 가격 상위 + 가까운 곳만 계산


@asynccontextmanager
async def lifespan(app: FastAPI):
    """시작: DB 초기화 + 스케줄러. 종료: 스케줄러 정리."""
    settings = get_settings()
    init_db()
    if settings.mock:
        logger.info("MOCK 모드: 외부 API 대신 샘플 데이터를 사용합니다.")
    if settings.scheduler_enabled:
        start_scheduler(settings)
    try:
        yield
    finally:
        shutdown_scheduler()


app = FastAPI(title="제주 렌터카 주유 최저가 도우미", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=get_settings().cors_origin_list,
    allow_methods=["*"], allow_headers=["*"],
)


# ---------------------------------------------------------------- 오류 처리 (한국어)
@app.exception_handler(UpstreamError)
async def upstream_error_handler(_: Request, exc: UpstreamError):
    return JSONResponse(status_code=502, content={"detail": exc.message})


@app.exception_handler(service.AlertNotFound)
async def not_found_handler(_: Request, exc: service.AlertNotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    msgs = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e.get("loc", []) if x not in ("body", "query"))
        msg = str(e.get("msg", "")).replace("Value error, ", "")
        msgs.append(f"{loc}: {msg}" if loc else msg)
    return JSONResponse(status_code=422, content={"detail": "입력값이 올바르지 않습니다. " + " / ".join(msgs)})


def device_token_dep(x_device_token: Optional[str] = Header(default=None)) -> str:
    """익명 device_token (X-Device-Token 헤더). 회원가입 없이 기기 단위로 식별한다."""
    if not x_device_token or not (16 <= len(x_device_token) <= 128):
        raise HTTPException(status_code=401, detail="기기 식별값(X-Device-Token)이 필요합니다.")
    return x_device_token


# ---------------------------------------------------------------- 메타
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/meta")
async def meta():
    """프론트엔드가 필요로 하는 공개 설정."""
    s = get_settings()
    return {"mock": s.mock, "vapid_public_key": s.vapid_public_key, "fuel_types": FUEL_TYPES}


# ---------------------------------------------------------------- 주유소
def _pick_candidates(stations, limit: int = MAX_RECOMMEND_CANDIDATES):
    """가격 낮은 순 + 가까운 순을 섞어 limit 개로 줄인다."""
    by_price = sorted(stations, key=lambda s: s.price or 10**9)
    near = sorted(stations, key=lambda s: s.distance_m or 10**9)
    picked, seen = [], set()
    for s in by_price[: limit - 5] + near[:5] + by_price:
        if s.id not in seen and len(picked) < limit:
            seen.add(s.id)
            picked.append(s)
    return picked


@app.get("/stations")
async def stations_endpoint(
    lat: float = Query(ge=32.5, le=34.2),
    lng: float = Query(ge=125.8, le=127.2),
    radius: int = Query(3000, ge=500, le=10000, description="반경(m)"),
    fuel_type: str = Query("B027"),
    dest_lat: Optional[float] = None,
    dest_lng: Optional[float] = None,
    liters: float = Query(DEFAULT_LITERS, gt=0, le=200),
    time_value: int = Query(DEFAULT_TIME_VALUE, ge=0),
    near_return: bool = False,
    max_detour: Optional[float] = Query(None, gt=0),
    self_only: bool = False,
    session: Session = Depends(get_session),
):
    """주변 주유소 + 실질 총비용 추천 순위."""
    settings = get_settings()
    if fuel_type not in FUEL_TYPES:
        raise HTTPException(status_code=422, detail="지원하지 않는 유종입니다.")
    if (dest_lat is None) != (dest_lng is None):
        raise HTTPException(status_code=422, detail="반납 장소는 위도와 경도를 함께 보내 주세요.")

    notices: List[str] = []
    found = await find_gas_stations(lat, lng, radius, fuel_type, settings=settings)
    if self_only:
        found = [s for s in found if s.is_self]

    # 상세 API 로 주소/셀프/갱신시각 보강 (캐시됨). 실패해도 목록은 보여준다.
    pool = _pick_candidates(found)
    try:
        detail = await get_prices([s.id for s in pool], fuel_type, settings=settings)
        for s in found:
            d = detail.get(s.id)
            if d:
                s.address, s.is_self, s.is_alttle = d.address or s.address, d.is_self, d.is_alttle
                s.brand_name, s.updated_at = d.brand_name or s.brand_name, d.updated_at or s.updated_at
                if d.price:
                    s.price = d.price
    except UpstreamError as exc:
        notices.append(f"{exc.message} 상세 정보 없이 목록만 표시합니다.")
    if self_only:
        found = [s for s in found if s.is_self]

    service.record_price_history(session, found)
    dest = (dest_lat, dest_lng) if dest_lat is not None else None
    result = await recommend(
        _pick_candidates(found), (lat, lng), destination=dest, liters=liters,
        time_value_per_hour=time_value, top_n=5,
        near_return_radius_km=3.0 if (near_return and dest) else None,
        max_detour_minutes=max_detour if dest else None,
        travel_fn=lambda o, d: get_travel_time(o, d, settings=settings),
    )
    price_rank = {s.id: i + 1 for i, s in enumerate(sorted(found, key=lambda s: s.price or 10**9))}
    return {
        "fuel_type": fuel_type,
        "center": {"lat": lat, "lng": lng},
        "destination": {"lat": dest_lat, "lng": dest_lng} if dest else None,
        "total_found": len(found),
        "recommendations": result.items,
        "cheapest": result.cheapest,
        "rank_differs": result.rank_differs,
        "explanation": result.explanation,
        "notices": notices + result.notices + ([] if found else ["반경 내 주유소가 없습니다. 반경을 넓혀 보세요."]),
        "stations": [{**s.model_dump(mode="json"), "price_rank": price_rank[s.id]} for s in found],
    }


@app.get("/stations/{station_id}/price-history")
async def price_history(
    station_id: str,
    days: int = Query(7, ge=1, le=30),
    fuel_type: str = Query("B027"),
    session: Session = Depends(get_session),
):
    """최근 days 일 가격 추이."""
    if fuel_type not in FUEL_TYPES:
        raise HTTPException(status_code=422, detail="지원하지 않는 유종입니다.")
    rows = service.get_price_history(session, station_id, fuel_type, days)
    points = [{"t": r.recorded_at.isoformat(), "price": r.price} for r in rows]
    if len(points) < 2 and get_settings().mock:  # MOCK: 차트가 비지 않도록 샘플 이력 제공
        points = [{"t": t.isoformat(), "price": p} for t, p in mock.price_history(station_id, fuel_type, days)]
    return {"station_id": station_id, "fuel_type": fuel_type, "days": days, "points": points}


# ---------------------------------------------------------------- 알림
@app.post("/alerts", response_model=AlertRule, status_code=201)
async def create_alert(body: AlertRuleCreate, token: str = Depends(device_token_dep),
                       session: Session = Depends(get_session)):
    return service.create_alert(session, token, body)


@app.get("/alerts", response_model=List[AlertRule])
async def list_alerts(token: str = Depends(device_token_dep), session: Session = Depends(get_session)):
    return service.list_alerts(session, token)


@app.patch("/alerts/{alert_id}", response_model=AlertRule)
async def update_alert(alert_id: int, body: AlertRuleUpdate, token: str = Depends(device_token_dep),
                       session: Session = Depends(get_session)):
    return service.update_alert(session, token, alert_id, body)


@app.delete("/alerts/{alert_id}", status_code=204)
async def delete_alert(alert_id: int, token: str = Depends(device_token_dep),
                       session: Session = Depends(get_session)):
    service.delete_alert(session, token, alert_id)


@app.get("/alerts/{alert_id}/events")
async def alert_events(alert_id: int, token: str = Depends(device_token_dep),
                       session: Session = Depends(get_session)):
    return service.list_events(session, token, alert_id)


@app.post("/alerts/{alert_id}/test")
async def alert_test(alert_id: int, token: str = Depends(device_token_dep),
                     session: Session = Depends(get_session)):
    """테스트 알림 즉시 발송."""
    rule = service.get_alert(session, token, alert_id)
    result, event = await service.send_test(session, rule, notifier=build_notifier(get_settings()))
    if not result.ok:
        if result.permanent:
            raise HTTPException(status_code=409, detail=f"알림을 보낼 수 없습니다: {result.error} 알림을 다시 등록해 주세요.")
        raise HTTPException(status_code=502, detail="네트워크 오류로 테스트 알림을 보내지 못했습니다. 잠시 후 다시 시도해 주세요.")
    return {"ok": True, "attempts": result.attempts, "message": event.message}


# ---------------------------------------------------------------- 웹 푸시
@app.post("/push/subscribe", status_code=201)
async def push_subscribe(body: PushSubscribeRequest, token: str = Depends(device_token_dep),
                         session: Session = Depends(get_session)):
    p256dh, auth = body.keys.get("p256dh"), body.keys.get("auth")
    if not (p256dh and auth):
        raise HTTPException(status_code=422, detail="푸시 구독 정보가 올바르지 않습니다.")
    service.save_subscription(session, token, body.endpoint, p256dh, auth)
    return {"ok": True}


@app.delete("/push/subscribe", status_code=204)
async def push_unsubscribe(token: str = Depends(device_token_dep), session: Session = Depends(get_session)):
    service.delete_subscription(session, token)


# ---------------------------------------------------------------- 프론트엔드 정적 서빙 (Docker 등)
_dist = get_settings().frontend_dist
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
