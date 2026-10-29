"""WGS84 <-> KATEC 변환 정확도."""
import pytest

from stations.coord import haversine_km, katec_to_wgs84, offset_point, wgs84_to_katec

JEJU_POINTS = [
    (33.5113, 126.4930),  # 제주공항
    (33.2541, 126.5601),  # 서귀포
    (33.4580, 126.9425),  # 성산
    (33.4636, 126.3311),  # 애월
]


@pytest.mark.parametrize("lat,lng", JEJU_POINTS)
def test_round_trip_is_sub_meter(lat, lng):
    x, y = wgs84_to_katec(lat, lng)
    lat2, lng2 = katec_to_wgs84(x, y)
    assert haversine_km((lat, lng), (lat2, lng2)) * 1000 < 0.5


@pytest.mark.parametrize("lat,lng", JEJU_POINTS)
def test_katec_values_are_in_jeju_range(lat, lng):
    x, y = wgs84_to_katec(lat, lng)
    assert 230_000 < x < 340_000  # 제주는 KATEC 원점(경도 128) 서쪽
    assert 60_000 < y < 130_000


def test_projection_preserves_distance():
    """KATEC 평면거리와 실제 대원거리가 0.5% 이내로 일치해야 한다."""
    a, b = JEJU_POINTS[0], JEJU_POINTS[2]
    (x1, y1), (x2, y2) = wgs84_to_katec(*a), wgs84_to_katec(*b)
    planar_km = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5 / 1000
    assert planar_km == pytest.approx(haversine_km(a, b), rel=0.005)


def test_north_east_axes():
    """북쪽으로 가면 y 증가, 동쪽으로 가면 x 증가."""
    lat, lng = JEJU_POINTS[0]
    x0, y0 = wgs84_to_katec(lat, lng)
    xn, yn = wgs84_to_katec(*offset_point(lat, lng, 1000, 0))
    xe, ye = wgs84_to_katec(*offset_point(lat, lng, 0, 1000))
    # 경도 128 원점에서 1.5° 떨어져 자오선 수렴각(~0.8°)만큼 축이 기운다 -> 30m 허용
    assert yn - y0 == pytest.approx(1000, abs=30) and abs(xn - x0) < 30
    assert xe - x0 == pytest.approx(1000, abs=30) and abs(ye - y0) < 30
