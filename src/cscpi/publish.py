"""Versioned outputs: CSV, JSON, chart, release notes and a LinkedIn draft."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl

from .model import IndexResult
from .pipeline import AuditRow


def describe(value: float) -> str:
    a = abs(value)
    level = "close to its average" if a < 0.5 else "moderately" if a < 1.0 else "well" if a < 2.0 else "far"
    if a < 0.5:
        return level
    return f"{level} {'above' if value > 0 else 'below'} average"


def drivers(result: IndexResult, k: int = 3) -> list[tuple[str, float]]:
    last = {sid: float(c[-1]) for sid, c in result.contributions.items()}
    return sorted(last.items(), key=lambda kv: abs(kv[1]), reverse=True)[:k]


def write_outputs(
    mode: str,
    result: IndexResult | None,
    pulse_df: pl.DataFrame | None,
    audit_rows: list[AuditRow],
    names: dict[str, str],
    out_dir: str | Path = "data",
    vintage: str | None = None,
) -> dict[str, Path]:
    out = Path(out_dir)
    (out / "releases").mkdir(parents=True, exist_ok=True)
    vintage = vintage or date.today().strftime("%Y-%m")  # noqa: DTZ011
    paths: dict[str, Path] = {}

    if mode == "composite" and result is not None:
        frame = result.to_frame()
        latest = frame.tail(1).row(0, named=True)
        prev = frame.tail(2).row(0, named=True) if frame.height > 1 else latest
        top = drivers(result)
        summary = {
            "vintage": vintage,
            "mode": mode,
            "latest_month": str(latest["month"]),
            "value": round(latest["cscpi"], 2),
            "previous": round(prev["cscpi"], 2),
            "change": round(latest["cscpi"] - prev["cscpi"], 2),
            "reading": describe(latest["cscpi"]),
            "variance_explained": round(result.explained, 3),
            "loadings": {k: round(v, 3) for k, v in result.loadings.items()},
            "drivers": [{"series": names.get(s, s), "contribution": round(c, 2)} for s, c in top],
            "notes": result.notes,
        }
        series_json = [
            {"month": str(r["month"]), "value": r["cscpi"]}
            for r in frame.select("month", "cscpi").iter_rows(named=True)
        ]
    else:
        frame = pulse_df if pulse_df is not None else pl.DataFrame()
        latest = frame.tail(1).row(0, named=True) if frame.height else {}
        summary = {
            "vintage": vintage,
            "mode": "pulse",
            "latest_month": str(latest.get("month")),
            "value": latest.get("pulse"),
            "reading": describe(latest.get("pulse") or 0.0),
            "notes": [
                "Fewer current series than the gate requires: publishing the indicator pulse, not the composite."
            ],
        }
        series_json = (
            [
                {"month": str(r["month"]), "value": r["pulse"]}
                for r in frame.select("month", "pulse").iter_rows(named=True)
            ]
            if frame.height
            else []
        )

    frame.write_csv(out / "cscpi.csv")
    frame.write_csv(out / "releases" / f"cscpi_{vintage}.csv")
    (out / "cscpi.json").write_text(
        json.dumps({"summary": summary, "series": series_json}, indent=2, default=str)
    )
    audit_table = pl.DataFrame([r.__dict__ for r in audit_rows])
    audit_table.write_csv(out / "audit.csv")
    paths.update(csv=out / "cscpi.csv", json=out / "cscpi.json", audit=out / "audit.csv")

    notes = release_notes(summary, audit_rows, names)
    (out / "releases" / f"notes_{vintage}.md").write_text(notes)
    (out / "releases" / f"linkedin_{vintage}.md").write_text(linkedin_post(summary))
    paths["notes"] = out / "releases" / f"notes_{vintage}.md"
    try:
        paths["chart"] = chart(frame, mode, out / "cscpi.png")
    except ImportError:
        pass
    return paths


def release_notes(summary: dict, audit_rows: list[AuditRow], names: dict[str, str]) -> str:
    lines = [
        f"# Canada Supply Chain Pressure Index: {summary['latest_month'][:7]} (vintage {summary['vintage']})",
        "",
        f"**{summary['value']:+.2f}** standard deviations: {summary['reading']}."
        if isinstance(summary.get("value"), (int, float))
        else "No value.",
    ]
    if "change" in summary:
        lines.append(f"Change from the previous month: {summary['change']:+.2f}.")
    if summary.get("drivers"):
        lines += ["", "Largest contributions this month:", ""]
        lines += [f"- {d['series']}: {d['contribution']:+.2f}" for d in summary["drivers"]]
    lines += ["", "Inputs:", "", "| Series | Role | Last month | Current |", "|---|---|---|---|"]
    for r in audit_rows:
        lines.append(
            f"| {names.get(r.id, r.id)} | {r.role} | {r.last or 'n/a'} | {'yes' if r.current else 'no'} |"
        )
    if summary.get("notes"):
        lines += ["", "Notes:", "", *[f"- {n}" for n in summary["notes"]]]
    lines += [
        "",
        "Method: docs/methodology.md. History is re-estimated each month; earlier vintages are kept in data/releases/.",
    ]
    return "\n".join(lines) + "\n"


def linkedin_post(summary: dict) -> str:
    v = summary.get("value")
    if not isinstance(v, (int, float)):
        return "No release this month.\n"
    drivers_txt = ", ".join(d["series"].lower() for d in summary.get("drivers", [])[:2]) or "several inputs"
    return (
        f"Canadian supply chain pressure, {summary['latest_month'][:7]}: {v:+.2f} standard deviations, {summary['reading']}.\n\n"
        f"What moved it: {drivers_txt}.\n\n"
        "The Canada Supply Chain Pressure Index is an open, monthly composite built only from public Canadian data, "
        "with demand effects removed so it reads supply pressure, not the business cycle. Method, data and code are open.\n\n"
        "Data and method: https://github.com/msachet5/canada-supply-chain-pressure-index\n"
    )


def chart(frame: pl.DataFrame, mode: str, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    col = "cscpi" if mode == "composite" else "pulse"
    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=150)
    x, y = frame["month"].to_list(), frame[col].to_list()
    ax.axhline(0, color="#9aa3b2", lw=0.8)
    ax.fill_between(
        x, y, 0, where=[v is not None and v > 0 for v in y], color="#d9534f", alpha=0.15, interpolate=True
    )
    ax.plot(x, y, color="#2f5bd3", lw=1.8)
    ax.set_title(
        "Canada Supply Chain Pressure Index" + (" (indicator pulse)" if mode != "composite" else ""),
        loc="left",
        fontsize=12,
    )
    ax.set_ylabel("standard deviations from average")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.text(
        1.0,
        -0.14,
        "Source: Statistics Canada, Transport Canada; method: github.com/msachet5/canada-supply-chain-pressure-index",
        transform=ax.transAxes,
        ha="right",
        fontsize=7,
        color="#5b6475",
    )
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
