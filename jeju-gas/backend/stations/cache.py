"""간단한 TTL 메모리 캐시."""
from __future__ import annotations

import time
from typing import Callable, Dict, Generic, Hashable, Optional, Tuple, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class TTLCache(Generic[K, V]):
    """만료 시간이 있는 메모리 캐시. clock을 주입해 테스트할 수 있다."""

    def __init__(
        self,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_size: int = 4096,
    ) -> None:
        self.ttl = ttl_seconds
        self._clock = clock
        self._max = max_size
        self._data: Dict[K, Tuple[float, V]] = {}

    def get(self, key: K) -> Optional[V]:
        """만료되지 않은 값을 반환하고, 없거나 만료되면 None."""
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if self._clock() >= expires:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: K, value: V) -> None:
        """값을 저장한다. 크기 초과 시 만료/오래된 항목부터 정리."""
        if len(self._data) >= self._max:
            now = self._clock()
            for k in [k for k, (exp, _) in self._data.items() if exp <= now]:
                self._data.pop(k, None)
            while len(self._data) >= self._max:
                self._data.pop(next(iter(self._data)))
        self._data[key] = (self._clock() + self.ttl, value)

    def clear(self) -> None:
        """전체 삭제."""
        self._data.clear()
