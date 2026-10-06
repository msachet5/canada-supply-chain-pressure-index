"""cscpi command line."""

from __future__ import annotations

import argparse
import json
import sys

import polars as pl

from .config import load_config
from .pipeline import audit, build, fetch_series
from .publish import write_outputs
from .sources import statcan


def cmd_audit(a: argparse.Namespace) -> int:
    cfg = load_config(a.config)
    rows, gate = audit(cfg)
    with pl.Config(tbl_rows=50, tbl_width_chars=200, fmt_str_lengths=80):
        print(pl.DataFrame([{k: v for k, v in r.__dict__.items() if k != "message"} for r in rows]))
    for r in rows:
        if not r.ok:
            print(f"\n[{r.id}] {r.message}")
    print(f"\nGate: {gate['current_supply_series']} current supply series, {gate['required']} required -> {gate['mode'].upper()}")
    return 0


def cmd_members(a: argparse.Namespace) -> int:
    """Print the dimensions and members of a StatCan table, to write filters."""
    meta = statcan.cube_metadata(a.table)
    print(f"{meta['title']} | {meta['start']} to {meta['end']} | released {meta['released']} | {meta['archive_status']}")
    for d in meta["dimensions"]:
        print(f"\n{d['name']}:")
        for m in d["members"][: a.limit]:
            print(f"  - {m}")
    return 0


def cmd_build(a: argparse.Namespace) -> int:
    cfg = load_config(a.config)
    mode, result, pulse_df, rows = build(cfg, refresh=a.refresh)
    names = {s.id: s.name for s in cfg.series}
    paths = write_outputs(mode, result, pulse_df, rows, names, out_dir=a.out, vintage=a.vintage)
    print(f"mode: {mode}")
    if result is not None:
        print(result.to_frame().select("month", "cscpi", "series_available").tail(12))
        print("loadings:", json.dumps({k: round(v, 3) for k, v in result.loadings.items()}))
        print(f"variance explained by the first component: {result.explained:.0%}")
    for k, p in paths.items():
        print(f"{k}: {p}")
    return 0


def cmd_validate(a: argparse.Namespace) -> int:
    """Correlate the published index with the NY Fed GSCPI."""
    cfg = load_config(a.config)
    ours = pl.read_csv(f"{a.out}/cscpi.csv", try_parse_dates=True)
    col = "cscpi" if "cscpi" in ours.columns else "pulse"
    g = fetch_series(cfg.get("gscpi"))
    j = ours.select("month", col).join(g.rename({"value": "gscpi"}), on="month", how="inner")
    for lag in (0, 1, 3, 6):
        jj = ours.select("month", col).join(
            g.with_columns(pl.col("month").dt.offset_by(f"{lag}mo")).rename({"value": "gscpi"}), on="month", how="inner"
        )
        print(f"corr(CSCPI_t, GSCPI_t-{lag}) = {jj.select(pl.corr(col, 'gscpi')).item():.2f}  (n={jj.height})")
    print(f"overlap: {j['month'].min()} to {j['month'].max()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cscpi", description="Canada Supply Chain Pressure Index")
    p.add_argument("--config", default="series.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("audit", help="check every input: resolves, how recent, gate decision")
    s.set_defaults(func=cmd_audit)
    s = sub.add_parser("members", help="list a StatCan table's dimensions and members")
    s.add_argument("table")
    s.add_argument("--limit", type=int, default=60)
    s.set_defaults(func=cmd_members)
    s = sub.add_parser("build", help="build the index and write data/")
    s.add_argument("--out", default="data")
    s.add_argument("--vintage")
    s.add_argument("--refresh", action="store_true")
    s.set_defaults(func=cmd_build)
    s = sub.add_parser("validate", help="correlate with the NY Fed GSCPI")
    s.add_argument("--out", default="data")
    s.set_defaults(func=cmd_validate)
    a = p.parse_args(argv)
    return int(a.func(a) or 0)


if __name__ == "__main__":
    sys.exit(main())
