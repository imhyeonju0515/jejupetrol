"""외부 API 호출 공통 헬퍼 (타임아웃/오류를 한국어 UpstreamError로 변환)."""
from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from stations.schemas import UpstreamError


async def fetch_json(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    client: Optional[httpx.AsyncClient] = None,
    timeout: float = 5.0,
    service: str = "외부 서비스",
) -> Any:
    """GET 요청 후 JSON을 반환한다. 실패 시 UpstreamError(한국어)."""
    try:
        if client is not None:
            resp = await client.get(url, params=params, headers=headers, timeout=timeout)
        else:
            async with httpx.AsyncClient(timeout=timeout) as c:
                resp = await c.get(url, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise UpstreamError(f"{service} 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamError(f"{service}에 연결하지 못했습니다. 네트워크를 확인해 주세요.") from exc

    if resp.status_code >= 400:
        raise UpstreamError(f"{service} 요청이 실패했습니다. (HTTP {resp.status_code})")
    try:
        return resp.json()
    except ValueError as exc:
        raise UpstreamError(f"{service}에서 올바르지 않은 응답을 받았습니다.") from exc
