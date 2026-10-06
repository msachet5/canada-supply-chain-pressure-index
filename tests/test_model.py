from datetime import date

import numpy as np
import polars as pl
import pytest

from cscpi.model import build_index, first_component, pulse, purge_demand, transform


def monthly(values, start=date(2017, 1, 1)):
    months = pl.date_range(start, date(2100, 1, 1), "1mo", eager=True)[: len(values)]
    return pl.DataFrame({"month": months, "value": values}).drop_nulls()


def synthetic(n=96, seed=0):
    rng = np.random.default_rng(seed)
    f = np.zeros(n)
    for t in range(1, n):
        f[t] = 0.85 * f[t - 1] + rng.normal()
    d = rng.normal(size=n)  # demand proxy, independent of the supply factor
    supply = {}
    for j, load in enumerate([1.0, 0.8, 0.9, 0.7, 1.1, 0.6]):
        y = load * f + 0.6 * d + rng.normal(scale=0.5, size=n)
        y = y.astype(float)
        if j == 5:
            y[:24] = np.nan  # starts later
        if j == 4:
            y[-2:] = np.nan  # publishes later
        supply[f"s{j}"] = monthly(list(np.where(np.isnan(y), None, y)))
    return f, d, supply, {"demand": monthly(list(d))}


def test_transform_yoy():
    df = monthly([100.0] * 12 + [110.0] * 12)
    out = transform(df, "yoy")
    assert out.height == 12 and out["value"][0] == pytest.approx(10.0)


def test_purge_removes_demand():
    rng = np.random.default_rng(1)
    d = rng.normal(size=(200, 1))
    s = 0.9 * d + 0.1 * rng.normal(size=(200, 1))
    r, _ = purge_demand(s, d)
    assert abs(np.corrcoef(r[:, 0], d[:, 0])[0, 1]) < 1e-6


def test_first_component_handles_missing():
    rng = np.random.default_rng(2)
    f = rng.normal(size=120)
    x = np.column_stack([f + 0.3 * rng.normal(size=120) for _ in range(5)])
    x[:30, 0] = np.nan
    x[-3:, 1] = np.nan
    scores, loadings, explained = first_component(x)
    assert abs(np.corrcoef(scores, f)[0, 1]) > 0.95
    assert explained > 0.7
    assert np.all(np.sign(loadings) == np.sign(loadings[0]))


def test_index_recovers_factor_and_sign():
    f, _, supply, demand = synthetic()
    signs = {k: 1 for k in supply}
    res = build_index(supply, demand, signs, reference="s0")
    frame = res.to_frame()
    assert frame.height == len(f)
    assert np.corrcoef(res.index, f)[0, 1] > 0.9
    assert res.index.mean() == pytest.approx(0, abs=1e-9) and res.index.std() == pytest.approx(1, abs=1e-9)
    # contributions add up to the index (missing cells contribute zero after imputation, so allow slack)
    total = sum(res.contributions.values())
    assert np.corrcoef(total, res.index)[0, 1] > 0.95


def test_negative_sign_is_oriented():
    f, _, supply, demand = synthetic(seed=3)
    flipped = {k: v.with_columns(-pl.col("value")) for k, v in supply.items()}
    res = build_index(flipped, demand, {k: -1 for k in flipped}, reference="s0")
    assert np.corrcoef(res.index, f)[0, 1] > 0.9


def test_pulse():
    _, _, supply, _ = synthetic()
    p = pulse(supply, {k: 1 for k in supply})
    assert "pulse" in p.columns and p["series_available"].max() == 6
