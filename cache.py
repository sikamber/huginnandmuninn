from dataclasses import dataclass, field
from datetime import date, datetime

DAILY_MODES = {"radar"}


@dataclass
class ResponseCache:
    _responses: dict[str, str] = field(default_factory=dict)
    _generated_at: dict[str, datetime] = field(default_factory=dict)
    _last_modified: datetime = field(default_factory=datetime.now)

    def get(self, mode: str) -> str | None:
        if mode not in self._responses:
            return None
        generated = self._generated_at[mode]
        if mode in DAILY_MODES:
            if generated.date() < date.today():
                return None
        else:
            if generated < self._last_modified:
                return None
        return self._responses[mode]

    def set(self, mode: str, response: str) -> None:
        self._responses[mode] = response
        self._generated_at[mode] = datetime.now()

    def invalidate(self) -> None:
        self._last_modified = datetime.now()


response_cache = ResponseCache()
