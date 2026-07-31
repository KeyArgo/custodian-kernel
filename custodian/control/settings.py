"""Operator-owned preferences shared by every Custodian harness adapter."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class ControlSettings:
    enforcement: str = "open"
    visibility: str = "verbose"
    harness_enforcement: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.enforcement not in {"protected", "open", "developer-open"}:
            raise ValueError("enforcement must be protected or open")
        if self.visibility not in {"verbose", "quiet"}:
            raise ValueError("visibility must be verbose or quiet")
        if any(
            not isinstance(harness, str)
            or not harness
            or mode not in {"protected", "open"}
            for harness, mode in self.harness_enforcement.items()
        ):
            raise ValueError("harness enforcement must map harness names to protected or open")

    def enforcement_for(self, harness: str) -> str:
        return self.harness_enforcement.get(harness, self.enforcement)


class ControlSettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> ControlSettings:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError
            settings = ControlSettings(**value)
            if settings.enforcement == "developer-open":
                return ControlSettings(
                    enforcement="open", visibility=settings.visibility,
                    harness_enforcement=settings.harness_enforcement,
                )
            return settings
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return ControlSettings()

    def save(self, settings: ControlSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(asdict(settings), stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)
