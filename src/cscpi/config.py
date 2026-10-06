"""Series configuration (series.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

VALID_ROLES = {"supply", "demand", "benchmark"}
VALID_TRANSFORMS = {"level", "yoy", "diff", "log_yoy"}


@dataclass
class SeriesSpec:
    id: str
    name: str
    source: str
    role: str
    transform: str = "level"
    sign: int = 1
    table: str | None = None
    filters: dict[str, str] = field(default_factory=dict)
    status: str = "verify"
    why: str = ""
    purge: bool = True

    def __post_init__(self) -> None:
        if self.role not in VALID_ROLES:
            raise ValueError(f"{self.id}: role must be one of {VALID_ROLES}")
        if self.transform not in VALID_TRANSFORMS:
            raise ValueError(f"{self.id}: transform must be one of {VALID_TRANSFORMS}")
        if self.sign not in (1, -1):
            raise ValueError(f"{self.id}: sign must be 1 or -1")


@dataclass
class Settings:
    start: str = "2017-01"
    min_current_series: int = 6
    max_staleness_months: int = 4
    reference_series: str | None = None


@dataclass
class Config:
    settings: Settings
    series: list[SeriesSpec]

    def by_role(self, role: str) -> list[SeriesSpec]:
        return [s for s in self.series if s.role == role]

    def get(self, series_id: str) -> SeriesSpec:
        for s in self.series:
            if s.id == series_id:
                return s
        raise KeyError(series_id)


def load_config(path: str | Path = "series.yaml") -> Config:
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text())
    settings = Settings(**(raw.get("settings") or {}))
    specs = [SeriesSpec(**{k: v for k, v in s.items()}) for s in raw["series"]]
    ids = [s.id for s in specs]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate series ids: {dupes}")
    return Config(settings=settings, series=specs)
