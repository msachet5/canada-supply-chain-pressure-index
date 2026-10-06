import polars as pl
import pytest

from cscpi.sources import statcan

CSV = (
    "﻿REF_DATE,GEO,DGUID,Principal statistics,Seasonal adjustment,UOM,UOM_ID,SCALAR_FACTOR,SCALAR_ID,VECTOR,COORDINATE,VALUE,STATUS,SYMBOL,TERMINATED,DECIMALS\n"
    "2024-01,Canada,x,Unfilled orders to sales ratio,Seasonally adjusted,Ratio,1,units,0,v1,1.1.1,1.50,,,,2\n"
    "2024-02,Canada,x,Unfilled orders to sales ratio,Seasonally adjusted,Ratio,1,units,0,v1,1.1.1,1.60,,,,2\n"
    "2024-01,Canada,x,New orders,Seasonally adjusted,Dollars,1,thousands,3,v2,1.2.1,100,,,,0\n"
    "2024-02,Canada,x,New orders,Seasonally adjusted,Dollars,1,thousands,3,v2,1.2.1,,..,,,0\n"
)


def test_product_id():
    assert statcan.product_id("16-10-0047-01") == 16100047
    with pytest.raises(ValueError):
        statcan.product_id("abc")


def test_parse_select_monthly():
    df = statcan.parse_csv(CSV.encode("utf-8"))
    assert "REF_DATE" in df.columns  # BOM stripped
    s = statcan.select_series(df, {"GEO": "Canada", "Principal statistics": "Unfilled orders to sales ratio"})
    m = statcan.to_monthly(s)
    assert m["value"].to_list() == [1.5, 1.6]
    assert str(m["month"][0]) == "2024-01-01"


def test_missing_values_dropped():
    df = statcan.parse_csv(CSV.encode())
    m = statcan.to_monthly(statcan.select_series(df, {"Principal statistics": "New orders"}))
    assert m.height == 1


def test_member_mismatch_lists_options():
    df = statcan.parse_csv(CSV.encode())
    with pytest.raises(KeyError, match="Available"):
        statcan.select_series(df, {"Principal statistics": "Backlog"})


def test_ambiguous_filter():
    df = statcan.parse_csv(CSV.encode())
    with pytest.raises(ValueError, match="2 series"):
        statcan.select_series(df, {"GEO": "Canada"})


def test_weekly_averaged_to_month():
    df = pl.DataFrame({"REF_DATE": ["2024-01-07", "2024-01-14", "2024-02-04"], "VALUE": ["2", "4", "5"]})
    m = statcan.to_monthly(df)
    assert m["value"].to_list() == [3.0, 5.0]
