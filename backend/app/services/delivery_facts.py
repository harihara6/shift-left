"""Loading and combining the per-period fact sets.

Facts are stored per quarter, because that is the smallest window the sources report cleanly.
A half or a year is assembled from its quarters here.

What can be combined honestly is combined: counts add, mean durations are weighted by their
sample size, distributions add bucket by bucket. What cannot is left out rather than faked - a
median of medians is not a median, so `median_days` comes back None for an aggregate and the
widget renders it as absent.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metrics import MetricsSnapshot

KIND = "delivery_facts"


@dataclass
class FactSet:
    """One period's facts, plus what is known about how they were assembled."""

    payload: dict[str, Any]
    period_keys: list[str]
    missing_keys: list[str]
    connector_keys: list[str]
    aggregated: bool

    @property
    def partial(self) -> bool:
        return bool(self.missing_keys)


def _weighted_mean(pairs: list[tuple[float | None, float]]) -> float | None:
    """Mean of values weighted by sample size. None when nothing carried a weight."""
    usable = [(value, weight) for value, weight in pairs if value is not None and weight > 0]
    if not usable:
        return None
    total_weight = sum(weight for _, weight in usable)
    return round(sum(value * weight for value, weight in usable) / total_weight, 1)


def _sum_buckets(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Add distributions bucket by bucket; average their cycle times by bucket volume."""
    if not blocks:
        return {"labels": [], "count": [], "cycle": []}
    labels = blocks[0]["labels"]
    counts = [sum(block["count"][i] for block in blocks) for i in range(len(labels))]
    cycles = [
        _weighted_mean([(block["cycle"][i], block["count"][i]) for block in blocks]) or 0
        for i in range(len(labels))
    ]
    return {"labels": labels, "count": counts, "cycle": cycles}


def _concat_series(blocks: list[dict[str, Any]], value_keys: list[str]) -> dict[str, Any]:
    """Lay time series end to end, oldest first, so a year reads as one continuous line."""
    out: dict[str, Any] = {"labels": []}
    for key in value_keys:
        out[key] = []
    for block in blocks:
        out["labels"].extend(block["labels"])
        for key in value_keys:
            out[key].extend(block[key])
    return out


def combine(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold several quarters into one fact set."""
    if len(blocks) == 1:
        return blocks[0]

    epics = [block["epics"] for block in blocks]
    stories = [block["stories"] for block in blocks]
    maint = [block["maint"] for block in blocks]
    prs = [block["prs"] for block in blocks]

    return {
        "provenance": "aggregated",
        "epics": {
            "avg_cycle_days": _weighted_mean([(e["avg_cycle_days"], e["sample"]) for e in epics]),
            # A median or a P85 cannot be recovered from summaries. Absent beats invented.
            "median_days": None,
            "p85_days": None,
            "sample": sum(e["sample"] for e in epics),
            "throughput": sum(e["throughput"] for e in epics),
            "size": _sum_buckets([e["size"] for e in epics]),
        },
        "stories": {
            "avg_cycle_days": _weighted_mean([(s["avg_cycle_days"], s["sample"]) for s in stories]),
            "median_days": None,
            "p85_days": None,
            "sample": sum(s["sample"] for s in stories),
            "throughput": sum(s["throughput"] for s in stories),
            "weekly": _concat_series([s["weekly"] for s in stories], ["done"]),
            "size": _sum_buckets([s["size"] for s in stories]),
        },
        "maint": {
            "avg_cycle_days": _weighted_mean([(m["avg_cycle_days"], m["sample"]) for m in maint]),
            "median_days": None,
            "sample": sum(m["sample"] for m in maint),
            "opened": sum(m["opened"] for m in maint),
            "resolved": sum(m["resolved"] for m in maint),
            # Backlog is a level, not a flow: the reading at the end of the window is the reading.
            "backlog_end": maint[-1]["backlog_end"],
            "priority": _sum_buckets([m["priority"] for m in maint]),
        },
        "prs": {
            "median_cycle_days": _weighted_mean([(p["median_cycle_days"], p["merged"]) for p in prs]),
            "avg_cycle_days": _weighted_mean([(p["avg_cycle_days"], p["merged"]) for p in prs]),
            "merged": sum(p["merged"] for p in prs),
            "small_pct": _weighted_mean([(p["small_pct"], p["merged"]) for p in prs]),
            "huge_count": sum(p["huge_count"] for p in prs),
            "buckets": {
                "labels": prs[0]["buckets"]["labels"],
                "cycle": [
                    _weighted_mean([(p["buckets"]["cycle"][i], p["merged"]) for p in prs]) or 0
                    for i in range(len(prs[0]["buckets"]["labels"]))
                ],
            },
            "cadence": _concat_series([p["cadence"] for p in prs], ["merged"]),
        },
        "detection": _concat_series(
            [block["detection"] for block in blocks], ["pr", "nightly", "prod"]
        ),
    }


async def load(session: AsyncSession, project_id: str, period_keys: list[str]) -> FactSet | None:
    """Load the quarters a period is made of, oldest first.

    Returns None only when nothing at all is stored. A partially covered window still renders,
    with `missing_keys` naming the quarters that were absent - a gap is reported, not filled in.
    """
    rows = (
        await session.execute(
            select(MetricsSnapshot).where(
                MetricsSnapshot.project_id == project_id,
                MetricsSnapshot.kind == KIND,
                MetricsSnapshot.period.in_(period_keys),
            )
        )
    ).scalars().all()
    by_key = {row.period: row for row in rows}

    ordered = [by_key[key] for key in period_keys if key in by_key]
    if not ordered:
        return None

    connector_keys: list[str] = []
    for row in ordered:
        for key in row.source_connector_keys or []:
            if key not in connector_keys:
                connector_keys.append(key)

    return FactSet(
        payload=combine([row.payload for row in ordered]),
        period_keys=[row.period for row in ordered],
        missing_keys=[key for key in period_keys if key not in by_key],
        connector_keys=connector_keys,
        aggregated=len(ordered) > 1,
    )
