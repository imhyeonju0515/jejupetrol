"""오피넷 aroundAll.do 로 주변 주유소를 찾는다."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import Settings, get_settings
from stations import mock
from stations.coord import haversine_km, katec_to_wgs84, offset_point, wgs84_to_katec
from stations.http import fetch_json
from stations.schemas import (
    ALTTLE_BRANDS,
    BRAND_NAMES,
    FUEL_TYPES,
    GasStation,
    UpstreamError,
)

logger = logging.getLogger(__name__)

OPINET_MAX_RADIUS_M = 5000  # aroundAll.do 의 반경 상한


def _parse_item(item: Dict[str, Any], fuel_type: str, origin: Tuple[float, float]) -> Optional[GasStation]:
    """aroundAll.do 의 OIL 항목 하나를 GasStation 으로. 가격/좌표가 없으면 None."""
    try:
        price = int(float(item.get("PRICE") or 0))
        lat, lng = katec_to_wgs84(float(item["GIS_X_COOR"]), float(item["GIS_Y_COOR"]))
        sid = str(item["UNI_ID"])
    except (KeyError, TypeError, ValueError):
        return None
    if price <= 0:
        return None
    name = str(item.get("OS_NM", "")).strip()
    brand = str(item.get("POLL_DIV_CD") or item.get("POLL_DIV_CO") or "")
    return GasStation(
        id=sid,
        name=name,
        brand=brand,
        brand_name=BRAND_NAMES.get(brand, brand),
        lat=lat,
        lng=lng,
        price=price,
        fuel_type=fuel_type,
        is_self="셀프" in name,  # 상세 조회(get_prices)에서 정확한 값으로 보정
        is_alttle=brand in ALTTLE_BRANDS,
        distance_m=round(haversine_km(origin, (lat, lng)) * 1000, 1),
    )


async def _query(
    settings: Settings, lat: float, lng: float, radius_m: int, fuel_type: str,
    client: Optional[httpx.AsyncClient],
) -> List[Dict[str, Any]]:
    x, y = wgs84_to_katec(lat, lng)
    data = await fetch_json(
        f"{settings.opinet_base_url}/aroundAll.do",
        params={
            "code": settings.opinet_api_key, "out": "json", "x": round(x, 1), "y": round(y, 1),
            "radius": min(radius_m, OPINET_MAX_RADIUS_M), "prodcd": fuel_type, "sort": 1,
        },
        client=client, timeout=settings.http_timeout_seconds, service="오피넷",
    )
    result = (data or {}).get("RESULT") or {}
    items = result.get("OIL")
    return items if isinstance(items, list) else []


async def find_gas_stations(
    lat: float,
    lng: float,
    radius_m: int = 5000,
    fuel_type: str = "B027",
    *,
    settings: Optional[Settings] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> List[GasStation]:
    """(lat, lng) 반경 radius_m 이내 주유소를 가격 오름차순으로 반환한다.

    오피넷은 KATEC 좌표를 요구하므로 변환해서 호출하고 응답 좌표는 다시 WGS84로 되돌린다.
    오피넷 반경 상한(5km)을 넘는 요청은 중심 + 동서남북 5km 지점 5곳을 조회해 병합한다.

    Raises:
        UpstreamError: API 키 누락, 타임아웃, 응답 오류(한국어 메시지).
    """
    settings = settings or get_settings()
    if fuel_type not in FUEL_TYPES:
        raise UpstreamError("지원하지 않는 유종입니다.")
    if settings.mock:
        return mock.find_stations(lat, lng, radius_m, fuel_type)
    if not settings.opinet_api_key:
        raise UpstreamError("오피넷 API 키가 설정되지 않았습니다. .env 의 OPINET_API_KEY 를 확인해 주세요.")

    centers = [(lat, lng)]
    if radius_m > OPINET_MAX_RADIUS_M:
        centers += [offset_point(lat, lng, n, e) for n, e in
                    ((5000, 0), (-5000, 0), (0, 5000), (0, -5000))]
    batches = await asyncio.gather(
        *[_query(settings, c[0], c[1], OPINET_MAX_RADIUS_M, fuel_type, client) for c in centers]
    )

    merged: Dict[str, GasStation] = {}
    for items in batches:
        for item in items:
            st = _parse_item(item, fuel_type, (lat, lng))
            if st and (st.distance_m or 0) <= radius_m:
                merged[st.id] = st
    stations = sorted(merged.values(), key=lambda s: (s.price or 10**9, s.distance_m or 0))
    if not stations:
        logger.info("주변 주유소 없음: %s,%s r=%s", lat, lng, radius_m)
    return stations
