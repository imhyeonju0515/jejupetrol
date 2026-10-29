"""MOCK=true 용 샘플 주유소 + 시간에 따라 변하는 가짜 가격."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from stations.coord import haversine_km
from stations.schemas import (
    ALTTLE_BRANDS,
    BRAND_NAMES,
    GasStation,
    StationPrice,
)

_BASE: Dict[str, int] = {"B027": 1650, "D047": 1490, "B034": 1890, "K015": 1010}

# (id, 상호, 브랜드, 주소, lat, lng, 셀프, 가격오프셋, 위상)
_SAMPLES: List[Tuple[str, str, str, str, float, float, bool, int, float]] = [
    ("MOCK0001", "공항로셀프주유소", "RTE", "제주시 공항로 2", 33.5072, 126.4985, True, -35, 0.0),
    ("MOCK0002", "용담주유소", "SKE", "제주시 용담이동 1500", 33.5120, 126.5090, False, 25, 0.8),
    ("MOCK0003", "도두알뜰주유소", "NHO", "제주시 도두일동 800", 33.5152, 126.4690, True, -28, 1.6),
    ("MOCK0004", "연동GS주유소", "GSC", "제주시 연동 270", 33.4880, 126.4930, False, 18, 2.2),
    ("MOCK0005", "노형셀프주유소", "SOL", "제주시 노형동 920", 33.4850, 126.4780, True, -10, 2.9),
    ("MOCK0006", "제주시청주유소", "HDO", "제주시 이도이동 1700", 33.4996, 126.5312, False, 30, 3.5),
    ("MOCK0007", "아라셀프주유소", "RTE", "제주시 아라일동 100", 33.4700, 126.5440, True, -42, 4.1),
    ("MOCK0008", "삼화주유소", "SKE", "제주시 삼양일동 55", 33.5240, 126.5870, False, 22, 4.8),
    ("MOCK0009", "애월셀프주유소", "RTE", "제주시 애월읍 애월로 10", 33.4636, 126.3311, True, -30, 5.4),
    ("MOCK0010", "한담주유소", "GSC", "제주시 애월읍 한담로 3", 33.4650, 126.3100, False, 35, 0.4),
    ("MOCK0011", "곽지알뜰주유소", "NHO", "제주시 애월읍 곽지리 400", 33.4480, 126.3000, True, -20, 1.1),
    ("MOCK0012", "한림주유소", "SOL", "제주시 한림읍 한림로 20", 33.4130, 126.2650, False, 15, 1.9),
    ("MOCK0013", "서귀포셀프주유소", "RTE", "서귀포시 중정로 80", 33.2500, 126.5600, True, -38, 2.7),
    ("MOCK0014", "서귀포중앙주유소", "SKE", "서귀포시 중앙로 40", 33.2541, 126.5601, False, 28, 3.3),
    ("MOCK0015", "중문주유소", "HDO", "서귀포시 중문관광로 60", 33.2500, 126.4120, False, 32, 4.0),
    ("MOCK0016", "대정셀프주유소", "NHO", "서귀포시 대정읍 일주서로 10", 33.2200, 126.2500, True, -25, 4.6),
    ("MOCK0017", "성산주유소", "GSC", "서귀포시 성산읍 일출로 100", 33.4580, 126.9425, False, 38, 5.2),
    ("MOCK0018", "성산알뜰주유소", "RTE", "서귀포시 성산읍 성산리 300", 33.4400, 126.9250, True, -18, 0.2),
    ("MOCK0019", "표선셀프주유소", "SOL", "서귀포시 표선면 표선리 20", 33.3260, 126.8350, True, -5, 1.4),
    ("MOCK0020", "조천주유소", "SKE", "제주시 조천읍 신북로 700", 33.5400, 126.6400, False, 20, 2.4),
]


def _price(sample: Tuple, fuel_type: str, at: datetime) -> int:
    """시각 at 의 가짜 가격. 10분 단위로 변하며 약 6시간 주기의 파동 + 느린 드리프트."""
    base = _BASE.get(fuel_type, 1650)
    _, _, _, _, _, _, _, offset, phase = sample
    bucket = int(at.replace(tzinfo=timezone.utc).timestamp() // 600)
    wave = math.sin(bucket / 36 * 2 * math.pi + phase) * 25
    drift = math.sin(bucket / 600 * 2 * math.pi + phase) * 15
    return int(round(base + offset + wave + drift))


def _to_station(sample: Tuple, fuel_type: str, at: datetime, origin: Optional[Tuple[float, float]]) -> GasStation:
    sid, name, brand, addr, lat, lng, is_self, _, _ = sample
    return GasStation(
        id=sid,
        name=name,
        brand=brand,
        brand_name=BRAND_NAMES.get(brand, brand),
        address=addr,
        lat=lat,
        lng=lng,
        price=_price(sample, fuel_type, at),
        fuel_type=fuel_type,
        is_self=is_self,
        is_alttle=brand in ALTTLE_BRANDS,
        distance_m=round(haversine_km(origin, (lat, lng)) * 1000, 1) if origin else None,
        updated_at=at.replace(minute=(at.minute // 10) * 10, second=0, microsecond=0),
    )


def find_stations(
    lat: float, lng: float, radius_m: int, fuel_type: str, now: Optional[datetime] = None
) -> List[GasStation]:
    """반경 내 샘플 주유소 (가격 오름차순)."""
    at = now or datetime.utcnow()
    found = []
    for s in _SAMPLES:
        d = haversine_km((lat, lng), (s[4], s[5])) * 1000
        if d <= radius_m:
            found.append(_to_station(s, fuel_type, at, (lat, lng)))
    found.sort(key=lambda x: (x.price or 10**9, x.distance_m or 0))
    return found


def get_station_prices(
    station_ids: List[str], fuel_type: str, now: Optional[datetime] = None
) -> Dict[str, StationPrice]:
    """샘플 주유소의 상세 가격."""
    at = now or datetime.utcnow()
    out: Dict[str, StationPrice] = {}
    by_id = {s[0]: s for s in _SAMPLES}
    for sid in station_ids:
        s = by_id.get(sid)
        if not s:
            continue
        st = _to_station(s, fuel_type, at, None)
        out[sid] = StationPrice(
            station_id=sid,
            name=st.name,
            brand=st.brand,
            brand_name=st.brand_name,
            address=st.address,
            lat=st.lat,
            lng=st.lng,
            fuel_type=fuel_type,
            price=st.price,
            updated_at=st.updated_at,
            is_self=st.is_self,
            is_alttle=st.is_alttle,
            all_prices={f: _price(s, f, at) for f in _BASE},
        )
    return out


def price_history(
    station_id: str, fuel_type: str, days: int, now: Optional[datetime] = None
) -> List[Tuple[datetime, int]]:
    """샘플 주유소의 과거 가격 (3시간 간격)."""
    at = now or datetime.utcnow()
    sample = next((s for s in _SAMPLES if s[0] == station_id), None)
    if sample is None:
        return []
    points = []
    t = at - timedelta(days=days)
    while t <= at:
        points.append((t, _price(sample, fuel_type, t)))
        t += timedelta(hours=3)
    return points
