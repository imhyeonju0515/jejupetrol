"""카카오모빌리티 길찾기로 이동 시간/거리를 구한다 (병렬 호출, 캐시, 직선거리 폴백)."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, List, Optional, Sequence, Tuple

import httpx
from pydantic import BaseModel

from config import Settings, get_settings
from stations.cache import TTLCache
from stations.coord import Point, haversine_km
from stations.http import fetch_json
from stations.schemas import UpstreamError

logger = logging.getLogger(__name__)

ROAD_FACTOR = 1.35  # 직선거리 -> 도로거리 보정
FALLBACK_SPEED_KMH = 40.0  # 제주 평균 주행 속도 가정

_cache: TTLCache[Tuple[float, float, float, float], "TravelResult"] = TTLCache(ttl_seconds=600)


class TravelResult(BaseModel):
    """이동 소요시간(분), 거리(km), 추정치 여부."""

    minutes: float
    km: float
    estimated: bool = False


TravelFn = Callable[[Point, Point], Awaitable[TravelResult]]


def estimate_travel(origin: Point, destination: Point) -> TravelResult:
    """직선거리 기반 추정치 (API 실패/키 없음/MOCK 용)."""
    km = haversine_km(origin, destination) * ROAD_FACTOR
    return TravelResult(minutes=round(km / FALLBACK_SPEED_KMH * 60, 1), km=round(km, 2), estimated=True)


def _key(o: Point, d: Point) -> Tuple[float, float, float, float]:
    return (round(o[0], 4), round(o[1], 4), round(d[0], 4), round(d[1], 4))


async def get_travel_time(
    origin: Point,
    destination: Point,
    *,
    settings: Optional[Settings] = None,
    client: Optional[httpx.AsyncClient] = None,
    cache: Optional[TTLCache] = None,
) -> TravelResult:
    """origin -> destination 자동차 소요시간(분)·거리(km).

    카카오 API 실패(타임아웃/키 없음/경로 없음) 시 직선거리 추정치로 폴백한다(estimated=True).
    성공 결과는 캐시한다.
    """
    settings = settings or get_settings()
    if settings.mock or not settings.kakao_rest_api_key:
        return estimate_travel(origin, destination)

    if cache is None:
        _cache.ttl = settings.travel_cache_ttl_seconds
        cache = _cache
    key = _key(origin, destination)
    hit = cache.get(key)
    if hit is not None:
        return hit
    try:
        data = await fetch_json(
            settings.kakao_directions_url,
            params={
                "origin": f"{origin[1]},{origin[0]}",
                "destination": f"{destination[1]},{destination[0]}",
                "priority": "TIME",
            },
            headers={"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"},
            client=client, timeout=settings.http_timeout_seconds, service="카카오모빌리티",
        )
        route = (data.get("routes") or [None])[0]
        if not route or route.get("result_code") not in (0, None):
            raise UpstreamError("경로를 찾지 못했습니다.")
        summary = route["summary"]
        result = TravelResult(
            minutes=round(float(summary["duration"]) / 60, 1),
            km=round(float(summary["distance"]) / 1000, 2),
        )
    except (UpstreamError, KeyError, TypeError, ValueError) as exc:
        logger.warning("길찾기 실패, 직선거리 추정으로 대체: %s", exc)
        return estimate_travel(origin, destination)
    cache.set(key, result)
    return result


async def get_travel_times(
    origin: Point,
    destinations: Sequence[Point],
    *,
    concurrency: int = 8,
    travel_fn: Optional[TravelFn] = None,
    **kwargs,
) -> List[TravelResult]:
    """한 출발지에서 여러 도착지까지를 asyncio 로 병렬 계산한다 (순서 유지)."""
    fn = travel_fn or (lambda o, d: get_travel_time(o, d, **kwargs))
    sem = asyncio.Semaphore(concurrency)

    async def one(dest: Point) -> TravelResult:
        async with sem:
            return await fn(origin, dest)

    return list(await asyncio.gather(*[one(d) for d in destinations]))
