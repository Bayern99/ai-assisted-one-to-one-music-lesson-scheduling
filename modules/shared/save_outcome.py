from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SessionRevision:
    source: Optional[str]
    mtime_ns: Optional[int]

    @property
    def mtime(self):
        return None if self.mtime_ns is None else self.mtime_ns / 1_000_000_000


@dataclass(frozen=True)
class SaveOutcome:
    status: str
    path: str
    warning: str = ""
    mtime: float = None
    revision: SessionRevision = None

    def to_dict(self):
        return {
            "status": self.status,
            "path": self.path,
            "warning": self.warning,
        }
