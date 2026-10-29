"""알림 규칙/이력/가격이력/푸시 구독 모델 (SQLModel) 과 요청 스키마 (Pydantic).

SQLModel 테이블 모델은 annotations 지연 평가(from __future__)를 쓰지 않는다.
"""
from datetime import date, datetime, time, timedelta
from typing import List, Optional

from pydantic import NaiveDatetime, BaseModel, Field as PField, model_validator
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from stations.schemas import FUEL_TYPES

ALERT_TARGET_PRICE = "target_price"  # a. 목표가 도달
ALERT_DROP = "drop"  # b. 최저가 하락폭
ALERT_TOTAL_COST = "total_cost"  # c. 실질 총비용
ALERT_TYPES = (ALERT_TARGET_PRICE, ALERT_DROP, ALERT_TOTAL_COST)
ALLOWED_RADIUS_KM = (1, 3, 5, 10)
KST_OFFSET = timedelta(hours=9)


def utcnow() -> datetime:
    """DB 에 저장하는 시각은 naive UTC 로 통일한다."""
    return datetime.utcnow()


def to_kst(dt: datetime) -> datetime:
    """naive UTC -> naive KST."""
    return dt + KST_OFFSET


def rental_expiry(rental_end: Optional[date]) -> Optional[datetime]:
    """대여 종료일 KST 23:59:59 를 naive UTC 로 환산."""
    if rental_end is None:
        return None
    return datetime.combine(rental_end, time(23, 59, 59)) - KST_OFFSET


def round_coord(v: Optional[float]) -> Optional[float]:
    """위치는 소수점 3자리(약 110m)로 반올림해 최소 정밀도로만 저장한다."""
    return None if v is None else round(float(v), 3)


# ---------------------------------------------------------------- 테이블
class AlertRule(SQLModel, table=True):
    """사용자가 등록한 알림 조건. 익명 device_token 으로 소유자를 구분한다."""

    id: Optional[int] = Field(default=None, primary_key=True)
    device_token: str = Field(index=True)
    name: str = ""
    label: str = ""  # 기준 위치 표시명 (예: 제주공항)
    lat: float
    lng: float
    radius_km: int = 3
    fuel_type: str = "B027"
    alert_types: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    target_price: Optional[int] = None
    drop_amount: Optional[int] = None
    total_cost_limit: Optional[int] = None
    self_only: bool = False
    alttle_only: bool = False
    rental_start: Optional[date] = None
    rental_end: Optional[date] = None
    return_lat: Optional[float] = None
    return_lng: Optional[float] = None
    return_label: str = ""
    exclude_far_detour: bool = False
    max_detour_minutes: int = 10
    liters: float = 30.0
    time_value_per_hour: int = 10_000
    cooldown_hours: int = 6
    email: Optional[str] = None
    is_active: bool = True
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    expires_at: Optional[NaiveDatetime] = None
    last_sent_at: Optional[NaiveDatetime] = None
    summary_d1_sent: bool = False
    summary_d0_sent: bool = False


class AlertEvent(SQLModel, table=True):
    """발송 이력. status: sent | failed | test | summary."""

    id: Optional[int] = Field(default=None, primary_key=True)
    rule_id: int = Field(index=True)
    device_token: str = ""
    station_id: str = ""
    station_name: str = ""
    kind: str = ""
    price: Optional[int] = None
    message: str = ""
    status: str = "sent"
    attempts: int = 1
    error: Optional[str] = None
    created_at: NaiveDatetime = Field(default_factory=utcnow, index=True)


class PriceHistory(SQLModel, table=True):
    """주유소별 가격 이력 (알림 판단 + 7일 추이 차트)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    station_id: str = Field(index=True)
    station_name: str = ""
    fuel_type: str = "B027"
    price: int
    recorded_at: NaiveDatetime = Field(default_factory=utcnow, index=True)


class PushSubscription(SQLModel, table=True):
    """웹 푸시 구독 (기기당 1개)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    device_token: str = Field(index=True, unique=True)
    endpoint: str
    p256dh: str
    auth: str
    created_at: NaiveDatetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------- 요청 스키마
def validate_conditions(
    alert_types: List[str],
    target_price: Optional[int],
    drop_amount: Optional[int],
    total_cost_limit: Optional[int],
) -> None:
    """선택한 알림 유형에 맞는 기준값이 있는지 검사한다. 문제가 있으면 ValueError(한국어)."""
    if not alert_types:
        raise ValueError("알림 유형을 하나 이상 선택해 주세요.")
    bad = [t for t in alert_types if t not in ALERT_TYPES]
    if bad:
        raise ValueError(f"알 수 없는 알림 유형입니다: {', '.join(bad)}")
    if ALERT_TARGET_PRICE in alert_types and not (target_price and target_price > 0):
        raise ValueError("목표가(원/L)를 입력해 주세요.")
    if ALERT_DROP in alert_types and not (drop_amount and drop_amount > 0):
        raise ValueError("하락폭(원)을 입력해 주세요.")
    if ALERT_TOTAL_COST in alert_types and not (total_cost_limit and total_cost_limit > 0):
        raise ValueError("총비용 기준(원)을 입력해 주세요.")


class AlertRuleCreate(BaseModel):
    """알림 등록 요청."""

    name: str = ""
    label: str = ""
    lat: float = PField(ge=32.5, le=34.2)  # 제주 일대
    lng: float = PField(ge=125.8, le=127.2)
    radius_km: int = 3
    fuel_type: str = "B027"
    alert_types: List[str]
    target_price: Optional[int] = None
    drop_amount: Optional[int] = None
    total_cost_limit: Optional[int] = None
    self_only: bool = False
    alttle_only: bool = False
    rental_start: Optional[date] = None
    rental_end: Optional[date] = None
    return_lat: Optional[float] = None
    return_lng: Optional[float] = None
    return_label: str = ""
    exclude_far_detour: bool = False
    max_detour_minutes: int = PField(default=10, ge=1, le=120)
    liters: float = PField(default=30.0, gt=0, le=200)
    time_value_per_hour: int = PField(default=10_000, ge=0)
    cooldown_hours: int = PField(default=6, ge=0, le=72)
    email: Optional[str] = None

    @model_validator(mode="after")
    def _check(self) -> "AlertRuleCreate":
        if self.radius_km not in ALLOWED_RADIUS_KM:
            raise ValueError("반경은 1/3/5/10km 중에서 선택해 주세요.")
        if self.fuel_type not in FUEL_TYPES:
            raise ValueError("지원하지 않는 유종입니다.")
        if self.rental_start and self.rental_end and self.rental_end < self.rental_start:
            raise ValueError("대여 종료일이 시작일보다 빠릅니다.")
        if self.exclude_far_detour and self.return_lat is None:
            raise ValueError("우회 시간 제외 옵션은 반납 장소가 필요합니다.")
        validate_conditions(self.alert_types, self.target_price, self.drop_amount, self.total_cost_limit)
        return self


class AlertRuleUpdate(BaseModel):
    """알림 수정 요청 (보낸 필드만 반영)."""

    name: Optional[str] = None
    label: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    radius_km: Optional[int] = None
    fuel_type: Optional[str] = None
    alert_types: Optional[List[str]] = None
    target_price: Optional[int] = None
    drop_amount: Optional[int] = None
    total_cost_limit: Optional[int] = None
    self_only: Optional[bool] = None
    alttle_only: Optional[bool] = None
    rental_start: Optional[date] = None
    rental_end: Optional[date] = None
    return_lat: Optional[float] = None
    return_lng: Optional[float] = None
    return_label: Optional[str] = None
    exclude_far_detour: Optional[bool] = None
    max_detour_minutes: Optional[int] = None
    liters: Optional[float] = None
    time_value_per_hour: Optional[int] = None
    cooldown_hours: Optional[int] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None


class PushSubscribeRequest(BaseModel):
    """브라우저 PushSubscription.toJSON() 형태."""

    endpoint: str
    keys: dict
