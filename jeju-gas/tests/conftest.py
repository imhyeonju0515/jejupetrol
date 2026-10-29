"""공용 픽스처/헬퍼."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import pytest
from sqlmodel import Session, SQLModel

from alerts import models  # noqa: F401  (테이블 등록)
from alerts.models import AlertRuleCreate
from config import Settings
from database import make_engine
from stations.coord import haversine_km
from stations.schemas import GasStation
from stations.travel import TravelResult, estimate_travel

NOW = datetime(2026, 10, 29, 3, 0, 0)  # naive UTC (= KST 12:00)
AIRPORT = (33.5113, 126.493)


@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def settings() -> Settings:
    return Settings(mock=True, alert_batch_delay_seconds=0, _env_file=None)


def make_station(sid: str, price: int, lat: float = 33.5113, lng: float = 126.493,
                 is_self: bool = False, is_alttle: bool = False, fuel: str = "B027") -> GasStation:
    return GasStation(id=sid, name=f"주유소{sid}", lat=lat, lng=lng, price=price, fuel_type=fuel,
                      is_self=is_self, is_alttle=is_alttle,
                      distance_m=haversine_km(AIRPORT, (lat, lng)) * 1000)


def rule_data(**over) -> AlertRuleCreate:
    base = dict(label="제주공항", lat=AIRPORT[0], lng=AIRPORT[1], radius_km=3, fuel_type="B027",
                alert_types=["target_price"], target_price=1600)
    base.update(over)
    return AlertRuleCreate(**base)


class FakeFind:
    """find_fn 대역: 호출 횟수를 센다."""

    def __init__(self, stations: List[GasStation]) -> None:
        self.stations = stations
        self.calls: list = []

    async def __call__(self, lat, lng, radius_m, fuel):
        self.calls.append((lat, lng, radius_m, fuel))
        return list(self.stations)


async def fake_travel(origin, dest) -> TravelResult:
    return estimate_travel(origin, dest)


async def no_sleep(_: float) -> None:
    return None
