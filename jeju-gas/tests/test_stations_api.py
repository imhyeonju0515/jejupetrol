"""MOCK 모드 find/prices/travel + 캐시 동작."""
import asyncio

from config import Settings
from stations.cache import TTLCache
from stations.finder import find_gas_stations
from stations.prices import get_prices
from stations.travel import get_travel_time

MOCK = Settings(mock=True, _env_file=None)
AIRPORT = (33.5113, 126.493)


def test_mock_find_sorted_by_price_and_in_radius():
    found = asyncio.run(find_gas_stations(*AIRPORT, 5000, "B027", settings=MOCK))
    assert found and all(s.distance_m <= 5000 for s in found)
    assert [s.price for s in found] == sorted(s.price for s in found)


def test_mock_prices_cover_all_fuels():
    res = asyncio.run(get_prices(["MOCK0001", "MOCK0002", "NOPE"], "D047", settings=MOCK))
    assert set(res) == {"MOCK0001", "MOCK0002"}
    assert set(res["MOCK0001"].all_prices) == {"B027", "D047", "B034", "K015"}
    assert res["MOCK0001"].is_self and res["MOCK0001"].is_alttle


def test_travel_falls_back_to_estimate_without_key():
    r = asyncio.run(get_travel_time(AIRPORT, (33.2541, 126.5601), settings=Settings(mock=False, kakao_rest_api_key="", _env_file=None)))
    assert r.estimated and r.minutes > 20 and r.km > 30


def test_ttl_cache_expires():
    now = [0.0]
    c = TTLCache(ttl_seconds=300, clock=lambda: now[0])
    c.set("a", 1)
    now[0] = 299
    assert c.get("a") == 1
    now[0] = 301
    assert c.get("a") is None
