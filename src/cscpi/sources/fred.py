"""FRED (St. Louis Fed) series via the public graph CSV endpoint. Optional source."""

from __future__ import annotations

import io

import polars as pl
import requests


def fetch(series_id: str) -> pl.DataFrame:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, timeout=60, headers={"User-Agent": "cscpi/0.1"})
    r.raise_for_status()
    df = pl.read_csv(io.BytesIO(r.content), infer_schema=False)
    date_col, val_col = df.columns[0], df.columns[1]
    return (
        df.with_columns(
            pl.col(date_col).str.slice(0, 7).add("-01").str.to_date().alias("month"),
            pl.col(val_col).cast(pl.Float64, strict=False).alias("value"),
        )
        .group_by("month")
        .agg(pl.col("value").mean())
        .drop_nulls()
        .sort("month")
    )
