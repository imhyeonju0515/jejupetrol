"""'기름값 + 이동 시간'을 함께 고려한 실질 최저가 추천."""
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel

from stations.coord import Point, haversine_km
from stations.schemas import GasStation
from stations.travel import TravelFn, get_travel_time

DEFAULT_LITERS = 30.0
DEFAULT_TIME_VALUE = 10_000  # 원/시간
DEFAULT_EFFICIENCY = 10.0  # km/L (렌터카 평균 가정)


class Trip(BaseModel):
    """한 주유소를 들를 때의 추가 이동."""

    extra_minutes: float  # 우회(또는 왕복) 추가 시간
    extra_km: float  # 우회(또는 왕복) 추가 거리
    leg_minutes: float  # 출발지 -> 주유소 편도 시간
    estimated: bool = False


class CostBreakdown(BaseModel):
    fuel_cost: int  # 주유 금액
    time_cost: int  # 시간 가치 환산
    travel_fuel_cost: int  # 이동(왕복/우회) 연료비
    total_cost: int


class Recommendation(BaseModel):
    rank: int  # 실질 총비용 순위
    price_rank: int  # 단순 리터당 가격 순위
    station: GasStation
    price: int
    extra_minutes: float
    extra_km: float
    leg_minutes: float
    estimated: bool
    fuel_cost: int
    time_cost: int
    travel_fuel_cost: int
    total_cost: int


class RecommendationResult(BaseModel):
    items: List[Recommendation]  # 상위 N개 (총비용 오름차순)
    cheapest: Optional[Recommendation] = None  # 단순 최저가 주유소
    rank_differs: bool = False
    explanation: str = ""
    notices: List[str] = []


def compute_total_cost(
    price_per_liter: float,
    liters: float,
    extra_minutes: float,
    extra_km: float,
    time_value_per_hour: float = DEFAULT_TIME_VALUE,
    fuel_efficiency: float = DEFAULT_EFFICIENCY,
) -> CostBreakdown:
    """실질 총비용 = 리터당 가격×주유량 + 우회시간/60×시간가치 + 왕복(우회) 연료비.

    왕복 연료비는 추가 주행거리 / 연비 × 리터당 가격.
    """
    fuel_cost = round(price_per_liter * liters)
    time_cost = round(extra_minutes / 60 * time_value_per_hour)
    travel_fuel = round(extra_km / max(fuel_efficiency, 0.1) * price_per_liter)
    return CostBreakdown(
        fuel_cost=fuel_cost, time_cost=time_cost, travel_fuel_cost=travel_fuel,
        total_cost=fuel_cost + time_cost + travel_fuel,
    )


async def measure_trips(
    origin: Point,
    stations: Sequence[GasStation],
    destination: Optional[Point] = None,
    travel_fn: Optional[TravelFn] = None,
    concurrency: int = 8,
) -> Dict[str, Trip]:
    """주유소별 추가 이동(시간/거리)을 병렬로 계산한다.

    - 반납 장소 없음: 현재 위치 <-> 주유소 왕복
    - 반납 장소 있음: (현재->주유소->반납) - (현재->반납) 의 우회분만
    """
    fn = travel_fn or get_travel_time
    sem = asyncio.Semaphore(concurrency)

    async def call(a: Point, b: Point):
        async with sem:
            return await fn(a, b)

    base_task = call(origin, destination) if destination else None
    legs_a = [call(origin, (s.lat, s.lng)) for s in stations]
    legs_b = [call((s.lat, s.lng), destination) for s in stations] if destination else []
    base, a_res, b_res = await asyncio.gather(
        base_task if base_task else asyncio.sleep(0, result=None),
        asyncio.gather(*legs_a),
        asyncio.gather(*legs_b),
    )

    trips: Dict[str, Trip] = {}
    for i, s in enumerate(stations):
        a = a_res[i]
        if destination:
            b = b_res[i]
            extra_min = max(0.0, a.minutes + b.minutes - base.minutes)
            extra_km = max(0.0, a.km + b.km - base.km)
            est = a.estimated or b.estimated or base.estimated
        else:
            extra_min, extra_km, est = a.minutes * 2, a.km * 2, a.estimated
        trips[s.id] = Trip(
            extra_minutes=round(extra_min, 1), extra_km=round(extra_km, 2),
            leg_minutes=a.minutes, estimated=est,
        )
    return trips


def build_recommendations(
    stations: Sequence[GasStation],
    trips: Dict[str, Trip],
    liters: float = DEFAULT_LITERS,
    time_value_per_hour: float = DEFAULT_TIME_VALUE,
    fuel_efficiency: float = DEFAULT_EFFICIENCY,
) -> List[Recommendation]:
    """(순수 함수) 총비용 오름차순으로 정렬된 Recommendation 목록. 가격이 없는 주유소는 제외."""
    priced = [s for s in stations if s.price and s.id in trips]
    by_price = sorted(priced, key=lambda s: (s.price, trips[s.id].extra_minutes))
    price_rank = {s.id: i + 1 for i, s in enumerate(by_price)}

    recs: List[Recommendation] = []
    for s in priced:
        t = trips[s.id]
        c = compute_total_cost(s.price, liters, t.extra_minutes, t.extra_km, time_value_per_hour, fuel_efficiency)
        recs.append(Recommendation(
            rank=0, price_rank=price_rank[s.id], station=s, price=s.price,
            extra_minutes=t.extra_minutes, extra_km=t.extra_km, leg_minutes=t.leg_minutes,
            estimated=t.estimated, fuel_cost=c.fuel_cost, time_cost=c.time_cost,
            travel_fuel_cost=c.travel_fuel_cost, total_cost=c.total_cost,
        ))
    recs.sort(key=lambda r: (r.total_cost, r.price))
    for i, r in enumerate(recs):
        r.rank = i + 1
    return recs


def explain_difference(best: Recommendation, cheapest: Recommendation) -> str:
    """단순 최저가와 실질 최저가가 다를 때 이유를 설명하는 문구."""
    if best.station.id == cheapest.station.id:
        return "리터당 최저가 주유소가 이동 시간까지 고려해도 가장 이득입니다."
    saved = cheapest.total_cost - best.total_cost
    price_gap = best.price - cheapest.price
    extra = round(cheapest.extra_minutes - best.extra_minutes)
    return (
        f"리터당 최저가는 {cheapest.station.name}({cheapest.price:,}원)이지만, "
        f"이동 시간이 약 {max(extra, 0)}분 더 걸려 실질 총비용은 "
        f"{best.station.name}({best.price:,}원, 리터당 +{price_gap:,}원)이 "
        f"약 {saved:,}원 더 저렴합니다."
    )


async def recommend(
    stations: Sequence[GasStation],
    origin: Point,
    *,
    destination: Optional[Point] = None,
    liters: float = DEFAULT_LITERS,
    time_value_per_hour: float = DEFAULT_TIME_VALUE,
    fuel_efficiency: float = DEFAULT_EFFICIENCY,
    top_n: int = 5,
    near_return_radius_km: Optional[float] = None,
    max_detour_minutes: Optional[float] = None,
    travel_fn: Optional[TravelFn] = None,
) -> RecommendationResult:
    """실질 총비용 기준 상위 top_n 주유소를 추천한다.

    Args:
        stations: find_gas_stations 결과 (가격 포함).
        origin: 현재 위치 (lat, lng).
        destination: 반납 장소. 있으면 '현재 -> 주유소 -> 반납' 우회분만 계산.
        near_return_radius_km: 반납 장소 반경 내 주유소만(없으면 전체로 대체하고 안내).
        max_detour_minutes: 이 시간보다 우회가 큰 주유소는 제외.
    """
    notices: List[str] = []
    candidates = [s for s in stations if s.price]

    if destination and near_return_radius_km:
        near = [s for s in candidates
                if haversine_km(destination, (s.lat, s.lng)) <= near_return_radius_km]
        if near:
            candidates = near
        elif candidates:
            notices.append(f"반납 장소 {near_return_radius_km:g}km 이내 주유소가 없어 전체 주유소에서 추천합니다.")

    if not candidates:
        return RecommendationResult(items=[], notices=notices + ["조건에 맞는 주유소가 없습니다."])

    trips = await measure_trips(origin, candidates, destination, travel_fn)
    if any(t.estimated for t in trips.values()):
        notices.append("일부 이동 시간은 직선거리 기반 추정치입니다.")

    if max_detour_minutes is not None:
        kept = [s for s in candidates if trips[s.id].extra_minutes <= max_detour_minutes]
        if not kept:
            return RecommendationResult(
                items=[], notices=notices + [f"우회 시간 {max_detour_minutes:g}분 이내 주유소가 없습니다."])
        candidates = kept

    ranked = build_recommendations(candidates, trips, liters, time_value_per_hour, fuel_efficiency)
    cheapest = min(ranked, key=lambda r: (r.price, r.extra_minutes))
    best = ranked[0]
    differs = best.station.id != cheapest.station.id
    return RecommendationResult(
        items=ranked[:top_n], cheapest=cheapest, rank_differs=differs,
        explanation=explain_difference(best, cheapest), notices=notices,
    )
