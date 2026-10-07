"""Transformations, demand purge and principal component extraction.

Method, following the structure of the New York Fed GSCPI (Benigno et al., 2022):

1. Transform each input to a stationary-ish signal (levels for ratios and
   dwell times, 12-month changes for prices and volumes) and orient it so a
   higher value means more pressure.
2. Standardise each signal to mean 0, standard deviation 1 over the sample.
3. Purge demand: regress each supply signal on the demand proxies and keep
   the residual, so the index measures supply pressure rather than the
   business cycle.
4. Extract the first principal component of the purged panel. Missing
   values (series that start later or publish later) are handled by
   iterative rank-one imputation, a standard EM-style approach.
5. Sign the component so it correlates positively with the reference
   series, then scale it to mean 0 and standard deviation 1: the index
   reads as "standard deviations from its average".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl


def transform(df: pl.DataFrame, how: str) -> pl.DataFrame:
    """Apply a transform to a monthly (month, value) frame."""
    df = df.sort("month")
    v = pl.col("value")
    if how == "level":
        out = df
    elif how == "yoy":
        out = df.with_columns(((v / v.shift(12) - 1) * 100).alias("value"))
    elif how == "log_yoy":
        out = df.with_columns(((v.log() - v.log().shift(12)) * 100).alias("value"))
    elif how == "diff":
        out = df.with_columns((v - v.shift(1)).alias("value"))
    else:
        raise ValueError(how)
    return out.drop_nulls("value").filter(pl.col("value").is_finite())


def panel(series: dict[str, pl.DataFrame], start: str | None = None) -> pl.DataFrame:
    """Join {id: (month, value)} into one wide frame on a complete monthly calendar."""
    months = sorted({m for df in series.values() for m in df["month"].to_list()})
    if not months:
        raise ValueError("no data")
    cal = pl.DataFrame({"month": pl.date_range(months[0], months[-1], "1mo", eager=True)})
    wide = cal
    for sid, df in series.items():
        wide = wide.join(df.select("month", pl.col("value").alias(sid)), on="month", how="left")
    if start:
        wide = wide.filter(pl.col("month") >= pl.lit(f"{start}-01").str.to_date())
    return wide


def standardise(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mu = np.nanmean(x, axis=0)
    sd = np.nanstd(x, axis=0)
    sd[sd == 0] = 1.0
    return (x - mu) / sd, mu, sd


def purge_demand(supply: np.ndarray, demand: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Residuals of each supply column on demand columns (plus constant), using rows where all exist.

    Rows where a supply value exists but demand is missing keep the supply value
    unpurged rather than being dropped, so the index can extend to the latest
    month (a ragged edge). Returns residuals and the coefficient matrix.
    """
    n, k = supply.shape
    if demand.size == 0 or demand.shape[1] == 0:
        return supply.copy(), np.zeros((0, k))
    d_ok = ~np.isnan(demand).any(axis=1)
    X = np.column_stack([np.ones(n), np.nan_to_num(demand)])
    out = supply.copy()
    coefs = np.zeros((X.shape[1], k))
    for j in range(k):
        ok = d_ok & ~np.isnan(supply[:, j])
        if ok.sum() <= X.shape[1] + 2:
            continue
        beta, *_ = np.linalg.lstsq(X[ok], supply[ok, j], rcond=None)
        coefs[:, j] = beta
        fit_rows = d_ok & ~np.isnan(supply[:, j])
        out[fit_rows, j] = supply[fit_rows, j] - X[fit_rows] @ beta
    return out, coefs


def first_component(
    x: np.ndarray, max_iter: int = 500, tol: float = 1e-8
) -> tuple[np.ndarray, np.ndarray, float]:
    """First principal component of a panel with missing values.

    Iterates: fill missing cells with the rank-one reconstruction, recompute
    the SVD, until the reconstruction stops changing. Columns are re-standardised
    each pass. Returns scores (n), loadings (k) and the share of variance explained.
    """
    mask = np.isnan(x)
    filled = np.where(mask, 0.0, x)
    prev = None
    for _ in range(max_iter):
        z = (filled - filled.mean(axis=0)) / np.where(filled.std(axis=0) == 0, 1, filled.std(axis=0))
        u, s, vt = np.linalg.svd(z, full_matrices=False)
        scores, loadings = u[:, 0] * s[0], vt[0]
        recon = np.outer(scores, loadings)
        recon = recon * filled.std(axis=0) + filled.mean(axis=0)
        new = np.where(mask, recon, x)
        if prev is not None and np.nanmax(np.abs(new - prev)) < tol:
            filled = new
            break
        prev, filled = new, new
    explained = float(s[0] ** 2 / np.sum(s**2))
    return scores, loadings, explained


@dataclass
class IndexResult:
    months: list
    index: np.ndarray
    loadings: dict[str, float]
    explained: float
    contributions: dict[str, np.ndarray]
    n_available: np.ndarray
    supply_ids: list[str]
    demand_ids: list[str]
    notes: list[str] = field(default_factory=list)

    def to_frame(self) -> pl.DataFrame:
        cols = {
            "month": self.months,
            "cscpi": np.round(self.index, 4),
            "series_available": self.n_available.astype(int),
        }
        for sid, c in self.contributions.items():
            cols[f"contrib_{sid}"] = np.round(c, 4)
        return pl.DataFrame(cols)


def build_index(
    supply: dict[str, pl.DataFrame],
    demand: dict[str, pl.DataFrame],
    signs: dict[str, int],
    start: str | None = None,
    reference: str | None = None,
    min_available: int = 3,
) -> IndexResult:
    """Build the composite from transformed supply and demand series."""
    wide = panel({**supply, **demand}, start=start)
    s_ids, d_ids = list(supply), list(demand)
    S = wide.select(s_ids).to_numpy().astype(float) * np.array([signs.get(i, 1) for i in s_ids])
    D = wide.select(d_ids).to_numpy().astype(float) if d_ids else np.zeros((wide.height, 0))
    avail = (~np.isnan(S)).sum(axis=1)
    keep = avail >= min_available
    S, D = S[keep], D[keep]
    months = wide["month"].filter(pl.Series(keep)).to_list()
    avail = avail[keep]

    Sz, _, _ = standardise(S)
    Dz, _, _ = standardise(D) if D.shape[1] else (D, None, None)
    resid, _ = purge_demand(Sz, Dz)
    resid, _, _ = standardise(resid)
    scores, loadings, explained = first_component(resid)

    sign = 1.0
    if reference and reference in s_ids:
        j = s_ids.index(reference)
        ok = ~np.isnan(resid[:, j])
        if np.corrcoef(scores[ok], resid[ok, j])[0, 1] < 0:
            sign = -1.0
    elif loadings.sum() < 0:
        sign = -1.0
    scores, loadings = scores * sign, loadings * sign
    mu, sd = scores.mean(), scores.std()
    index = (scores - mu) / sd

    # Contribution of each series to each month's score (missing cells contribute 0).
    contrib = {sid: np.nan_to_num(resid[:, j]) * loadings[j] / sd for j, sid in enumerate(s_ids)}
    notes = []
    if explained < 0.3:
        notes.append(
            f"first component explains only {explained:.0%} of variance: inputs move weakly together"
        )
    return IndexResult(
        months=list(months),
        index=index,
        loadings={sid: float(loadings[j]) for j, sid in enumerate(s_ids)},
        explained=explained,
        contributions=contrib,
        n_available=avail,
        supply_ids=s_ids,
        demand_ids=d_ids,
        notes=notes,
    )


def pulse(supply: dict[str, pl.DataFrame], signs: dict[str, int], start: str | None = None) -> pl.DataFrame:
    """Fallback when the gate fails: each indicator as a signed z-score, plus their equal-weighted mean."""
    wide = panel(supply, start=start)
    ids = list(supply)
    S = wide.select(ids).to_numpy().astype(float) * np.array([signs.get(i, 1) for i in ids])
    Z, _, _ = standardise(S)
    out = wide.select("month")
    for j, sid in enumerate(ids):
        out = out.with_columns(pl.Series(f"z_{sid}", np.round(Z[:, j], 3)))
    mean = np.nanmean(Z, axis=1)
    return out.with_columns(
        pl.Series("pulse", np.round(mean, 3)),
        pl.Series("series_available", (~np.isnan(Z)).sum(axis=1)),
    )
