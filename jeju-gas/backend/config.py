"""환경변수(.env) 기반 설정. 모든 키/비밀값은 여기서만 읽는다."""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """애플리케이션 설정. 환경변수 이름은 필드명의 대문자 형태(MOCK, OPINET_API_KEY ...)."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # 동작 모드
    mock: bool = False

    # 외부 API
    opinet_api_key: str = ""
    opinet_base_url: str = "https://www.opinet.co.kr/api"
    kakao_rest_api_key: str = ""
    kakao_directions_url: str = "https://apis-navi.kakaomobility.com/v1/directions"
    http_timeout_seconds: float = 5.0

    # 저장소 / 서버
    database_url: str = "sqlite:///./jeju_gas.db"
    cors_origins: str = "http://localhost:5173"
    frontend_dist: str = "../frontend/dist"

    # 캐시
    price_cache_ttl_seconds: int = 420  # 7분
    travel_cache_ttl_seconds: int = 600

    # 스케줄러 / 알림
    scheduler_enabled: bool = True
    alert_check_interval_minutes: int = 20
    alert_batch_size: int = 50
    alert_batch_delay_seconds: float = 0.3
    alert_default_cooldown_hours: int = 6
    notify_max_attempts: int = 3

    # 웹 푸시 (VAPID)
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    # 이메일 (선택)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    @property
    def cors_origin_list(self) -> List[str]:
        """쉼표로 구분된 CORS 허용 오리진 목록."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """프로세스 전역 설정 인스턴스를 반환한다."""
    return Settings()
