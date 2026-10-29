"""오피넷 detailById.do 로 주유소 상세/유종별 현재 가격을 조회한다 (TTL 캐시)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import httpx

from config import Settings, get_settings
from stations import mock
from stations.cache import TTLCache
from stations.coord import katec_to_wgs84
from stations.http import fetch_json
from stations.schemas import (
    ALTTLE_BRANDS,
    BRAND_NAMES,
    FUEL_TYPES,
    StationPrice,
    UpstreamError,
)

logger = logging.getLogger(__name__)

# 주유소 ID -> 정규화된 상세(전 유종 가격 포함). 유종과 무관하게 한 번만 받아 재사용한다.
_detail_cache: TTLCache[str, Dict[str, Any]] = TTLCache(ttl_seconds=420)
_CONCURRENCY = 5


def _parse_dt(date_s: Any, time_s: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(f"{date_s}{str(time_s or '000000').zfill(6)}", "%Y%m%d%H%M%S")
    except (TypeError, ValueError):
        return None


def _parse_detail(item: Dict[str, Any]) -> Dict[str, Any]:
    """detailById.do 의 OIL[0] 을 캐시용 dict 로 정규화한다."""
    prices: Dict[str, int] = {}
    updated: Dict[str, Optional[datetime]] = {}
    for p in item.get("OIL_PRICE") or []:
        code = p.get("PRODCD")
        try:
            value = int(float(p.get("PRICE") or 0))
        except (TypeError, ValueError):
            continue
        if code and value > 0:
            prices[code] = value
            updated[code] = _parse_dt(p.get("TRADE_DT"), p.get("TRADE_TM"))
    brand = str(item.get("POLL_DIV_CD") or item.get("POLL_DIV_CO") or "")
    name = str(item.get("OS_NM", "")).strip()
    lat = lng = None
    try:
        lat, lng = katec_to_wgs84(float(item["GIS_X_COOR"]), float(item["GIS_Y_COOR"]))
    except (KeyError, TypeError, ValueError):
        pass
    # 셀프 여부: 응답 필드(SELF_YN 등)가 있으면 사용, 없으면 상호명으로 추정
    self_flag = str(item.get("SELF_YN") or item.get("SELF_DIV_CD") or "").upper()
    return {
        "id": str(item.get("UNI_ID", "")),
        "name": name,
        "brand": brand,
        "address": str(item.get("NEW_ADR") or item.get("VAN_ADR") or ""),
        "lat": lat,
        "lng": lng,
        "prices": prices,
        "updated": updated,
        "is_self": self_flag in ("Y", "S") or "셀프" in name,
    }


def _to_price(detail: Dict[str, Any], station_id: str, fuel_type: str) -> StationPrice:
    brand = detail["brand"]
    return StationPrice(
        station_id=station_id,
        name=detail["name"],
        brand=brand,
        brand_name=BRAND_NAMES.get(brand, brand),
        address=detail["address"],
        lat=detail["lat"],
        lng=detail["lng"],
        fuel_type=fuel_type,
        price=detail["prices"].get(fuel_type),
        updated_at=detail["updated"].get(fuel_type),
        is_self=detail["is_self"],
        is_alttle=brand in ALTTLE_BRANDS,
        all_prices=dict(detail["prices"]),
    )


async def _fetch_detail(
    settings: Settings, station_id: str, client: Optional[httpx.AsyncClient]
) -> Dict[str, Any]:
    data = await fetch_json(
        f"{settings.opinet_base_url}/detailById.do",
        params={"code": settings.opinet_api_key, "id": station_id, "out": "json"},
        client=client, timeout=settings.http_timeout_seconds, service="오피넷",
    )
    oil = ((data or {}).get("RESULT") or {}).get("OIL")
    if not isinstance(oil, list) or not oil:
        raise UpstreamError(f"주유소({station_id}) 상세 정보가 비어 있습니다.")
    return _parse_detail(oil[0])


async def get_prices(
    station_ids: Iterable[str],
    fuel_type: str = "B027",
    *,
    settings: Optional[Settings] = None,
    client: Optional[httpx.AsyncClient] = None,
    cache: Optional[TTLCache[str, Dict[str, Any]]] = None,
) -> Dict[str, StationPrice]:
    """주유소 ID 목록의 유종별 현재 가격/브랜드/셀프 여부/갱신 시각을 반환한다.

    결과는 {station_id: StationPrice}. 일부 주유소 조회가 실패하면 그 주유소만 빠진다.
    캐시(기본 7분)가 있어 같은 주유소를 반복 조회해도 오피넷을 다시 부르지 않는다.

    Raises:
        UpstreamError: 모든 조회가 실패했을 때.
    """
    settings = settings or get_settings()
    if fuel_type not in FUEL_TYPES:
        raise UpstreamError("지원하지 않는 유종입니다.")
    ids: List[str] = list(dict.fromkeys(str(i) for i in station_ids))
    if not ids:
        return {}
    if settings.mock:
        return mock.get_station_prices(ids, fuel_type)
    if not settings.opinet_api_key:
        raise UpstreamError("오피넷 API 키가 설정되지 않았습니다. .env 의 OPINET_API_KEY 를 확인해 주세요.")

    if cache is None:
        _detail_cache.ttl = settings.price_cache_ttl_seconds
        cache = _detail_cache
    sem = asyncio.Semaphore(_CONCURRENCY)
    errors: List[UpstreamError] = []

    async def one(sid: str) -> Optional[StationPrice]:
        detail = cache.get(sid)
        if detail is None:
            async with sem:
                try:
                    detail = await _fetch_detail(settings, sid, client)
                except UpstreamError as exc:
                    logger.warning("상세 조회 실패 %s: %s", sid, exc.message)
                    errors.append(exc)
                    return None
            cache.set(sid, detail)
        return _to_price(detail, sid, fuel_type)

    results = await asyncio.gather(*[one(i) for i in ids])
    out = {sid: r for sid, r in zip(ids, results) if r is not None}
    if not out and errors:
        raise errors[0]
    return out
