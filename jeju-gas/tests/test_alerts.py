"""알림 조건 평가 / 쿨다운 / 만료 / 그룹핑 / 우회 필터 / 재시도."""
import asyncio
from datetime import date, timedelta

import pytest
from sqlmodel import select

from alerts import service
from alerts.models import AlertEvent, AlertRule, PriceHistory, PushSubscription, utcnow
from alerts.notifier import (
    ConsoleNotifier,
    NotificationMessage,
    NotificationTarget,
    Notifier,
    PermanentNotifierError,
    TransientNotifierError,
    format_price_alert,
    send_with_retry,
)
from conftest import AIRPORT, NOW, FakeFind, fake_travel, make_station, no_sleep, rule_data
from stations.recommender import Trip, build_recommendations

TOKEN = "device-token-0000001"


class ScriptedNotifier(Notifier):
    """미리 정한 결과(None=성공, 예외=실패)를 차례로 돌려주는 대역."""

    def __init__(self, script=None):
        self.script = list(script or [])
        self.calls = 0

    async def send(self, target, message):
        self.calls += 1
        outcome = self.script.pop(0) if self.script else None
        if outcome is not None:
            raise outcome


def run_check(session, settings, find, notifier=None, now=NOW, **kw):
    return asyncio.run(service.check_alerts(
        session, now=now, settings=settings, find_fn=find, travel_fn=fake_travel,
        notifier=notifier or ConsoleNotifier(), sleep=no_sleep, retry_sleep=no_sleep, **kw))


def events(session):
    return session.exec(select(AlertEvent)).all()


# ------------------------------------------------------------ 조건 평가
def test_target_price_condition(session):
    rule = service.create_alert(session, TOKEN, rule_data(target_price=1600))
    cands = [make_station("A", 1599), make_station("B", 1601)]
    trig = service.evaluate_conditions(rule, cands)
    assert [t.station.id for t in trig] == ["A"] and trig[0].kinds == ["target_price"]
    assert service.evaluate_conditions(rule, [make_station("B", 1601)]) == []


def test_drop_condition_uses_baseline(session):
    rule = service.create_alert(session, TOKEN, rule_data(alert_types=["drop"], target_price=None, drop_amount=20))
    cands = [make_station("A", 1580), make_station("B", 1650)]
    assert service.evaluate_conditions(rule, cands, baseline_min=1600)  # 20원 하락 = 충족
    assert service.evaluate_conditions(rule, cands, baseline_min=1599) == []  # 19원 하락
    assert service.evaluate_conditions(rule, cands, baseline_min=None) == []  # 기준 이력 없음


def test_total_cost_condition(session):
    rule = service.create_alert(session, TOKEN, rule_data(
        alert_types=["total_cost"], target_price=None, total_cost_limit=48_500))
    s = make_station("A", 1600)
    best = build_recommendations([s], {"A": Trip(extra_minutes=6, extra_km=3, leg_minutes=3)})[0]
    assert best.total_cost == 49_480
    assert service.evaluate_conditions(rule, [s], best_total=best) == []
    rule.total_cost_limit = 49_480
    trig = service.evaluate_conditions(rule, [s], best_total=best)
    assert trig and trig[0].kinds == ["total_cost"] and trig[0].total_cost == 49_480


def test_multiple_kinds_merge_per_station(session):
    rule = service.create_alert(session, TOKEN, rule_data(
        alert_types=["target_price", "drop"], target_price=1600, drop_amount=10))
    trig = service.evaluate_conditions(rule, [make_station("A", 1580)], baseline_min=1600)
    assert len(trig) == 1 and set(trig[0].kinds) == {"target_price", "drop"}


def test_candidate_filters(session):
    rule = service.create_alert(session, TOKEN, rule_data(radius_km=1, self_only=True))
    near_self = make_station("A", 1600, is_self=True)
    near_full = make_station("B", 1600)
    far_self = make_station("C", 1600, lat=33.60, lng=126.60, is_self=True)
    assert [s.id for s in service.filter_candidates(rule, [near_self, near_full, far_self])] == ["A"]


def test_validation_requires_threshold_for_selected_type():
    with pytest.raises(ValueError):
        rule_data(alert_types=["drop"], target_price=None, drop_amount=None)
    with pytest.raises(ValueError):
        rule_data(radius_km=2)


def test_location_is_rounded_to_3_decimals(session):
    rule = service.create_alert(session, TOKEN, rule_data(lat=33.511349, lng=126.493049))
    assert (rule.lat, rule.lng) == (33.511, 126.493)


# ------------------------------------------------------------ check_alerts 흐름
def test_check_sends_and_records_event(session, settings):
    service.create_alert(session, TOKEN, rule_data(target_price=1600), now=NOW)
    notifier = ConsoleNotifier()
    report = run_check(session, settings, FakeFind([make_station("A", 1589, is_self=True)]), notifier)
    assert report.sent == 1
    ev = events(session)[0]
    assert ev.status == "sent" and ev.station_id == "A" and "1,589원/L (셀프)" in ev.message
    assert "[제주 주유 알림] 제주공항 3km 내 휘발유" in notifier.sent[0][1].body
    assert session.exec(select(PriceHistory)).all()  # 가격 이력 저장


def test_message_includes_yesterday_delta(session, settings):
    service.create_alert(session, TOKEN, rule_data(target_price=1600), now=NOW)
    session.add(PriceHistory(station_id="A", fuel_type="B027", price=1612, recorded_at=NOW - timedelta(hours=25)))
    session.commit()
    run_check(session, settings, FakeFind([make_station("A", 1589)]))
    assert "어제보다 -23원" in events(session)[0].message


def test_cooldown_blocks_duplicate_then_allows_after_window(session, settings):
    service.create_alert(session, TOKEN, rule_data(target_price=1600, cooldown_hours=6), now=NOW)
    find = FakeFind([make_station("A", 1589)])
    assert run_check(session, settings, find, now=NOW).sent == 1
    r2 = run_check(session, settings, find, now=NOW + timedelta(hours=2))
    assert r2.sent == 0 and r2.skipped_cooldown == 1
    assert run_check(session, settings, find, now=NOW + timedelta(hours=6, minutes=1)).sent == 1
    assert len(events(session)) == 2


def test_cooldown_is_per_station(session, settings):
    service.create_alert(session, TOKEN, rule_data(target_price=1600), now=NOW)
    run_check(session, settings, FakeFind([make_station("A", 1589)]), now=NOW)
    r = run_check(session, settings, FakeFind([make_station("A", 1595), make_station("B", 1590)]),
                  now=NOW + timedelta(hours=1))
    assert r.sent == 1 and events(session)[-1].station_id == "B"  # A 는 쿨다운, B 로 발송


def test_expired_rule_is_deactivated_and_subscription_removed(session, settings):
    yesterday = (NOW + timedelta(hours=9)).date() - timedelta(days=1)
    rule = service.create_alert(session, TOKEN, rule_data(rental_end=yesterday), now=NOW - timedelta(days=3))
    service.save_subscription(session, TOKEN, "https://push/x", "p", "a")
    notifier = ConsoleNotifier()
    report = run_check(session, settings, FakeFind([make_station("A", 1500)]), notifier)
    session.refresh(rule)
    assert report.expired == 1 and report.sent == 0 and notifier.sent == []
    assert rule.is_active is False
    assert session.exec(select(PushSubscription)).all() == []


def test_rule_valid_through_end_of_rental_day(session, settings):
    today_kst = (NOW + timedelta(hours=9)).date()
    rule = service.create_alert(session, TOKEN, rule_data(rental_end=today_kst), now=NOW - timedelta(days=1))
    assert service.expire_rules(session, NOW) == 0  # 종료일 당일 낮에는 유효
    assert service.expire_rules(session, NOW + timedelta(hours=13)) == 1  # KST 다음날 01시
    session.refresh(rule)
    assert rule.is_active is False


def test_subscription_kept_while_other_rule_active(session):
    yesterday = (NOW + timedelta(hours=9)).date() - timedelta(days=1)
    service.create_alert(session, TOKEN, rule_data(rental_end=yesterday), now=NOW - timedelta(days=3))
    service.create_alert(session, TOKEN, rule_data(), now=NOW)
    service.save_subscription(session, TOKEN, "https://push/x", "p", "a")
    service.expire_rules(session, NOW)
    assert len(session.exec(select(PushSubscription)).all()) == 1


def test_same_condition_rules_share_one_api_call(session, settings):
    for radius in (1, 3, 5):
        for t in (1500, 1600, 1700):
            service.create_alert(session, TOKEN, rule_data(radius_km=radius, target_price=t), now=NOW)
    find = FakeFind([make_station("A", 1589)])
    report = run_check(session, settings, find)
    assert len(find.calls) == 1 and report.api_calls == 1 and report.rules_checked == 9
    assert find.calls[0][2] == 5000  # 그룹 내 최대 반경으로 1회 조회

    service.create_alert(session, TOKEN, rule_data(lat=33.25, lng=126.56), now=NOW)  # 다른 위치
    service.create_alert(session, TOKEN, rule_data(fuel_type="D047"), now=NOW)  # 다른 유종
    find2 = FakeFind([make_station("A", 1589)])
    run_check(session, settings, find2)
    assert len(find2.calls) == 3


def test_batching_defers_groups_and_rotates(session, settings):
    for i in range(5):
        service.create_alert(session, TOKEN, rule_data(lat=33.40 + i * 0.01), now=NOW)
    find = FakeFind([])
    report = run_check(session, settings, find, batch_size=2)
    assert len(find.calls) == 2 and report.deferred_groups == 3
    run_check(session, settings, find, batch_size=2)
    assert len({c[0] for c in find.calls}) >= 3  # 다음 사이클은 이어서 다른 그룹을 처리


def test_detour_filter_excludes_far_stations(session, settings):
    origin, dest = (33.2541, 126.5601), AIRPORT
    service.create_alert(session, TOKEN, rule_data(
        lat=origin[0], lng=origin[1], radius_km=10, target_price=1700,
        return_lat=dest[0], return_lng=dest[1], exclude_far_detour=True, max_detour_minutes=10), now=NOW)
    on_route = make_station("ON", 1650, lat=33.30, lng=126.55)
    detour = make_station("OFF", 1500, lat=33.30, lng=126.64)  # 훨씬 싸지만 우회 큼
    find = FakeFind([on_route, detour])
    run_check(session, settings, find)
    assert [e.station_id for e in events(session)] == ["ON"]


def test_detour_filter_function():
    a, b = make_station("A", 1500), make_station("B", 1500)
    trips = {"A": Trip(extra_minutes=11, extra_km=5, leg_minutes=6),
             "B": Trip(extra_minutes=10, extra_km=5, leg_minutes=5)}
    assert [s.id for s in service.filter_by_detour([a, b], trips, 10)] == ["B"]


def test_disabled_rule_not_checked(session, settings):
    rule = service.create_alert(session, TOKEN, rule_data(), now=NOW)
    service.toggle_alert(session, TOKEN, rule.id, now=NOW)
    find = FakeFind([make_station("A", 1500)])
    assert run_check(session, settings, find).api_calls == 0 and find.calls == []


def test_return_summary_once_on_d1_and_d0(session, settings):
    kst_today = (NOW + timedelta(hours=9)).date()
    service.create_alert(session, TOKEN, rule_data(
        rental_end=kst_today + timedelta(days=1), return_lat=AIRPORT[0], return_lng=AIRPORT[1],
        return_label="제주공항"), now=NOW - timedelta(days=2))
    find = FakeFind([make_station(str(i), 1600 + i) for i in range(5)])
    notifier = ConsoleNotifier()

    def summaries(now):
        return asyncio.run(service.send_return_summaries(
            session, now=now, settings=settings, find_fn=find, notifier=notifier, retry_sleep=no_sleep))

    assert summaries(NOW - timedelta(hours=6)) == 0  # KST 06시: 아침 전
    assert summaries(NOW) == 1
    assert summaries(NOW) == 0  # D-1 은 1회만
    assert "D-1" in notifier.sent[0][1].body and "3)" in notifier.sent[0][1].body
    assert summaries(NOW + timedelta(days=1)) == 1  # D-day
    assert summaries(NOW + timedelta(days=1)) == 0


# ------------------------------------------------------------ 발송 재시도
def msg():
    return NotificationMessage(title="t", body="b")


def target():
    return NotificationTarget(device_token=TOKEN)


def test_retry_succeeds_on_third_attempt():
    n = ScriptedNotifier([TransientNotifierError("x"), TransientNotifierError("y"), None])
    res = asyncio.run(send_with_retry(n, target(), msg(), max_attempts=3, sleep=no_sleep))
    assert res.ok and res.attempts == 3 and n.calls == 3


def test_retry_gives_up_after_three_attempts():
    n = ScriptedNotifier([TransientNotifierError("x")] * 5)
    res = asyncio.run(send_with_retry(n, target(), msg(), max_attempts=3, sleep=no_sleep))
    assert not res.ok and not res.permanent and res.attempts == 3 and n.calls == 3


def test_permanent_failure_is_not_retried():
    n = ScriptedNotifier([PermanentNotifierError("만료")])
    res = asyncio.run(send_with_retry(n, target(), msg(), max_attempts=3, sleep=no_sleep))
    assert res.permanent and res.attempts == 1 and n.calls == 1


def test_permanent_failure_deletes_subscription_and_logs_failure(session, settings):
    service.create_alert(session, TOKEN, rule_data(), now=NOW)
    service.save_subscription(session, TOKEN, "https://push/x", "p", "a")
    notifier = ScriptedNotifier([PermanentNotifierError("구독 만료")])
    report = run_check(session, settings, FakeFind([make_station("A", 1500)]), notifier)
    assert report.failed == 1 and notifier.calls == 1
    assert session.exec(select(PushSubscription)).all() == []
    assert events(session)[0].status == "failed"


def test_failed_send_does_not_start_cooldown(session, settings):
    service.create_alert(session, TOKEN, rule_data(), now=NOW)
    find = FakeFind([make_station("A", 1500)])
    n = ScriptedNotifier([TransientNotifierError("net")] * 3)
    assert run_check(session, settings, find, n).failed == 1
    assert run_check(session, settings, find, ScriptedNotifier(), now=NOW + timedelta(minutes=20)).sent == 1


def test_message_format():
    text = format_price_alert(label="제주공항", radius_km=3, fuel_name="휘발유", price=1589, is_self=True,
                              delta_vs_yesterday=-23, travel_minutes=6)
    assert text == "[제주 주유 알림] 제주공항 3km 내 휘발유 1,589원/L (셀프) · 어제보다 -23원 · 이동 6분 · 지도 보기"


def test_other_device_cannot_access_rule(session):
    rule = service.create_alert(session, TOKEN, rule_data(), now=NOW)
    with pytest.raises(service.AlertNotFound):
        service.get_alert(session, "another-device-token-9", rule.id)
