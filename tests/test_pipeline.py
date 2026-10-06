from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from cscpi.config import load_config
from cscpi.pipeline import audit, build
from cscpi.publish import write_outputs

ROOT = Path(__file__).resolve().parents[1]


def fake_fetcher(stale: set[str] = frozenset()):
    rng = np.random.default_rng(5)
    n = 110
    f = np.cumsum(rng.normal(size=n)) * 0.3
    months = pl.date_range(date(2016, 1, 1), date(2025, 2, 1), "1mo", eager=True)[:n]

    def fetch(spec):
        if spec.id in stale:
            m = months[:60]
            return pl.DataFrame({"month": m, "value": rng.normal(size=60) + 100})
        base = 100 + (5 * f if spec.role == "supply" else 0) + rng.normal(size=n)
        return pl.DataFrame({"month": months, "value": base})

    return fetch


def test_config_loads():
    cfg = load_config(ROOT / "series.yaml")
    assert len(cfg.by_role("supply")) >= 6
    assert cfg.settings.reference_series == "msm_unfilled_orders_ratio"


def test_audit_gate_and_build(tmp_path):
    cfg = load_config(ROOT / "series.yaml")
    today = date(2025, 3, 15)
    rows, gate = audit(cfg, today=today, fetcher=fake_fetcher())
    assert gate["mode"] == "composite"
    mode, res, pulse_df, rows = build(cfg, fetcher=fake_fetcher(), today=today)
    assert mode == "composite" and res is not None and pulse_df is None
    names = {s.id: s.name for s in cfg.series}
    paths = write_outputs(mode, res, None, rows, names, out_dir=tmp_path, vintage="2025-03")
    assert (tmp_path / "cscpi.csv").exists() and (tmp_path / "releases" / "cscpi_2025-03.csv").exists()
    assert "standard deviations" in (tmp_path / "releases" / "notes_2025-03.md").read_text()
    assert "chart" in paths


def test_gate_falls_back_to_pulse(tmp_path):
    cfg = load_config(ROOT / "series.yaml")
    supply = [s.id for s in cfg.by_role("supply")]
    stale = set(supply[: len(supply) - 3])
    mode, res, pulse_df, rows = build(cfg, fetcher=fake_fetcher(stale), today=date(2025, 3, 15))
    assert mode == "pulse" and res is None and pulse_df is not None
    write_outputs(mode, None, pulse_df, rows, {}, out_dir=tmp_path, vintage="2025-03")
    assert "pulse" in (tmp_path / "cscpi.json").read_text()


def test_failed_series_reported():
    cfg = load_config(ROOT / "series.yaml")

    def broken(spec):
        raise KeyError("member 'x' not found")

    rows, gate = audit(cfg, today=date(2025, 3, 1), fetcher=broken)
    assert all(not r.ok for r in rows) and gate["mode"] == "pulse"
