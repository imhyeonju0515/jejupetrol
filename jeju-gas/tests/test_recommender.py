"""총비용 계산 / 최저가 순위 vs 실질 순위."""
import asyncio

import pytest

from conftest import AIRPORT, fake_travel, make_station
from stations.recommender import (
    build_recommendations,
    compute_total_cost,
    explain_difference,
    measure_trips,
    recommend,
    Trip,
)
from stations.travel import TravelResult


def test_total_cost_formula():
    c = compute_total_cost(1600, 30, extra_minutes=12, extra_km=6, time_value_per_hour=10_000, fuel_efficiency=10)
    assert c.fuel_cost == 48_000  # 1600 x 30L
    assert c.time_cost == 2_000  # 12분 / 60 x 10,000
    assert c.travel_fuel_cost == 960  # 6km / 10 x 1600
    assert c.total_cost == 50_960


def test_time_value_zero_removes_time_cost():
    c = compute_total_cost(1600, 30, 20, 0, time_value_per_hour=0)
    assert c.time_cost == 0 and c.total_cost == 48_000


def _trips(**minutes):
    return {sid: Trip(extra_minutes=m, extra_km=m * 0.6, leg_minutes=m / 2) for sid, m in minutes.items()}


def test_cheapest_price_is_not_best_total_cost():
    """리터당 20원 싼 주유소가 30분 더 멀면 실질 비용은 더 비싸다."""
    far_cheap = make_station("A", 1580)
    near = make_station("B", 1600)
    recs = build_recommendations([far_cheap, near], _trips(A=40, B=6), liters=30, time_value_per_hour=10_000)
    assert [r.station.id for r in recs] == ["B", "A"]  # 실질 순위
    by_id = {r.station.id: r for r in recs}
    assert by_id["A"].price_rank == 1 and by_id["B"].price_rank == 2  # 단순 가격 순위
    assert recs[0].rank == 1


def test_same_ranking_when_cheapest_is_also_nearest():
    recs = build_recommendations([make_station("A", 1580), make_station("B", 1600)], _trips(A=5, B=5))
    assert recs[0].station.id == "A"


def test_explanation_when_ranks_differ():
    recs = build_recommendations([make_station("A", 1580), make_station("B", 1600)], _trips(A=40, B=6))
    text = explain_difference(recs[0], recs[1])
    assert "주유소A" in text and "1,580" in text and "더 저렴" in text


def test_recommend_returns_top5_and_flags_difference():
    stations = [make_station("S0", 1580, lat=33.60, lng=126.60)]  # 멀지만 최저가
    stations += [make_station(f"N{i}", 1600 + i) for i in range(6)]  # 공항 인근

    result = asyncio.run(recommend(stations, AIRPORT, travel_fn=fake_travel))
    assert len(result.items) == 5
    assert result.cheapest.station.id == "S0"
    assert result.rank_differs is True
    assert result.items[0].station.id == "N0"
    assert [r.rank for r in result.items] == [1, 2, 3, 4, 5]
    assert "S0" in result.explanation


def test_destination_counts_only_detour():
    """반납 장소가 가는 길목에 있는 주유소는 우회 시간이 ~0 이다."""
    origin, dest = (33.2541, 126.5601), AIRPORT
    on_route = make_station("ON", 1650, lat=33.38, lng=126.53)
    off_route = make_station("OFF", 1650, lat=33.30, lng=126.90)
    trips = asyncio.run(measure_trips(origin, [on_route, off_route], dest, fake_travel))
    assert trips["ON"].extra_minutes < 3
    assert trips["OFF"].extra_minutes > 10


def test_round_trip_when_no_destination():
    trips = asyncio.run(measure_trips(AIRPORT, [make_station("X", 1600, lat=33.55, lng=126.55)], None, fake_travel))
    assert trips["X"].extra_minutes == pytest.approx(trips["X"].leg_minutes * 2)


def test_max_detour_filter_and_near_return():
    origin, dest = (33.2541, 126.5601), AIRPORT
    stations = [make_station("ON", 1650, lat=33.38, lng=126.53),
                make_station("OFF", 1500, lat=33.30, lng=126.90)]
    res = asyncio.run(recommend(stations, origin, destination=dest, max_detour_minutes=10, travel_fn=fake_travel))
    assert [r.station.id for r in res.items] == ["ON"]

    res = asyncio.run(recommend(stations, origin, destination=dest, near_return_radius_km=3, travel_fn=fake_travel))
    assert res.notices and len(res.items) >= 1  # 3km 내 없음 -> 전체로 대체 + 안내


def test_empty_when_no_priced_station():
    res = asyncio.run(recommend([], AIRPORT, travel_fn=fake_travel))
    assert res.items == [] and res.notices
