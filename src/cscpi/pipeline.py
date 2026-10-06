"""Fetch, audit and build."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

import polars as pl

from .config import Config, SeriesSpec
from .model import IndexResult, build_index, pulse, transform
from .sources import fred, nyfed, statcan


def fetch_series(spec: SeriesSpec, refresh: bool = False) -> pl.DataFrame:
    if spec.source == "statcan":
        if not spec.table:
            raise ValueError(f"{spec.id}: statcan series need a table id")
        return statcan.fetch(spec.table, spec.filters, refresh=refresh)
    if spec.source == "nyfed":
        return nyfed.fetch()
    if spec.source == "fred":
        if not spec.table:
            raise ValueError(f"{spec.id}: fred series need table: <FRED series id>")
        return fred.fetch(spec.table)
    raise ValueError(f"{spec.id}: unknown source {spec.source}")


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


@dataclass
class AuditRow:
    id: str
    role: str
    table: str | None
    status: str
    ok: bool
    first: date | None = None
    last: date | None = None
    staleness_months: int | None = None
    current: bool = False
    observations: int = 0
    message: str = ""


def audit(cfg: Config, today: date | None = None, fetcher: Callable[[SeriesSpec], pl.DataFrame] | None = None) -> tuple[list[AuditRow], dict]:
    """Check every series: does the filter resolve, how recent is it, is it current."""
    today = today or date.today()
    fetcher = fetcher or fetch_series
    rows: list[AuditRow] = []
    for spec in cfg.series:
        try:
            df = fetcher(spec)
            first, last = df["month"].min(), df["month"].max()
            stale = months_between(last, today) if last else None
            current = stale is not None and stale <= cfg.settings.max_staleness_months
            rows.append(AuditRow(spec.id, spec.role, spec.table, spec.status, True, first, last, stale, current, df.height))
        except Exception as exc:  # noqa: BLE001 - report every failure, keep auditing
            rows.append(AuditRow(spec.id, spec.role, spec.table, spec.status, False, message=f"{type(exc).__name__}: {exc}"[:600]))
    n_current_supply = sum(r.current for r in rows if r.role == "supply")
    gate = {
        "current_supply_series": n_current_supply,
        "required": cfg.settings.min_current_series,
        "mode": "composite" if n_current_supply >= cfg.settings.min_current_series else "pulse",
    }
    return rows, gate


def build(cfg: Config, refresh: bool = False, fetcher: Callable[[SeriesSpec], pl.DataFrame] | None = None,
          today: date | None = None) -> tuple[str, IndexResult | None, pl.DataFrame | None, list[AuditRow]]:
    """Build the composite when the gate passes, otherwise the indicator pulse."""
    fetcher = fetcher or (lambda s: fetch_series(s, refresh=refresh))
    rows, gate = audit(cfg, today=today, fetcher=fetcher)
    usable = {r.id for r in rows if r.ok and r.current}
    supply = {s.id: transform(fetcher(s), s.transform) for s in cfg.by_role("supply") if s.id in usable}
    demand = {s.id: transform(fetcher(s), s.transform) for s in cfg.by_role("demand") if s.id in usable}
    signs = {s.id: s.sign for s in cfg.series}
    if gate["mode"] == "composite":
        result = build_index(supply, demand, signs, start=cfg.settings.start, reference=cfg.settings.reference_series)
        return "composite", result, None, rows
    return "pulse", None, pulse(supply, signs, start=cfg.settings.start), rows
