"""알림 발송 채널. Notifier 를 상속해 채널(카카오 알림톡 등)을 쉽게 추가할 수 있다."""
from __future__ import annotations

import asyncio
import json
import logging
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Awaitable, Callable, List, Optional

from config import Settings, get_settings

logger = logging.getLogger(__name__)


class NotifierError(Exception):
    """발송 실패 공통 부모."""


class TransientNotifierError(NotifierError):
    """일시적 실패 (네트워크 등) — 재시도 대상."""


class PermanentNotifierError(NotifierError):
    """영구 실패 (구독 만료 등) — 재시도 없이 구독 삭제."""


@dataclass
class NotificationMessage:
    title: str
    body: str
    url: str = "/"  # 클릭 시 이동 경로
    tag: str = ""


@dataclass
class NotificationTarget:
    """수신자 정보. 채널별로 필요한 값만 채워진다."""

    device_token: str
    push_subscription: Optional[dict] = None  # {endpoint, keys:{p256dh,auth}}
    email: Optional[str] = None


@dataclass
class SendResult:
    ok: bool
    attempts: int
    permanent: bool = False
    error: Optional[str] = None


class Notifier(ABC):
    """알림 채널 인터페이스."""

    name = "base"

    def supports(self, target: NotificationTarget) -> bool:
        """이 채널로 target 에게 보낼 수 있는지."""
        return True

    @abstractmethod
    async def send(self, target: NotificationTarget, message: NotificationMessage) -> None:
        """발송한다. 실패 시 Transient/PermanentNotifierError 를 던진다."""


class ConsoleNotifier(Notifier):
    """MOCK 모드용: 로그/콘솔에 출력만 한다. sent 에 이력도 남긴다(테스트 확인용)."""

    name = "console"

    def __init__(self) -> None:
        self.sent: List[tuple] = []

    async def send(self, target: NotificationTarget, message: NotificationMessage) -> None:
        self.sent.append((target.device_token, message))
        line = f"[MOCK 알림] ({target.device_token[:8]}…) {message.title} | {message.body} -> {message.url}"
        logger.info(line)
        print(line, flush=True)


class WebPushNotifier(Notifier):
    """VAPID 웹 푸시. 404/410 은 구독 만료(영구 실패)로 본다."""

    name = "webpush"

    def __init__(self, private_key: str, subject: str) -> None:
        self.private_key = private_key
        self.subject = subject

    def supports(self, target: NotificationTarget) -> bool:
        return bool(target.push_subscription)

    async def send(self, target: NotificationTarget, message: NotificationMessage) -> None:
        if not target.push_subscription:
            raise PermanentNotifierError("푸시 구독 정보가 없습니다.")
        payload = json.dumps(
            {"title": message.title, "body": message.body, "url": message.url, "tag": message.tag},
            ensure_ascii=False,
        )
        await asyncio.to_thread(self._send_sync, target.push_subscription, payload)

    def _send_sync(self, subscription: dict, payload: str) -> None:
        from pywebpush import WebPushException, webpush  # 지연 import

        try:
            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=self.private_key,
                vapid_claims={"sub": self.subject},
                timeout=10,
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                raise PermanentNotifierError("푸시 구독이 만료되었습니다.") from exc
            raise TransientNotifierError(f"푸시 발송 실패 (HTTP {status})") from exc
        except Exception as exc:  # 네트워크 등
            raise TransientNotifierError(f"푸시 발송 중 오류: {exc}") from exc


class EmailNotifier(Notifier):
    """SMTP 이메일 (선택)."""

    name = "email"

    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def supports(self, target: NotificationTarget) -> bool:
        return bool(target.email and self.s.smtp_host)

    async def send(self, target: NotificationTarget, message: NotificationMessage) -> None:
        if not target.email:
            raise PermanentNotifierError("이메일 주소가 없습니다.")
        await asyncio.to_thread(self._send_sync, target.email, message)

    def _send_sync(self, to: str, message: NotificationMessage) -> None:
        msg = EmailMessage()
        msg["Subject"] = message.title
        msg["From"] = self.s.smtp_from or self.s.smtp_user
        msg["To"] = to
        msg.set_content(f"{message.body}\n\n{message.url}")
        try:
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=10) as smtp:
                if self.s.smtp_use_tls:
                    smtp.starttls()
                if self.s.smtp_user:
                    smtp.login(self.s.smtp_user, self.s.smtp_password)
                smtp.send_message(msg)
        except smtplib.SMTPRecipientsRefused as exc:
            raise PermanentNotifierError("수신 이메일 주소가 거부되었습니다.") from exc
        except Exception as exc:
            raise TransientNotifierError(f"이메일 발송 실패: {exc}") from exc


class MultiNotifier(Notifier):
    """여러 채널을 묶는다. 하나라도 성공하면 성공."""

    name = "multi"

    def __init__(self, notifiers: List[Notifier]) -> None:
        self.notifiers = notifiers

    def supports(self, target: NotificationTarget) -> bool:
        return any(n.supports(target) for n in self.notifiers)

    async def send(self, target: NotificationTarget, message: NotificationMessage) -> None:
        usable = [n for n in self.notifiers if n.supports(target)]
        if not usable:
            raise PermanentNotifierError("알림을 받을 수 있는 채널(푸시 구독/이메일)이 없습니다.")
        errors: List[NotifierError] = []
        for n in usable:
            try:
                await n.send(target, message)
                return
            except NotifierError as exc:
                errors.append(exc)
        if all(isinstance(e, PermanentNotifierError) for e in errors):
            raise PermanentNotifierError(str(errors[0]))
        raise TransientNotifierError("; ".join(str(e) for e in errors))


def build_notifier(settings: Optional[Settings] = None) -> Notifier:
    """설정에 맞는 Notifier 를 만든다. MOCK 이면 ConsoleNotifier."""
    settings = settings or get_settings()
    if settings.mock:
        return ConsoleNotifier()
    channels: List[Notifier] = []
    if settings.vapid_private_key:
        channels.append(WebPushNotifier(settings.vapid_private_key, settings.vapid_subject))
    if settings.smtp_host:
        channels.append(EmailNotifier(settings))
    if not channels:
        logger.warning("발송 채널이 설정되지 않아 콘솔 출력만 합니다 (VAPID/SMTP 확인).")
        return ConsoleNotifier()
    return MultiNotifier(channels)


async def send_with_retry(
    notifier: Notifier,
    target: NotificationTarget,
    message: NotificationMessage,
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> SendResult:
    """최대 max_attempts 회 시도. 영구 실패는 즉시 중단(permanent=True)."""
    last: Optional[str] = None
    for attempt in range(1, max_attempts + 1):
        try:
            await notifier.send(target, message)
            return SendResult(ok=True, attempts=attempt)
        except PermanentNotifierError as exc:
            return SendResult(ok=False, attempts=attempt, permanent=True, error=str(exc))
        except Exception as exc:  # TransientNotifierError 및 예상 밖 오류
            last = str(exc)
            logger.warning("알림 발송 실패 (%d/%d): %s", attempt, max_attempts, last)
            if attempt < max_attempts:
                await sleep(backoff_seconds * attempt)
    return SendResult(ok=False, attempts=max_attempts, error=last or "알림 발송에 실패했습니다.")


def format_price_alert(
    *,
    label: str,
    radius_km: int,
    fuel_name: str,
    price: int,
    is_self: bool,
    delta_vs_yesterday: Optional[int],
    travel_minutes: Optional[float],
) -> str:
    """예) [제주 주유 알림] 제주공항 3km 내 휘발유 1,589원/L (셀프) · 어제보다 -23원 · 이동 6분 · 지도 보기"""
    parts = [f"[제주 주유 알림] {label or '내 위치'} {radius_km}km 내 {fuel_name} {price:,}원/L"
             + (" (셀프)" if is_self else "")]
    if delta_vs_yesterday is not None:
        parts.append(f"어제보다 {delta_vs_yesterday:+,}원")
    if travel_minutes is not None:
        parts.append(f"이동 {round(travel_minutes)}분")
    parts.append("지도 보기")
    return " · ".join(parts)
