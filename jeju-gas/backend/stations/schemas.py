"""stations 패키지 공용 모델/상수."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel, Field

FUEL_TYPES: Dict[str, str] = {
    "B027": "휘발유",
    "D047": "경유",
    "B034": "고급휘발유",
    "K015": "LPG",
}

BRAND_NAMES: Dict[str, str] = {
    "SKE": "SK에너지",
    "GSC": "GS칼텍스",
    "HDO": "현대오일뱅크",
    "SOL": "S-OIL",
    "RTE": "자영알뜰",
    "RTX": "고속도로알뜰",
    "NHO": "농협알뜰",
    "E1G": "E1",
    "SKG": "SK가스",
    "ETC": "자가상표",
}

ALTTLE_BRANDS = {"RTE", "RTX", "NHO"}  # 알뜰주유소


class UpstreamError(Exception):
    """외부 API 오류. message는 사용자에게 그대로 보여줄 수 있는 한국어 문구."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class GasStation(BaseModel):
    """주변 검색으로 얻은 주유소 한 곳."""

    id: str
    name: str
    brand: str = ""  # 브랜드 코드 (SKE ...)
    brand_name: str = ""
    address: str = ""
    lat: float
    lng: float
    price: Optional[int] = None  # 요청 유종의 리터당 가격(원)
    fuel_type: str = "B027"
    is_self: bool = False
    is_alttle: bool = False
    distance_m: Optional[float] = None
    updated_at: Optional[datetime] = None


class StationPrice(BaseModel):
    """상세 API로 얻은 주유소 가격/속성."""

    station_id: str
    name: str
    brand: str = ""
    brand_name: str = ""
    address: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    fuel_type: str
    price: Optional[int] = None
    updated_at: Optional[datetime] = None
    is_self: bool = False
    is_alttle: bool = False
    all_prices: Dict[str, int] = Field(default_factory=dict)
