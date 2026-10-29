"""좌표 변환 유틸. 오피넷은 KATEC, 지도/브라우저는 WGS84(위경도)를 쓴다."""
from __future__ import annotations

import math
from typing import Tuple

from pyproj import Transformer

# 오피넷 KATEC (Bessel 타원체, 도쿄 datum → WGS84 7-parameter)
KATEC_PROJ4 = (
    "+proj=tmerc +lat_0=38 +lon_0=128 +k=0.9999 +x_0=400000 +y_0=600000 "
    "+ellps=bessel +units=m +no_defs "
    "+towgs84=-115.80,474.99,674.11,1.16,-2.31,-1.63,6.43"
)

_to_katec = Transformer.from_crs("EPSG:4326", KATEC_PROJ4, always_xy=True)
_to_wgs84 = Transformer.from_crs(KATEC_PROJ4, "EPSG:4326", always_xy=True)

Point = Tuple[float, float]  # (lat, lng)


def wgs84_to_katec(lat: float, lng: float) -> Tuple[float, float]:
    """WGS84 위경도를 KATEC (x, y) 미터 좌표로 변환한다."""
    x, y = _to_katec.transform(lng, lat)
    return float(x), float(y)


def katec_to_wgs84(x: float, y: float) -> Tuple[float, float]:
    """KATEC (x, y) 좌표를 WGS84 (lat, lng)로 변환한다."""
    lng, lat = _to_wgs84.transform(x, y)
    return float(lat), float(lng)


def haversine_km(a: Point, b: Point) -> float:
    """두 (lat, lng) 지점 사이의 대원거리(km)."""
    r = 6371.0088
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(h))


def offset_point(lat: float, lng: float, north_m: float, east_m: float) -> Point:
    """(lat, lng)에서 북/동쪽으로 미터 단위 이동한 지점."""
    dlat = north_m / 111_320.0
    dlng = east_m / (111_320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lng + dlng
