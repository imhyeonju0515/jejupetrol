"""알림 규칙 CRUD, 조건 평가, check_alerts 본체."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from sqlmodel import Session, select

from alerts.models import (
    ALERT_DROP,
    ALERT_TARGET_PRICE,
    ALERT_TOTAL_COST,
    AlertEvent,
    AlertRule,
    AlertRuleCreate,
    AlertRuleUpdate,
    PriceHistory,
    PushSubscription,
    rental_expiry,
    round_coord,
    to_kst,
    utcnow,
    validate_conditions,
)
from alerts.notifier import (
    NotificationMessage,
    NotificationTarget,
    Notifier,
    SendResult,
    build_notifier,
    format_price_alert,
    send_with_retry,
)
from config import Settings, get_settings
from stations.coord import haversine_km
from stations.finder import find_gas_stations
from stations.recommender import Recommendation, Trip, build_recommendations, measure_trips
from stations.schemas import FUEL_TYPES, GasStation
from stations.travel import TravelFn, get_travel_time

logger = logging.getLogger(__name__)

FindFn = Callable[[float, float, int, str], Awaitable[List[GasStation]]]
SleepFn = Callable[[float], Awaitable[None]]


class AlertNotFound(LookupError):
    """존재하지 않거나 다른 기기의 알림."""


# ------------------------------------------------------------------ CRUD
def create_alert(session: Session, device_token: str, data: AlertRuleCreate,
                 now: Optional[datetime] = None) -> AlertRule:
    """알림을 등록한다. 위치는 소수점 3자리로 반올림, 대여 종료일 24시(KST)에 만료."""
    now = now or utcnow()
    values = data.model_dump()
    values["lat"], values["lng"] = round_coord(data.lat), round_coord(data.lng)
    values["return_lat"], values["return_lng"] = round_coord(data.return_lat), round_coord(data.return_lng)
    rule = AlertRule(device_token=device_token, created_at=now,
                     expires_at=rental_expiry(data.rental_end), **values)
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def list_alerts(session: Session, device_token: str) -> List[AlertRule]:
    """기기의 알림 목록 (최신순)."""
    return list(session.exec(
        select(AlertRule).where(AlertRule.device_token == device_token).order_by(AlertRule.id.desc())
    ).all())


def get_alert(session: Session, device_token: str, rule_id: int) -> AlertRule:
    """내 알림 1건. 없으면 AlertNotFound."""
    rule = session.get(AlertRule, rule_id)
    if rule is None or rule.device_token != device_token:
        raise AlertNotFound("알림을 찾을 수 없습니다.")
    return rule


def update_alert(session: Session, device_token: str, rule_id: int, patch: AlertRuleUpdate,
                 now: Optional[datetime] = None) -> AlertRule:
    """알림 수정/활성 전환. 잘못된 값이면 ValueError(한국어)."""
    now = now or utcnow()
    rule = get_alert(session, device_token, rule_id)
    changes = patch.model_dump(exclude_unset=True)
    if "radius_km" in changes and changes["radius_km"] not in (1, 3, 5, 10):
        raise ValueError("반경은 1/3/5/10km 중에서 선택해 주세요.")
    if "fuel_type" in changes and changes["fuel_type"] not in FUEL_TYPES:
        raise ValueError("지원하지 않는 유종입니다.")
    for k in ("lat", "lng", "return_lat", "return_lng"):
        if k in changes:
            changes[k] = round_coord(changes[k])
    for k, v in changes.items():
        setattr(rule, k, v)
    validate_conditions(rule.alert_types, rule.target_price, rule.drop_amount, rule.total_cost_limit)
    if rule.rental_start and rule.rental_end and rule.rental_end < rule.rental_start:
        raise ValueError("대여 종료일이 시작일보다 빠릅니다.")
    if "rental_end" in changes:
        rule.expires_at = rental_expiry(rule.rental_end)
    if rule.is_active and rule.expires_at and rule.expires_at <= now:
        raise ValueError("대여 기간이 이미 종료된 알림은 켤 수 없습니다.")
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def toggle_alert(session: Session, device_token: str, rule_id: int,
                 now: Optional[datetime] = None) -> AlertRule:
    """활성/비활성 전환."""
    rule = get_alert(session, device_token, rule_id)
    return update_alert(session, device_token, rule_id, AlertRuleUpdate(is_active=not rule.is_active), now)


def delete_alert(session: Session, device_token: str, rule_id: int) -> None:
    """알림과 그 발송 이력을 삭제한다."""
    rule = get_alert(session, device_token, rule_id)
    for ev in session.exec(select(AlertEvent).where(AlertEvent.rule_id == rule_id)).all():
        session.delete(ev)
    session.delete(rule)
    session.commit()


def list_events(session: Session, device_token: str, rule_id: int, limit: int = 50) -> List[AlertEvent]:
    """알림 발송 이력 (최신순)."""
    get_alert(session, device_token, rule_id)
    return list(session.exec(
        select(AlertEvent).where(AlertEvent.rule_id == rule_id)
        .order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc()).limit(limit)
    ).all())


# ------------------------------------------------------------------ 구독
def save_subscription(session: Session, device_token: str, endpoint: str, p256dh: str, auth: str) -> None:
    """푸시 구독을 저장(기기당 1개, 있으면 갱신)."""
    sub = session.exec(select(PushSubscription).where(PushSubscription.device_token == device_token)).first()
    if sub is None:
        sub = PushSubscription(device_token=device_token, endpoint=endpoint, p256dh=p256dh, auth=auth)
    else:
        sub.endpoint, sub.p256dh, sub.auth = endpoint, p256dh, auth
    session.add(sub)
    session.commit()


def delete_subscription(session: Session, device_token: str) -> bool:
    """푸시 구독 삭제. 삭제했으면 True."""
    sub = session.exec(select(PushSubscription).where(PushSubscription.device_token == device_token)).first()
    if sub is None:
        return False
    session.delete(sub)
    session.commit()
    return True


# ------------------------------------------------------------------ 만료/정리
def expire_rules(session: Session, now: Optional[datetime] = None) -> int:
    """대여 기간이 끝난 규칙을 비활성화하고, 활성 규칙이 없어진 기기의 푸시 구독을 삭제한다.

    Returns: 비활성화한 규칙 수.
    """
    now = now or utcnow()
    expired = session.exec(select(AlertRule).where(
        AlertRule.is_active == True,  # noqa: E712
        AlertRule.expires_at != None,  # noqa: E711
        AlertRule.expires_at <= now,
    )).all()
    devices = set()
    for rule in expired:
        rule.is_active = False
        devices.add(rule.device_token)
        session.add(rule)
    session.commit()
    for token in devices:
        still_active = session.exec(select(AlertRule).where(
            AlertRule.device_token == token, AlertRule.is_active == True)).first()  # noqa: E712
        if still_active is None:
            delete_subscription(session, token)
    return len(expired)


# ------------------------------------------------------------------ 가격 이력
def record_price_history(session: Session, stations: Sequence[GasStation], now: Optional[datetime] = None) -> int:
    """가격이 바뀌었거나 최근 1시간 내 기록이 없으면 이력을 추가한다. 추가 건수 반환."""
    now = now or utcnow()
    priced = [s for s in stations if s.price]
    if not priced:
        return 0
    ids = [s.id for s in priced]
    fuel = priced[0].fuel_type
    recent = session.exec(select(PriceHistory).where(
        PriceHistory.station_id.in_(ids), PriceHistory.fuel_type == fuel,
        PriceHistory.recorded_at >= now - timedelta(hours=1),
    ).order_by(PriceHistory.recorded_at)).all()
    latest = {r.station_id: r.price for r in recent}
    added = 0
    for s in priced:
        if latest.get(s.id) != s.price:
            session.add(PriceHistory(station_id=s.id, station_name=s.name, fuel_type=s.fuel_type,
                                     price=s.price, recorded_at=now))
            added += 1
    session.commit()
    return added


def get_price_history(session: Session, station_id: str, fuel_type: str, days: int = 7,
                      now: Optional[datetime] = None) -> List[PriceHistory]:
    """최근 days 일의 가격 이력 (오래된 순)."""
    now = now or utcnow()
    return list(session.exec(select(PriceHistory).where(
        PriceHistory.station_id == station_id, PriceHistory.fuel_type == fuel_type,
        PriceHistory.recorded_at >= now - timedelta(days=days),
    ).order_by(PriceHistory.recorded_at)).all())


def prune_price_history(session: Session, now: Optional[datetime] = None, keep_days: int = 14) -> int:
    """오래된 가격 이력 삭제."""
    now = now or utcnow()
    old = session.exec(select(PriceHistory).where(PriceHistory.recorded_at < now - timedelta(days=keep_days))).all()
    for r in old:
        session.delete(r)
    session.commit()
    return len(old)


def load_old_prices(session: Session, station_ids: Sequence[str], fuel_type: str,
                    now: datetime) -> Dict[str, int]:
    """'어제' 기준 가격: 24시간 전 이전의 가장 최근 기록, 없으면 1시간 이상 지난 가장 오래된 기록."""
    if not station_ids:
        return {}
    rows = session.exec(select(PriceHistory).where(
        PriceHistory.station_id.in_(list(station_ids)), PriceHistory.fuel_type == fuel_type,
        PriceHistory.recorded_at >= now - timedelta(hours=48),
    ).order_by(PriceHistory.recorded_at)).all()
    by: Dict[str, List[PriceHistory]] = defaultdict(list)
    for r in rows:
        by[r.station_id].append(r)
    out: Dict[str, int] = {}
    cutoff = now - timedelta(hours=24)
    for sid, lst in by.items():
        before = [r for r in lst if r.recorded_at <= cutoff]
        if before:
            out[sid] = before[-1].price
        elif lst[0].recorded_at <= now - timedelta(hours=1):
            out[sid] = lst[0].price
    return out


# ------------------------------------------------------------------ 조건 평가 (순수 함수)
@dataclass
class Trigger:
    """알림 조건을 충족한 주유소."""

    station: GasStation
    kinds: List[str] = field(default_factory=list)
    price: int = 0
    total_cost: Optional[int] = None


def filter_candidates(rule: AlertRule, stations: Sequence[GasStation]) -> List[GasStation]:
    """규칙의 반경/셀프/알뜰 필터를 적용한다."""
    out = []
    for s in stations:
        if not s.price:
            continue
        if haversine_km((rule.lat, rule.lng), (s.lat, s.lng)) > rule.radius_km:
            continue
        if rule.self_only and not s.is_self:
            continue
        if rule.alttle_only and not s.is_alttle:
            continue
        out.append(s)
    return out


def filter_by_detour(stations: Sequence[GasStation], trips: Dict[str, Trip],
                     max_minutes: float) -> List[GasStation]:
    """우회 시간이 max_minutes 를 넘는 주유소를 제외한다."""
    return [s for s in stations if s.id in trips and trips[s.id].extra_minutes <= max_minutes]


def evaluate_conditions(
    rule: AlertRule,
    candidates: Sequence[GasStation],
    baseline_min: Optional[int] = None,
    best_total: Optional[Recommendation] = None,
) -> List[Trigger]:
    """a/b/c 조건을 평가해 충족한 주유소(가격 오름차순)를 돌려준다.

    - target_price: 가격 <= 목표가인 모든 주유소
    - drop: 반경 내 현재 최저가가 baseline_min 보다 drop_amount 이상 낮을 때 그 주유소
    - total_cost: 실질 총비용 1위가 기준 이하일 때 그 주유소
    """
    found: Dict[str, Trigger] = {}

    def add(station: GasStation, kind: str, total: Optional[int] = None) -> None:
        t = found.setdefault(station.id, Trigger(station=station, price=station.price or 0))
        if kind not in t.kinds:
            t.kinds.append(kind)
        if total is not None:
            t.total_cost = total

    if ALERT_TARGET_PRICE in rule.alert_types and rule.target_price:
        for s in candidates:
            if s.price and s.price <= rule.target_price:
                add(s, ALERT_TARGET_PRICE)
    if ALERT_DROP in rule.alert_types and rule.drop_amount and baseline_min is not None and candidates:
        cheapest = min(candidates, key=lambda s: s.price or 10**9)
        if cheapest.price and baseline_min - cheapest.price >= rule.drop_amount:
            add(cheapest, ALERT_DROP)
    if ALERT_TOTAL_COST in rule.alert_types and rule.total_cost_limit and best_total is not None:
        if best_total.total_cost <= rule.total_cost_limit:
            add(best_total.station, ALERT_TOTAL_COST, best_total.total_cost)
    return sorted(found.values(), key=lambda t: t.price)


def in_cooldown(session: Session, rule: AlertRule, station_id: str, now: datetime) -> bool:
    """같은 규칙+주유소로 쿨다운 시간 안에 이미 발송했는지."""
    if rule.cooldown_hours <= 0:
        return False
    since = now - timedelta(hours=rule.cooldown_hours)
    return session.exec(select(AlertEvent).where(
        AlertEvent.rule_id == rule.id, AlertEvent.station_id == station_id,
        AlertEvent.status == "sent", AlertEvent.created_at > since,
    )).first() is not None


# ------------------------------------------------------------------ 발송
def _target_for(session: Session, rule: AlertRule) -> NotificationTarget:
    sub = session.exec(select(PushSubscription).where(PushSubscription.device_token == rule.device_token)).first()
    return NotificationTarget(
        device_token=rule.device_token,
        push_subscription={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}} if sub else None,
        email=rule.email,
    )


async def _send_and_log(
    session: Session, rule: AlertRule, message: NotificationMessage, *, status_ok: str,
    kind: str, station_id: str, station_name: str, price: Optional[int], now: datetime,
    notifier: Notifier, settings: Settings, retry_sleep: Optional[SleepFn],
) -> Tuple[SendResult, AlertEvent]:
    kwargs = {"max_attempts": settings.notify_max_attempts}
    if retry_sleep is not None:
        kwargs["sleep"] = retry_sleep
    result = await send_with_retry(notifier, _target_for(session, rule), message, **kwargs)
    event = AlertEvent(
        rule_id=rule.id, device_token=rule.device_token, station_id=station_id, station_name=station_name,
        kind=kind, price=price, message=message.body, status=status_ok if result.ok else "failed",
        attempts=result.attempts, error=result.error, created_at=now,
    )
    session.add(event)
    if result.ok and status_ok == "sent":
        rule.last_sent_at = now
        session.add(rule)
    if result.permanent:  # 구독 만료 등 영구 실패 -> 구독 자동 삭제
        delete_subscription(session, rule.device_token)
    session.commit()
    return result, event


async def send_test(session: Session, rule: AlertRule, *, notifier: Optional[Notifier] = None,
                    settings: Optional[Settings] = None, retry_sleep: Optional[SleepFn] = None,
                    now: Optional[datetime] = None) -> Tuple[SendResult, AlertEvent]:
    """테스트 알림을 즉시 발송한다 (쿨다운/조건과 무관)."""
    settings = settings or get_settings()
    notifier = notifier or build_notifier(settings)
    body = (f"[제주 주유 알림] 테스트 알림입니다 · {rule.label or '내 위치'} {rule.radius_km}km 내 "
            f"{FUEL_TYPES.get(rule.fuel_type, rule.fuel_type)} 알림이 정상 동작 중입니다.")
    message = NotificationMessage(title="제주 주유 알림", body=body, url="/#/alerts", tag=f"test-{rule.id}")
    return await _send_and_log(session, rule, message, status_ok="test", kind="test", station_id="",
                               station_name="", price=None, now=now or utcnow(), notifier=notifier,
                               settings=settings, retry_sleep=retry_sleep)


# ------------------------------------------------------------------ check_alerts
@dataclass
class CheckReport:
    groups: int = 0
    api_calls: int = 0
    rules_checked: int = 0
    sent: int = 0
    failed: int = 0
    skipped_cooldown: int = 0
    deferred_groups: int = 0
    expired: int = 0


_cursor = 0  # 배치 처리 시 다음 사이클이 이어서 시작할 위치


async def _process_rule(
    session: Session, rule: AlertRule, stations: Sequence[GasStation], old_prices: Dict[str, int],
    now: datetime, notifier: Notifier, travel_fn: TravelFn, settings: Settings,
    retry_sleep: Optional[SleepFn], report: CheckReport,
) -> None:
    cands = filter_candidates(rule, stations)
    if not cands:
        return
    origin = (rule.lat, rule.lng)
    dest = (rule.return_lat, rule.return_lng) if rule.return_lat is not None and rule.return_lng is not None else None
    detour_filter = rule.exclude_far_detour and dest is not None
    trips: Optional[Dict[str, Trip]] = None
    if detour_filter or ALERT_TOTAL_COST in rule.alert_types:
        trips = await measure_trips(origin, cands, dest, travel_fn)
    if detour_filter:
        cands = filter_by_detour(cands, trips, rule.max_detour_minutes)
        if not cands:
            return

    olds = [old_prices[s.id] for s in cands if s.id in old_prices]
    baseline_min = min(olds) if olds else None
    best_total = None
    if ALERT_TOTAL_COST in rule.alert_types:
        ranked = build_recommendations(cands, trips, rule.liters, rule.time_value_per_hour)
        best_total = ranked[0] if ranked else None

    report.rules_checked += 1
    for trig in evaluate_conditions(rule, cands, baseline_min, best_total):
        s = trig.station
        if in_cooldown(session, rule, s.id, now):
            report.skipped_cooldown += 1
            continue
        if trips is not None and s.id in trips:
            minutes: Optional[float] = trips[s.id].leg_minutes
        else:
            minutes = (await travel_fn(origin, (s.lat, s.lng))).minutes
        delta = s.price - old_prices[s.id] if s.id in old_prices else None
        body = format_price_alert(
            label=rule.label, radius_km=rule.radius_km, fuel_name=FUEL_TYPES.get(rule.fuel_type, rule.fuel_type),
            price=s.price, is_self=s.is_self, delta_vs_yesterday=delta, travel_minutes=minutes,
        )
        message = NotificationMessage(
            title="제주 주유 알림", body=body, tag=f"rule-{rule.id}-{s.id}",
            url=f"/#/?station={s.id}&lat={s.lat}&lng={s.lng}",
        )
        result, _ = await _send_and_log(
            session, rule, message, status_ok="sent", kind="+".join(trig.kinds), station_id=s.id,
            station_name=s.name, price=s.price, now=now, notifier=notifier, settings=settings,
            retry_sleep=retry_sleep,
        )
        if result.ok:
            report.sent += 1
        else:
            report.failed += 1
        break  # 규칙당 한 사이클에 1건만 (가장 싼 주유소)


async def check_alerts(
    session: Session,
    *,
    now: Optional[datetime] = None,
    settings: Optional[Settings] = None,
    find_fn: Optional[FindFn] = None,
    travel_fn: Optional[TravelFn] = None,
    notifier: Optional[Notifier] = None,
    batch_size: Optional[int] = None,
    batch_delay: Optional[float] = None,
    sleep: SleepFn = asyncio.sleep,
    retry_sleep: Optional[SleepFn] = None,
) -> CheckReport:
    """활성 규칙을 검사해 조건 충족 시 알림을 보낸다.

    같은 (위치, 유종) 규칙은 하나의 그룹으로 묶어 최대 반경으로 오피넷을 1회만 호출한다.
    그룹 수가 batch_size 를 넘으면 사이클마다 나눠서 처리하고, 그룹 사이에 batch_delay 만큼 쉰다.
    """
    global _cursor
    settings = settings or get_settings()
    now = now or utcnow()
    find_fn = find_fn or (lambda la, ln, r, f: find_gas_stations(la, ln, r, f, settings=settings))
    travel_fn = travel_fn or (lambda o, d: get_travel_time(o, d, settings=settings))
    notifier = notifier or build_notifier(settings)
    batch_size = batch_size or settings.alert_batch_size
    batch_delay = settings.alert_batch_delay_seconds if batch_delay is None else batch_delay

    report = CheckReport()
    report.expired = expire_rules(session, now)
    rules = session.exec(select(AlertRule).where(AlertRule.is_active == True)).all()  # noqa: E712
    rules = [r for r in rules if r.expires_at is None or r.expires_at > now]
    groups: Dict[Tuple[float, float, str], List[AlertRule]] = defaultdict(list)
    for r in rules:
        groups[(r.lat, r.lng, r.fuel_type)].append(r)

    keys = sorted(groups)
    report.groups = len(keys)
    if len(keys) > batch_size:
        start = _cursor % len(keys)
        keys = (keys + keys)[start:start + batch_size]
        _cursor += batch_size
        report.deferred_groups = report.groups - batch_size

    for i, key in enumerate(keys):
        lat, lng, fuel = key
        grp = groups[key]
        max_radius_m = max(r.radius_km for r in grp) * 1000
        try:
            stations = await find_fn(lat, lng, max_radius_m, fuel)
            report.api_calls += 1
        except Exception as exc:  # UpstreamError 등 — 다음 주기에 재시도
            logger.error("주유소 조회 실패 (%s,%s,%s): %s", lat, lng, fuel, exc)
            continue
        old = load_old_prices(session, [s.id for s in stations], fuel, now)
        record_price_history(session, stations, now)
        for rule in grp:
            try:
                await _process_rule(session, rule, stations, old, now, notifier, travel_fn,
                                    settings, retry_sleep, report)
            except Exception:
                logger.exception("알림 규칙 처리 실패 (rule=%s)", rule.id)
        if batch_delay and i < len(keys) - 1:
            await sleep(batch_delay)
    return report


# ------------------------------------------------------------------ 반납 전 요약
async def send_return_summaries(
    session: Session,
    *,
    now: Optional[datetime] = None,
    settings: Optional[Settings] = None,
    find_fn: Optional[FindFn] = None,
    notifier: Optional[Notifier] = None,
    retry_sleep: Optional[SleepFn] = None,
) -> int:
    """반납일 D-1, D-day 오전(KST 7시 이후)에 반납 장소 3km 내 최저가 TOP3 요약을 1회씩 보낸다."""
    settings = settings or get_settings()
    now = now or utcnow()
    kst = to_kst(now)
    if kst.hour < 7:
        return 0
    find_fn = find_fn or (lambda la, ln, r, f: find_gas_stations(la, ln, r, f, settings=settings))
    notifier = notifier or build_notifier(settings)
    sent = 0
    rules = session.exec(select(AlertRule).where(AlertRule.is_active == True)).all()  # noqa: E712
    for rule in rules:
        if rule.rental_end is None or rule.return_lat is None or rule.return_lng is None:
            continue
        days_left = (rule.rental_end - kst.date()).days
        if days_left == 1 and not rule.summary_d1_sent:
            flag, tag = "summary_d1_sent", "D-1"
        elif days_left == 0 and not rule.summary_d0_sent:
            flag, tag = "summary_d0_sent", "D-day"
        else:
            continue
        try:
            stations = await find_fn(rule.return_lat, rule.return_lng, 3000, rule.fuel_type)
        except Exception as exc:
            logger.error("반납 요약 조회 실패 (rule=%s): %s", rule.id, exc)
            continue
        pool = [s for s in stations if s.price and (not rule.self_only or s.is_self)
                and (not rule.alttle_only or s.is_alttle)]
        top = sorted(pool, key=lambda s: s.price)[:3]
        if not top:
            continue
        lines = " · ".join(f"{i}) {s.name} {s.price:,}원" for i, s in enumerate(top, 1))
        body = (f"[제주 주유 알림] 반납 전 주유 추천 ({tag}) {rule.return_label or '반납 장소'} 근처 "
                f"{FUEL_TYPES.get(rule.fuel_type, rule.fuel_type)} TOP{len(top)} · {lines}")
        message = NotificationMessage(
            title="제주 주유 알림", body=body, tag=f"summary-{rule.id}-{tag}",
            url=f"/#/?station={top[0].id}&lat={top[0].lat}&lng={top[0].lng}",
        )
        result, _ = await _send_and_log(
            session, rule, message, status_ok="summary", kind="summary", station_id=top[0].id,
            station_name=top[0].name, price=top[0].price, now=now, notifier=notifier,
            settings=settings, retry_sleep=retry_sleep,
        )
        if result.ok:
            setattr(rule, flag, True)
            session.add(rule)
            session.commit()
            sent += 1
    return sent
