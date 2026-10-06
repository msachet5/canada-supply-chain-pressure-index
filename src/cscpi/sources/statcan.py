"""Statistics Canada Web Data Service (WDS) client.

Uses two public endpoints:
  POST /t1/wds/rest/getCubeMetadata                 table metadata (release time, end date, status)
  GET  /t1/wds/rest/getFullTableDownloadCSV/{pid}/en  URL of the full-table CSV zip

Full tables are cached on disk, so filters can be changed without re-downloading.
Data is published under the Statistics Canada Open Licence.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import requests

WDS = "https://www150.statcan.gc.ca/t1/wds/rest"
CACHE = Path.home() / ".cache" / "cscpi" / "statcan"
META_COLS = {
    "REF_DATE", "GEO", "DGUID", "UOM", "UOM_ID", "SCALAR_FACTOR", "SCALAR_ID", "VECTOR",
    "COORDINATE", "VALUE", "STATUS", "SYMBOL", "TERMINATED", "DECIMALS",
}


def product_id(table: str) -> int:
    """'16-10-0047-01' -> 16100047 (the WDS product id is the first eight digits)."""
    digits = table.replace("-", "")
    if len(digits) < 8 or not digits.isdigit():
        raise ValueError(f"not a StatCan table id: {table}")
    return int(digits[:8])


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "cscpi/0.1 (+https://github.com/msachet5/canada-supply-chain-pressure-index)"
    return s


def cube_metadata(table: str, session: requests.Session | None = None) -> dict[str, Any]:
    """Table metadata: title, start and end reference dates, release time, archive status, frequency."""
    s = session or _session()
    r = s.post(f"{WDS}/getCubeMetadata", json=[{"productId": product_id(table)}], timeout=60)
    r.raise_for_status()
    payload = r.json()
    item = payload[0] if isinstance(payload, list) else payload
    if item.get("status") != "SUCCESS":
        raise RuntimeError(f"WDS metadata failed for {table}: {item}")
    obj = item["object"]
    return {
        "table": table,
        "title": obj.get("cubeTitleEn"),
        "start": obj.get("cubeStartDate"),
        "end": obj.get("cubeEndDate"),
        "released": obj.get("releaseTime"),
        "archived": str(obj.get("archiveStatusCode")) == "1" or "archived" in str(obj.get("archiveStatusEn", "")).lower(),
        "archive_status": obj.get("archiveStatusEn"),
        "frequency_code": obj.get("frequencyCode"),
        "dimensions": [
            {
                "name": d.get("dimensionNameEn"),
                "members": [m.get("memberNameEn") for m in d.get("member", [])],
            }
            for d in obj.get("dimension", [])
        ],
    }


def full_table(table: str, refresh: bool = False, session: requests.Session | None = None) -> pl.DataFrame:
    """Download (or load from cache) the full table as a polars DataFrame of strings."""
    pid = product_id(table)
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{pid}.parquet"
    if cached.exists() and not refresh and (time.time() - cached.stat().st_mtime) < 6 * 3600:
        return pl.read_parquet(cached)
    s = session or _session()
    r = s.get(f"{WDS}/getFullTableDownloadCSV/{pid}/en", timeout=60)
    r.raise_for_status()
    url = r.json()["object"]
    z = s.get(url, timeout=600)
    z.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".csv") and "MetaData" not in n)
        df = parse_csv(zf.read(name))
    df.write_parquet(cached)
    return df


def parse_csv(raw: bytes) -> pl.DataFrame:
    """Parse a StatCan full-table CSV (UTF-8 with BOM) keeping every column as text."""
    text = raw.decode("utf-8-sig")
    return pl.read_csv(io.StringIO(text), infer_schema=False)


def dimension_columns(df: pl.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in META_COLS]


def select_series(df: pl.DataFrame, filters: dict[str, str]) -> pl.DataFrame:
    """Filter a full table down to one series. Raises with the available members on a mismatch."""
    out = df
    for col, member in filters.items():
        if col not in out.columns:
            raise KeyError(f"column '{col}' not in table. Dimensions: {dimension_columns(df)}")
        hit = out.filter(pl.col(col) == member)
        if hit.is_empty():
            options = sorted(out[col].unique().to_list())
            raise KeyError(f"member '{member}' not found in '{col}'. Available: {options[:40]}")
        out = hit
    vectors = out["VECTOR"].unique().to_list() if "VECTOR" in out.columns else []
    if len(vectors) > 1:
        free = [c for c in dimension_columns(out) if out[c].n_unique() > 1 and c != "REF_DATE"]
        detail = {c: sorted(out[c].unique().to_list())[:15] for c in free}
        raise ValueError(f"filters match {len(vectors)} series; add filters for: {json.dumps(detail)[:1500]}")
    return out


def to_monthly(df: pl.DataFrame) -> pl.DataFrame:
    """REF_DATE + VALUE -> month, value. Weekly and daily data are averaged per month."""
    data = df.select("REF_DATE", "VALUE").filter(pl.col("VALUE").is_not_null() & (pl.col("VALUE") != ""))
    data = data.with_columns(
        pl.col("VALUE").cast(pl.Float64, strict=False).alias("value"),
        pl.col("REF_DATE").str.slice(0, 7).alias("_ym"),
    )
    data = data.with_columns((pl.col("_ym") + "-01").str.to_date().alias("month"))
    return data.group_by("month").agg(pl.col("value").mean()).drop_nulls().sort("month")


def fetch(table: str, filters: dict[str, str], refresh: bool = False) -> pl.DataFrame:
    return to_monthly(select_series(full_table(table, refresh=refresh), filters))


def last_month(df: pl.DataFrame) -> date | None:
    return df["month"].max() if df.height else None
